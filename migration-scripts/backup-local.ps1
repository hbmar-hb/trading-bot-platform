# =============================================================================
# Script de backup de PostgreSQL desde Windows local
# Ejecutar en PowerShell como administrador (o con Docker Desktop corriendo)
# =============================================================================

$ContainerName = "trading-bot-platform-postgres-1"
$BackupFile = "backup_trading_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
$BackupPath = Join-Path $PSScriptRoot $BackupFile

Write-Host "=== Backup de PostgreSQL ===" -ForegroundColor Cyan
Write-Host "Container: $ContainerName"
Write-Host "Destino: $BackupPath"

# Verificar que el contenedor existe
$container = docker ps --format "{{.Names}}" | Select-String $ContainerName
if (-not $container) {
    Write-Host "ERROR: No se encontro el contenedor '$ContainerName'" -ForegroundColor Red
    Write-Host "Contenedores activos:" -ForegroundColor Yellow
    docker ps --format "{{.Names}}"
    exit 1
}

# Hacer backup
docker exec $ContainerName pg_dump -U admin tradingbot | Out-File -FilePath $BackupPath -Encoding UTF8

if ($LASTEXITCODE -eq 0) {
    $size = (Get-Item $BackupPath).Length / 1KB
    Write-Host ""
    Write-Host "Backup completado exitosamente!" -ForegroundColor Green
    Write-Host "Archivo: $BackupPath"
    Write-Host "Tamano: $([math]::Round($size, 2)) KB"
    Write-Host ""
    Write-Host "Para copiar al VPS, ejecuta:" -ForegroundColor Yellow
    Write-Host "  scp $BackupPath deploy@IP_DEL_VPS:~/trading-bot-platform/"
} else {
    Write-Host "ERROR: El backup fallo" -ForegroundColor Red
    exit 1
}
