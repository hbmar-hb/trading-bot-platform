#!/bin/bash
set -e

# Configura el subdominio dev.getquantum.app con SSL.
# Debe ejecutarse como root (sudo).

CONF_SRC="/home/deploy/apps/trading-bot-platform-dev/nginx-dev.conf"
CONF_DST="/etc/nginx/sites-available/dev.getquantum.app"

echo "[setup-dev-domain] Copiando configuración de Nginx..."
cp "$CONF_SRC" "$CONF_DST"
ln -sf "$CONF_DST" /etc/nginx/sites-enabled/dev.getquantum.app

echo "[setup-dev-domain] Verificando configuración de Nginx..."
nginx -t

echo "[setup-dev-domain] Solicitando certificado SSL para dev.getquantum.app..."
certbot --nginx -d dev.getquantum.app --non-interactive --agree-tos -m admin@getquantum.app --redirect

echo "[setup-dev-domain] Recargando Nginx..."
systemctl reload nginx

echo "[setup-dev-domain] Listo. Prueba: https://dev.getquantum.app"
