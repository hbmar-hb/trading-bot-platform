# Guia: Subir DataControl al VPS (segundo proyecto)

## Resumen
DataControl es un frontend estatico (build de React/Vite). Se sirve directamente con Nginx en el mismo VPS donde ya tienes el Trading Bot.

## Acceso final
- `http://IP_DEL_VPS/` → Trading Bot Platform
- `http://IP_DEL_VPS/datacontrol/` → DataControl

## PASO 1: Copiar archivos al VPS

Desde tu PC Windows (PowerShell como administrador):

```powershell
# Variables (cambia la IP por la de tu VPS)
$VPS_IP = "IP_DE_TU_VPS"
$SSH_KEY = "C:\Apps\trading-bot-platform\trading-bot-platform\migration-scripts\hetzner_deploy_key"

# 1. Crear directorio en el VPS
ssh -i $SSH_KEY deploy@${VPS_IP} "sudo mkdir -p /var/www/datacontrol && sudo chown deploy:deploy /var/www/datacontrol"

# 2. Copiar los archivos estaticos
scp -i $SSH_KEY -r "C:\Apps\DataControl\frontend_offline\dist\*" deploy@${VPS_IP}:/var/www/datacontrol/
```

## PASO 2: Configurar Nginx

Conecta al VPS por SSH:
```bash
ssh -i hetzner_deploy_key deploy@IP_DE_TU_VPS
```

Edita la configuracion de Nginx:
```bash
sudo nano /etc/nginx/sites-available/trading
```

Añade estas lineas **antes** del ultimo `}`:

```nginx
    # DataControl - Dashboard estatico
    location /datacontrol {
        return 301 /datacontrol/;
    }

    location /datacontrol/ {
        alias /var/www/datacontrol/;
        index index.html;
        try_files $uri $uri/ =404;

        # Cache para assets estaticos
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 1M;
            add_header Cache-Control "public, immutable";
        }
    }
```

Guarda (Ctrl+O, Enter, Ctrl+X) y recarga Nginx:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

## PASO 3: Verificar

Abre en navegador:
- `http://IP_DE_TU_VPS/datacontrol/` → Debe cargar el dashboard

## Notas importantes

### Sobre Cloudflare Tunnel
Si estabas usando Cloudflare Tunnel para acceder a DataControl, puedes eliminarlo:
1. En tu PC local, cierra el tunnel de Cloudflare (el proceso `cloudflared`)
2. En el dashboard de Cloudflare, elimina el tunnel si ya no lo necesitas
3. El acceso ahora es directo por IP del VPS (mas rapido, sin intermediarios)

### Cuando compres dominio
Cuando tengas un dominio, puedes facilmente cambiar a:
- `trading.tudominio.com` → Trading Bot
- `data.tudominio.com` → DataControl

Solo necesitas:
1. Crear dos registros DNS tipo A apuntando a la misma IP del VPS
2. Actualizar la config de Nginx con `server_name` para cada dominio
3. Obtener SSL con Certbot para cada dominio

### Si quieres automatizar el deploy de DataControl
Puedes usar el script:
```powershell
cd C:\Apps\trading-bot-platform\trading-bot-platform\migration-scripts
.\deploy-datacontrol.ps1 -VpsIp "IP_DE_TU_VPS"
```
