$ContainerName = "trading-bot-platform-postgres-1"
$BackupFile = "data_only_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
$BackupPath = Join-Path $PSScriptRoot $BackupFile

Write-Host "Generando backup de datos..." -ForegroundColor Cyan

$header = "SET session_replication_role = replica;`n"
$footer = "`nSET session_replication_role = DEFAULT;`n"

$data = docker exec $ContainerName pg_dump -U admin tradingbot --data-only --exclude-table=alembic_version

$content = $header + ($data -join "`n") + $footer
[System.IO.File]::WriteAllText($BackupPath, $content, [System.Text.Encoding]::UTF8)

Write-Host "Backup creado: $BackupPath" -ForegroundColor Green
Write-Host "Tamaño: $([math]::Round((Get-Item $BackupPath).Length / 1KB, 2)) KB"
