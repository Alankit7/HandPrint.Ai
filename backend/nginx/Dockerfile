# ── nginx reverse proxy for Handprint AI ────────────────────────────────────
FROM nginx:1.25-alpine

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our production config
COPY prod.conf /etc/nginx/conf.d/handprint.conf

# Create cert directory (certs are mounted as a volume in production)
RUN mkdir -p /etc/nginx/certs

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/health | grep -q '"status":"ok"' || exit 1
