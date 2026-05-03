#!/bin/bash
# =============================================================================
# Script para subir DataControl al VPS como segundo proyecto
# Ejecutar como usuario deploy en el VPS
# =============================================================================

set -e

DC_DIR="/var/www/datacontrol"
NGINX_CONF="/etc/nginx/sites-available/trading"

echo "=== Instalando DataControl en el VPS ==="

# Crear directorio para DataControl
sudo mkdir -p $DC_DIR
sudo chown deploy:deploy $DC_DIR

# Aqui deberas copiar los archivos desde tu PC local:
# scp -r frontend_offline/dist/* deploy@IP_DEL_VPS:/var/www/datacontrol/

echo "=== Configurando Nginx para /datacontrol ==="

# Hacer backup de la config actual
sudo cp $NGINX_CONF ${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)

# Añadir location para DataControl
sudo tee -a $NGINX_CONF > /dev/null << 'EOF'

    # DataControl - Dashboard estatico
    location /datacontrol {
        alias /var/www/datacontrol;
        index index.html;
        try_files $uri $uri/ /datacontrol/index.html;

        # Cache para assets estaticos
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 1M;
            add_header Cache-Control "public, immutable";
        }
    }
EOF

# Verificar y recargar Nginx
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== Configuracion completada ==="
echo "DataControl estara disponible en: http://IP_DEL_VPS/datacontrol"
echo ""
echo "NOTA: Recuerda copiar los archivos desde tu PC con:"
echo "  scp -r frontend_offline/dist/* deploy@IP_DEL_VPS:/var/www/datacontrol/"
