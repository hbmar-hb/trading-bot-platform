#!/bin/bash
cp /root/nginx-trading.conf /etc/nginx/sites-available/trading
ln -sf /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/trading
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "Nginx configurado correctamente"
