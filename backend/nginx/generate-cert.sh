#!/usr/bin/env bash
# generate-cert.sh — create a self-signed TLS certificate for development.
# For production, replace these with certs from Let's Encrypt or your CA.
set -euo pipefail

CERT_DIR="${1:-./certs}"
mkdir -p "$CERT_DIR"

echo "Generating self-signed certificate in '$CERT_DIR'..."

openssl req -x509 -newkey rsa:2048 \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -days 365 \
    -nodes \
    -subj "/C=US/ST=CA/L=SF/O=HandprintAI/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "Done."
echo "  Certificate: $CERT_DIR/cert.pem"
echo "  Private key:  $CERT_DIR/key.pem"
echo ""
echo "For production, replace these with Let's Encrypt certs:"
echo "  certbot certonly --standalone -d your-domain.com"
echo "  cp /etc/letsencrypt/live/your-domain.com/fullchain.pem $CERT_DIR/cert.pem"
echo "  cp /etc/letsencrypt/live/your-domain.com/privkey.pem  $CERT_DIR/key.pem"
