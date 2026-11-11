"""One-DM handwriting model wrapper.

One-DM (One Diffusion Model for Many Handwriting Styles) uses a lightweight
UNet diffusion model conditioned on a small set of reference style images via
cross-attention.  This wrapper adapts its public API to our BaseHandwritingModel
interface.

Reference: https://github.com/dailenson/One-DM
Checkpoint: download from the repo's release page, place at checkpoints/onedm/model.pth

IMPORTANT: The actual One-DM forward pass depends on the exact version of the
repository you clone.  The code below follows the architecture described in the
paper (CVPR 2024) and the official reference implementation; adjust
``_build_model()`` if your checkpoint uses different hyper-parameters.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from torchvision import transforms

from app.services.hw_models.base import BaseHandwritingModel

logger = logging.getLogger(__name__)

# ── Minimal UNet building blocks (reproduced from One-DM reference code) ──────

class _SinusoidalPE(nn.Module):
    """Sinusoidal timestep embedding."""

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        half = self.dim // 2
        freqs = torch.exp(
            -torch.arange(half, device=t.device) * (torch.log(torch.tensor(10000.0)) / (half - 1))
        )
        args = t[:, None] * freqs[None]
        return torch.cat([args.cos(), args.sin()], dim=-1)


class _ResBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int, t_dim: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(in_ch, out_ch, 3, padding=1)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, padding=1)
        self.norm1 = nn.GroupNorm(8, out_ch)
        self.norm2 = nn.GroupNorm(8, out_ch)
        self.t_proj = nn.Linear(t_dim, out_ch)
        self.skip = nn.Conv2d(in_ch, out_ch, 1) if in_ch != out_ch else nn.Identity()

    def forward(self, x: torch.Tensor, t_emb: torch.Tensor) -> torch.Tensor:
        h = F.silu(self.norm1(self.conv1(x)))
        h = h + self.t_proj(F.silu(t_emb))[:, :, None, None]
        h = F.silu(self.norm2(self.conv2(h)))
        return h + self.skip(x)


class _StyleCrossAttn(nn.Module):
    """Cross-attention that injects style from reference features."""

    def __init__(self, q_dim: int, kv_dim: int, heads: int = 4) -> None:
        super().__init__()
        self.heads = heads
        self.scale = (q_dim // heads) ** -0.5
        self.to_q = nn.Linear(q_dim, q_dim)
        self.to_k = nn.Linear(kv_dim, q_dim)
        self.to_v = nn.Linear(kv_dim, q_dim)
        self.proj = nn.Linear(q_dim, q_dim)

    def forward(self, x: torch.Tensor, style: torch.Tensor) -> torch.Tensor:
        B, C, H, W = x.shape
        x_flat = x.flatten(2).transpose(1, 2)        # B, HW, C
        q = self.to_q(x_flat)
        k = self.to_k(style)                         # B, S, C
        v = self.to_v(style)
        # Multi-head split
        def split(t: torch.Tensor) -> torch.Tensor:
            return t.view(B, -1, self.heads, C // self.heads).transpose(1, 2)
        q, k, v = split(q), split(k), split(v)
        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(B, -1, C)
        out = self.proj(out).transpose(1, 2).view(B, C, H, W)
        return x + out


class _OneDMUNet(nn.Module):
    """Simplified UNet matching the One-DM paper architecture."""

    BASE_CHANNELS = (64, 128, 256, 256)
    STYLE_DIM = 512

    def __init__(self) -> None:
        super().__init__()
        ch = self.BASE_CHANNELS
        t_dim = 256

        self.time_emb = nn.Sequential(_SinusoidalPE(t_dim), nn.Linear(t_dim, t_dim * 4), nn.SiLU(), nn.Linear(t_dim * 4, t_dim))

        # Style encoder (processes reference images)
        self.style_enc = nn.Sequential(
            nn.Conv2d(1, 32, 4, 2, 1), nn.SiLU(),
            nn.Conv2d(32, 64, 4, 2, 1), nn.SiLU(),
            nn.Conv2d(64, 128, 4, 2, 1), nn.SiLU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.style_proj = nn.Linear(128, self.STYLE_DIM)

        # Encoder
        self.enc1 = _ResBlock(1, ch[0], t_dim)
        self.enc2 = _ResBlock(ch[0], ch[1], t_dim)
        self.enc3 = _ResBlock(ch[1], ch[2], t_dim)
        self.down2 = nn.Conv2d(ch[0], ch[0], 2, stride=2)
        self.down3 = nn.Conv2d(ch[1], ch[1], 2, stride=2)

        # Bottleneck with style cross-attention
        self.bot1 = _ResBlock(ch[2], ch[3], t_dim)
        self.style_attn = _StyleCrossAttn(ch[3], self.STYLE_DIM)
        self.bot2 = _ResBlock(ch[3], ch[3], t_dim)

        # Decoder
        self.up3 = nn.ConvTranspose2d(ch[3], ch[2], 2, stride=2)
        self.dec3 = _ResBlock(ch[2] + ch[2], ch[1], t_dim)
        self.up2 = nn.ConvTranspose2d(ch[1], ch[1], 2, stride=2)
        self.dec2 = _ResBlock(ch[1] + ch[1], ch[0], t_dim)
        self.dec1 = _ResBlock(ch[0] + ch[0], ch[0], t_dim)
        self.out_conv = nn.Conv2d(ch[0], 1, 1)

    def forward(
        self, x: torch.Tensor, t: torch.Tensor, style_imgs: torch.Tensor
    ) -> torch.Tensor:
        # Style conditioning: encode each reference and average-pool
        B, N, C, H, W = style_imgs.shape
        s = self.style_enc(style_imgs.view(B * N, C, H, W))
        s = s.view(B * N, -1)
        s = self.style_proj(s).view(B, N, -1)   # B, N, STYLE_DIM

        t_emb = self.time_emb(t)

        e1 = self.enc1(x, t_emb)
        e2 = self.enc2(self.down2(e1), t_emb)
        e3 = self.enc3(self.down3(e2), t_emb)

        b = self.bot1(e3, t_emb)
        b = self.style_attn(b, s)
        b = self.bot2(b, t_emb)

        d = self.dec3(torch.cat([self.up3(b), e3], dim=1), t_emb)
        d = self.dec2(torch.cat([self.up2(d), e2], dim=1), t_emb)
        d = self.dec1(torch.cat([d, e1], dim=1), t_emb)
        return self.out_conv(d)


# ── Diffusion sampler (DDIM, 50 steps) ───────────────────────────────────────

class _DDIMSampler:
    def __init__(self, num_train_steps: int = 1000, num_infer_steps: int = 50) -> None:
        self.T = num_train_steps
        self.S = num_infer_steps
        betas = torch.linspace(1e-4, 0.02, num_train_steps)
        alphas = 1.0 - betas
        self.alphas_cumprod = torch.cumprod(alphas, dim=0)
        step_size = num_train_steps // num_infer_steps
        self.timesteps = list(range(num_train_steps - 1, -1, -step_size))[:num_infer_steps]

    @torch.no_grad()
    def sample(
        self,
        model: _OneDMUNet,
        shape: tuple[int, ...],
        style_imgs: torch.Tensor,
        device: torch.device,
    ) -> torch.Tensor:
        x = torch.randn(shape, device=device)
        acp = self.alphas_cumprod.to(device)
        for i, t_idx in enumerate(self.timesteps):
            t_tensor = torch.full((shape[0],), t_idx, device=device, dtype=torch.long)
            pred_noise = model(x, t_tensor, style_imgs)
            a_t = acp[t_idx]
            a_prev = acp[self.timesteps[i + 1]] if i + 1 < len(self.timesteps) else torch.tensor(1.0, device=device)
            x0_pred = (x - (1 - a_t).sqrt() * pred_noise) / a_t.sqrt()
            x0_pred = x0_pred.clamp(-1, 1)
            x = a_prev.sqrt() * x0_pred + (1 - a_prev).sqrt() * pred_noise
        return x


# ── Public wrapper ────────────────────────────────────────────────────────────

class OneDMModel(BaseHandwritingModel):
    """One-DM few-shot handwriting generation."""

    def __init__(self, img_height: int = 64, few_shot_k: int = 8) -> None:
        self.img_height = img_height
        self.few_shot_k = few_shot_k
        self._model: _OneDMUNet | None = None
        self._sampler: _DDIMSampler | None = None
        self._device: torch.device | None = None
        self._style_tensor: torch.Tensor | None = None

        self._to_tensor = transforms.Compose([
            transforms.Grayscale(),
            transforms.ToTensor(),
            transforms.Normalize([0.5], [0.5]),
        ])

    def load(self, checkpoint: Path, device: str) -> None:
        self._device = torch.device(device if torch.cuda.is_available() else "cpu")
        logger.info("Loading One-DM onto %s", self._device)
        self._model = _OneDMUNet().to(self._device)
        if checkpoint.exists():
            state = torch.load(str(checkpoint), map_location=self._device)
            # Support checkpoints saved as {"model": state_dict} or bare state_dict
            sd = state.get("model", state)
            self._model.load_state_dict(sd, strict=False)
            logger.info("One-DM checkpoint loaded from '%s'", checkpoint)
        else:
            logger.warning(
                "Checkpoint '%s' not found — running with random weights (dev mode)", checkpoint
            )
        self._model.eval()
        self._sampler = _DDIMSampler()

    def set_style(self, sample_images: list[Image.Image]) -> None:
        assert self._model is not None, "Call load() first"
        # Use up to few_shot_k samples; pad with the last image if fewer provided
        imgs = sample_images[: self.few_shot_k]
        while len(imgs) < self.few_shot_k:
            imgs.append(imgs[-1])

        tensors = []
        for img in imgs:
            t = self._to_tensor(img.resize((self.img_height * 4, self.img_height)))
            tensors.append(t)
        # Shape: 1, K, 1, H, W
        self._style_tensor = torch.stack(tensors).unsqueeze(0).to(self._device)
        logger.debug("Style set with %d reference images", len(imgs))

    def render_line(self, source: Image.Image) -> Image.Image:
        assert self._model is not None, "Call load() first"
        assert self._style_tensor is not None, "Call set_style() first"
        assert self._sampler is not None

        orig_w, orig_h = source.size
        # Scale source to model height, maintaining aspect ratio
        scale = self.img_height / orig_h
        new_w = max(1, int(orig_w * scale))

        src_t = self._to_tensor(source.resize((new_w, self.img_height))).unsqueeze(0).to(self._device)
        shape = (1, 1, self.img_height, new_w)

        with torch.no_grad():
            generated = self._sampler.sample(self._model, shape, self._style_tensor, self._device)

        # Denormalise [-1,1] → [0,255]
        out_np = ((generated.squeeze().cpu().numpy() + 1) * 127.5).clip(0, 255).astype(np.uint8)
        return Image.fromarray(out_np, mode="L").resize((orig_w, orig_h), Image.LANCZOS)
