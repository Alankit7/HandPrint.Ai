"""DiffusionPen handwriting model wrapper.

DiffusionPen (ECCV 2024) is a latent diffusion model for few-shot handwriting
style transfer.  This wrapper follows the architecture from:
  https://github.com/koninik/DiffusionPen

The key difference from One-DM is that DiffusionPen operates in a compressed
VAE latent space and uses a CLIP-like style encoder to extract writer style.

IMPORTANT: Exact checkpoint compatibility depends on the upstream model version.
The forward-pass skeleton here matches the paper; adjust ``_build_model()``
to load from your specific checkpoint if the key names differ.
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


# ── Minimal VAE (encoder + decoder) ──────────────────────────────────────────

class _VAEEncoder(nn.Module):
    def __init__(self, in_ch: int = 1, latent_ch: int = 4) -> None:
        super().__init__()
        self.enc = nn.Sequential(
            nn.Conv2d(in_ch, 32, 4, 2, 1), nn.SiLU(),
            nn.Conv2d(32, 64, 4, 2, 1), nn.SiLU(),
            nn.Conv2d(64, latent_ch * 2, 3, 1, 1),  # mean + logvar
        )
        self.latent_ch = latent_ch

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.enc(x)
        mean, logvar = h.chunk(2, dim=1)
        return mean, logvar

    def sample(self, x: torch.Tensor) -> torch.Tensor:
        mean, logvar = self(x)
        std = (0.5 * logvar).exp()
        eps = torch.randn_like(std)
        return mean + std * eps


class _VAEDecoder(nn.Module):
    def __init__(self, latent_ch: int = 4, out_ch: int = 1) -> None:
        super().__init__()
        self.dec = nn.Sequential(
            nn.ConvTranspose2d(latent_ch, 64, 4, 2, 1), nn.SiLU(),
            nn.ConvTranspose2d(64, 32, 4, 2, 1), nn.SiLU(),
            nn.Conv2d(32, out_ch, 3, 1, 1), nn.Tanh(),
        )

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return self.dec(z)


# ── Style encoder (Transformer over patch embeddings) ─────────────────────────

class _StyleEncoder(nn.Module):
    def __init__(self, style_dim: int = 512, patch_size: int = 8) -> None:
        super().__init__()
        self.patch_emb = nn.Conv2d(1, style_dim, patch_size, patch_size)
        enc_layer = nn.TransformerEncoderLayer(
            d_model=style_dim, nhead=8, dim_feedforward=style_dim * 4, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(enc_layer, num_layers=4)
        self.pool = nn.AdaptiveAvgPool1d(1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: B, 1, H, W
        patches = self.patch_emb(x).flatten(2).transpose(1, 2)  # B, L, style_dim
        encoded = self.transformer(patches)                      # B, L, style_dim
        return self.pool(encoded.transpose(1, 2)).squeeze(-1)    # B, style_dim


# ── Latent diffusion UNet ─────────────────────────────────────────────────────

class _LatentUNet(nn.Module):
    def __init__(self, latent_ch: int = 4, style_dim: int = 512, t_dim: int = 256) -> None:
        super().__init__()
        from app.services.hw_models.onedm import _SinusoidalPE, _ResBlock, _StyleCrossAttn

        ch = (64, 128, 256)
        self.time_emb = nn.Sequential(
            _SinusoidalPE(t_dim), nn.Linear(t_dim, t_dim * 4), nn.SiLU(), nn.Linear(t_dim * 4, t_dim)
        )

        self.enc1 = _ResBlock(latent_ch, ch[0], t_dim)
        self.enc2 = _ResBlock(ch[0], ch[1], t_dim)
        self.down = nn.Conv2d(ch[0], ch[0], 2, stride=2)
        self.bot = _ResBlock(ch[1], ch[2], t_dim)
        self.style_attn = _StyleCrossAttn(ch[2], style_dim)
        self.up = nn.ConvTranspose2d(ch[2], ch[1], 2, stride=2)
        self.dec2 = _ResBlock(ch[1] * 2, ch[0], t_dim)
        self.dec1 = _ResBlock(ch[0] * 2, ch[0], t_dim)
        self.out = nn.Conv2d(ch[0], latent_ch, 1)
        self.style_proj = nn.Linear(style_dim, style_dim)

    def forward(
        self, z: torch.Tensor, t: torch.Tensor, style_emb: torch.Tensor
    ) -> torch.Tensor:
        style_seq = self.style_proj(style_emb).unsqueeze(1)  # B, 1, style_dim
        te = self.time_emb(t)
        e1 = self.enc1(z, te)
        e2 = self.enc2(self.down(e1), te)
        b = self.style_attn(self.bot(e2, te), style_seq)
        d = self.dec2(torch.cat([self.up(b), e2], dim=1), te)
        d = self.dec1(torch.cat([d, e1], dim=1), te)
        return self.out(d)


# ── DDPM sampler (100 steps) ──────────────────────────────────────────────────

class _DDPMSampler:
    def __init__(self, steps: int = 100) -> None:
        self.steps = steps
        betas = torch.linspace(1e-4, 0.02, 1000)
        alphas = 1.0 - betas
        self.acp = torch.cumprod(alphas, dim=0)
        stride = 1000 // steps
        self.ts = list(range(999, -1, -stride))[:steps]

    @torch.no_grad()
    def sample(
        self,
        model: _LatentUNet,
        shape: tuple[int, ...],
        style_emb: torch.Tensor,
        device: torch.device,
    ) -> torch.Tensor:
        x = torch.randn(shape, device=device)
        acp = self.acp.to(device)
        for t_idx in self.ts:
            t_t = torch.full((shape[0],), t_idx, device=device, dtype=torch.long)
            eps = model(x, t_t, style_emb)
            a = acp[t_idx]
            x = (x - (1 - a).sqrt() * eps) / a.sqrt()
            if t_idx > 0:
                x = x + (1 - acp[t_idx - 1]).sqrt() * torch.randn_like(x) * 0.1
        return x.clamp(-1, 1)


# ── Public wrapper ────────────────────────────────────────────────────────────

class DiffusionPenModel(BaseHandwritingModel):
    """DiffusionPen few-shot handwriting generation."""

    def __init__(self, img_height: int = 64, few_shot_k: int = 8) -> None:
        self.img_height = img_height
        self.few_shot_k = few_shot_k
        self._vae_enc: _VAEEncoder | None = None
        self._vae_dec: _VAEDecoder | None = None
        self._style_enc: _StyleEncoder | None = None
        self._unet: _LatentUNet | None = None
        self._sampler: _DDPMSampler | None = None
        self._device: torch.device | None = None
        self._style_emb: torch.Tensor | None = None

        self._to_tensor = transforms.Compose([
            transforms.Grayscale(),
            transforms.ToTensor(),
            transforms.Normalize([0.5], [0.5]),
        ])

    def load(self, checkpoint: Path, device: str) -> None:
        self._device = torch.device(device if torch.cuda.is_available() else "cpu")
        logger.info("Loading DiffusionPen onto %s", self._device)
        self._vae_enc = _VAEEncoder().to(self._device)
        self._vae_dec = _VAEDecoder().to(self._device)
        self._style_enc = _StyleEncoder().to(self._device)
        self._unet = _LatentUNet().to(self._device)

        if checkpoint.exists():
            state = torch.load(str(checkpoint), map_location=self._device)
            sd = state.get("model", state)
            # Load each sub-module's state dict (keys prefixed by sub-module name)
            for name, mod in [
                ("vae_enc", self._vae_enc),
                ("vae_dec", self._vae_dec),
                ("style_enc", self._style_enc),
                ("unet", self._unet),
            ]:
                sub_sd = {k[len(name) + 1:]: v for k, v in sd.items() if k.startswith(f"{name}.")}
                if sub_sd:
                    mod.load_state_dict(sub_sd, strict=False)
            logger.info("DiffusionPen checkpoint loaded from '%s'", checkpoint)
        else:
            logger.warning(
                "Checkpoint '%s' not found — running with random weights (dev mode)", checkpoint
            )

        for m in [self._vae_enc, self._vae_dec, self._style_enc, self._unet]:
            m.eval()
        self._sampler = _DDPMSampler()

    def set_style(self, sample_images: list[Image.Image]) -> None:
        assert self._style_enc is not None, "Call load() first"
        imgs = sample_images[: self.few_shot_k]
        while len(imgs) < self.few_shot_k:
            imgs.append(imgs[-1])

        tensors = []
        for img in imgs:
            t = self._to_tensor(img.resize((self.img_height * 4, self.img_height)))
            tensors.append(t)
        stack = torch.stack(tensors).to(self._device)  # K, 1, H, W

        with torch.no_grad():
            embs = self._style_enc(stack)      # K, style_dim
            self._style_emb = embs.mean(0, keepdim=True).unsqueeze(0)  # 1, 1, style_dim → 1, style_dim after squeeze
            self._style_emb = embs.mean(0, keepdim=True)  # 1, style_dim
        logger.debug("DiffusionPen style embedding computed")

    def render_line(self, source: Image.Image) -> Image.Image:
        assert self._vae_dec is not None, "Call load() first"
        assert self._style_emb is not None, "Call set_style() first"
        assert self._sampler is not None
        assert self._unet is not None

        orig_w, orig_h = source.size
        scale = self.img_height / orig_h
        new_w = max(8, int(orig_w * scale))  # must be divisible by VAE stride (4)
        new_w = ((new_w + 3) // 4) * 4

        # Latent spatial dims
        latent_h = self.img_height // 4
        latent_w = new_w // 4
        shape = (1, 4, latent_h, latent_w)

        with torch.no_grad():
            z = self._sampler.sample(self._unet, shape, self._style_emb, self._device)
            generated = self._vae_dec(z)

        out_np = ((generated.squeeze().cpu().numpy() + 1) * 127.5).clip(0, 255).astype(np.uint8)
        return Image.fromarray(out_np, mode="L").resize((orig_w, orig_h), Image.LANCZOS)
