@echo off
setlocal EnableDelayedExpansion
title Trading Bot Platform
cd /d "%~dp0"

:MENU
cls
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║      Trading Bot Platform — Arranque     ║
echo  ╚══════════════════════════════════════════╝
echo.
echo    [1]  Desarrollo  — Arranca todo con recarga automatica al guardar cambios.
echo                      Frontend en :5274, backend en :8100, Flower en :5556.
echo.
echo    [2]  Produccion  — Construye las imagenes optimizadas y arranca.
echo                      Frontend compilado en :80, backend en :8100.
echo.
echo    [3]  Parar       — Detiene todos los contenedores. Los datos se conservan.
echo.
echo    [4]  Logs        — Muestra los mensajes de los servicios en tiempo real.
echo.
echo    [5]  Estado      — Estado de cada contenedor y tiempo en marcha.
echo.
echo    [6]  ngrok       — Abre el tunel publico para TradingView ^(webhooks^).
echo                      Necesario para recibir senales desde internet.
echo.
echo    [7]  Salir
echo.
set /p OPCION=" Opcion: "

if "%OPCION%"=="1" goto DEV
if "%OPCION%"=="2" goto PROD
if "%OPCION%"=="3" goto STOP
if "%OPCION%"=="4" goto LOGS
if "%OPCION%"=="5" goto STATUS
if "%OPCION%"=="6" goto NGROK
if "%OPCION%"=="7" goto FIN
goto MENU


:: ─────────────────────────────────────────────────────────────
:DEV
cls
echo  [DEV] Verificando Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Docker no esta en ejecucion o no esta instalado.
    echo          Arranca Docker Desktop e intentalo de nuevo.
    echo.
    pause
    goto MENU
)
if not exist ".env" (
    echo  [AVISO] No se encontro .env — copiando desde .env.example...
    copy ".env.example" ".env" >nul
    echo.
    echo  Edita el fichero .env con tus claves antes de continuar.
    echo  ^(JWT_SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD^)
    echo.
    pause
    goto MENU
)
echo.
echo  [DEV] Arrancando servicios ^(hot reload activado^)...
echo        Frontend en  http://localhost:5274
echo        Backend en   http://localhost:8100
echo        API docs en  http://localhost:8100/docs
echo        Flower en    http://localhost:5556
echo.
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
if errorlevel 1 (
    echo.
    echo  [ERROR] Fallo al arrancar. Revisa los logs con la opcion 4.
    pause
    goto MENU
)
echo.
echo  [OK] Todos los servicios iniciados.
echo.
echo  Abriendo navegador...
start http://localhost:5274
echo.
pause
goto MENU


:: ─────────────────────────────────────────────────────────────
:PROD
cls
echo  [PROD] Verificando Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Docker no esta en ejecucion o no esta instalado.
    echo          Arranca Docker Desktop e intentalo de nuevo.
    echo.
    pause
    goto MENU
)
if not exist ".env" (
    echo  [AVISO] No se encontro .env — copiando desde .env.example...
    copy ".env.example" ".env" >nul
    echo.
    echo  Edita el fichero .env con tus claves antes de continuar.
    echo.
    pause
    goto MENU
)
echo.
echo  [PROD] Construyendo y arrancando servicios...
echo         Frontend en  http://localhost
echo         Backend en   http://localhost:8100
echo.
docker compose -f docker-compose.yml up --build -d
if errorlevel 1 (
    echo.
    echo  [ERROR] Fallo al arrancar. Revisa los logs con la opcion 4.
    pause
    goto MENU
)
echo.
echo  [OK] Todos los servicios iniciados.
echo.
echo  Abriendo navegador...
start http://localhost
echo.
pause
goto MENU


:: ─────────────────────────────────────────────────────────────
:STOP
cls
echo  [STOP] Deteniendo todos los contenedores...
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
echo.
echo  [OK] Contenedores detenidos. Los datos ^(postgres, redis^) se conservan.
echo       Para borrar los volumenes tambien: docker compose down -v
echo.
pause
goto MENU


:: ─────────────────────────────────────────────────────────────
:LOGS
cls
echo  Servicios disponibles:
echo    backend  celery_worker  celery_beat  frontend  postgres  redis  flower
echo.
set /p SERVICIO=" Servicio ^(o ENTER para todos^): "
echo.
echo  [Ctrl+C para volver al menu]
echo.
if "%SERVICIO%"=="" (
    docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=100
) else (
    docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=100 %SERVICIO%
)
goto MENU


:: ─────────────────────────────────────────────────────────────
:STATUS
cls
echo  ─── Estado de los contenedores ───────────────────────────
echo.
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
echo.
pause
goto MENU


:: ─────────────────────────────────────────────────────────────
:NGROK
cls
echo  [NGROK] Verificando configuracion...
if not exist "ngrok.bat" (
    echo  [ERROR] No se encontro ngrok.bat en esta carpeta.
    pause
    goto MENU
)
echo.
echo  Abriendo tunel ngrok en una nueva ventana...
echo  Una vez abierto, la URL publica aparecera en esa ventana.
echo.
echo  Usa esa URL en TradingView:
echo  https://TU_DOMINIO.ngrok-free.app/webhook/ID_DEL_BOT
echo.
start "ngrok — Trading Bot" cmd /k "cd /d "%~dp0" && ngrok.bat"
pause
goto MENU


:: ─────────────────────────────────────────────────────────────
:FIN
endlocal
exit /b 0
