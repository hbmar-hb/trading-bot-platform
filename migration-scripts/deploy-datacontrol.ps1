# =============================================================================
# Script de PowerShell para subir DataControl al VPS desde Windows
# Ejecutar desde la carpeta C:\Apps\DataControl
# =============================================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$VpsIp,

    [string]$SshKey = "$PSScriptRoot\hetzner_deploy_key",
    [string]$DcSource = "C:\Apps\DataControl\frontend_offline\dist",
    [string]$VpsUser = "deploy"
)

Write-Host "=== Deploy DataControl al VPS ===" -ForegroundColor Cyan
Write-Host "VPS IP: $VpsIp"
Write-Host "Origen: $DcSource"
Write-Host ""

# Verificar que existe la carpeta fuente
if (-not (Test-Path $DcSource)) {
    Write-Host "ERROR: No se encontro la carpeta $DcSource" -ForegroundColor Red
    exit 1
}

# Verificar que existe la clave SSH
if (-not (Test-Path $SshKey)) {
    Write-Host "ERROR: No se encontro la clave SSH: $SshKey" -ForegroundColor Red
    exit 1
}

Write-Host "=== 1. Creando directorio en el VPS ===" -ForegroundColor Yellow
ssh -i $SshKey "${VpsUser}@${VpsIp}" "sudo mkdir -p /var/www/datacontrol && sudo chown ${VpsUser}:${VpsUser} /var/www/datacontrol"

Write-Host "=== 2. Copiando archivos estaticos ===" -ForegroundColor Yellow
scp -i $SshKey -r "${DcSource}\*" "${VpsUser}@${VpsIp}:/var/www/datacontrol/"

Write-Host "=== 3. Actualizando Nginx ===" -ForegroundColor Yellow
$nginxConfig = @"

    # DataControl - Dashboard estatico
    location /datacontrol {
        alias /var/www/datacontrol;
        index index.html;
        try_files `$uri `$uri/ =404;
    }

    # Redirigir /datacontrol/ a /datacontrol
    location = /datacontrol {
        return 301 /datacontrol/;
    }

    location /datacontrol/ {
        alias /var/www/datacontrol/;
        index index.html;
        try_files `$uri `$uri/ /datacontrol/index.html;

        # Cache para assets estaticos
        location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 1M;
            add_header Cache-Control "public, immutable";
        }
    }
"@

# Guardar config temporal y copiar al VPS
$tempFile = [System.IO.Path]::GetTempFileName()
$nginxConfig | Out-File -FilePath $tempFile -Encoding UTF8
scp -i $SshKey $tempFile "${VpsUser}@${VpsIp}:/tmp/datacontrol_nginx.conf"

# Insertar la config en el archivo de Nginx (antes del cierre del server block)
ssh -i $SshKey "${VpsUser}@${VpsIp}" @"
    sudo cp /etc/nginx/sites-available/trading /etc/nginx/sites-available/trading.backup.
$(Get-Date -Format 'yyyyMMdd_HHmmss')
    sudo sed -i '/^}/e cat /tmp/datacontrol_nginx.conf' /etc/nginx/sites-available/trading
    sudo rm /tmp/datacontrol_nginx.conf
    sudo nginx -t && sudo systemctl reload nginx
"@

Remove-Item $tempFile

Write-Host ""
Write-Host "=== Deploy completado ===" -ForegroundColor Green
Write-Host "DataControl disponible en: http://${VpsIp}/datacontrol"
Write-Host ""
