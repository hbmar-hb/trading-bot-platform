@echo off
setlocal EnableDelayedExpansion
title Trading Bot Platform — Instalacion
cd /d "%~dp0"

cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║       Trading Bot Platform — Instalacion             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ─────────────────────────────────────────────────────────────
:: PASO 1 — Verificar Docker
:: ─────────────────────────────────────────────────────────────
echo  [1/4] Verificando Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Docker no esta instalado o no esta en ejecucion.
    echo.
    echo  Instala Docker Desktop desde:
    echo  https://www.docker.com/products/docker-desktop
    echo.
    echo  Una vez instalado y abierto, vuelve a ejecutar este script.
    echo.
    pause
    exit /b 1
)
echo  [OK] Docker detectado.
echo.

:: ─────────────────────────────────────────────────────────────
:: PASO 2 — Verificar o crear el .env
:: ─────────────────────────────────────────────────────────────
echo  [2/4] Verificando configuracion...
if exist ".env" (
    echo  [OK] Fichero .env encontrado.
) else (
    echo  [AVISO] No se encontro el fichero .env
    echo.
    echo  Tienes dos opciones:
    echo.
    echo    [A] Copiar el .env desde el equipo principal ^(recomendado^)
    echo        Copia el fichero .env a esta carpeta y vuelve a ejecutar.
    echo.
    echo    [B] Generar uno nuevo
    echo        Se copiara .env.example y tendras que rellenarlo a mano.
    echo.
    set /p OPCION_ENV=" Elige A o B: "

    if /i "!OPCION_ENV!"=="B" (
        copy ".env.example" ".env" >nul
        echo.
        echo  Fichero .env creado desde .env.example.
        echo.
        echo  ┌────────────────────────────────────────────────────────┐
        echo  │  IMPORTANTE: Abre el fichero .env y rellena:           │
        echo  │                                                        │
        echo  │  POSTGRES_PASSWORD = una contrasena segura             │
        echo  │  JWT_SECRET_KEY    = genera con Python:                │
        echo  │    python -c "import secrets;                          │
        echo  │               print^(secrets.token_hex^(32^)^)"           │
        echo  │  ENCRYPTION_KEY   = genera con Python:                 │
        echo  │    python -c "from cryptography.fernet import Fernet;  │
        echo  │               print^(Fernet.generate_key^(^).decode^(^)^)"  │
        echo  │                                                        │
        echo  │  Y actualiza DATABASE_URL con tu POSTGRES_PASSWORD     │
        echo  └────────────────────────────────────────────────────────┘
        echo.
        echo  Cuando hayas rellenado el .env, vuelve a ejecutar este script.
        echo.
        pause
        exit /b 0
    ) else (
        echo.
        echo  Copia el fichero .env del equipo principal a esta carpeta
        echo  y vuelve a ejecutar install.bat
        echo.
        pause
        exit /b 0
    )
)
echo.

:: ─────────────────────────────────────────────────────────────
:: PASO 3 — Construir imagenes Docker
:: ─────────────────────────────────────────────────────────────
echo  [3/4] Construyendo imagenes Docker...
echo  ^(La primera vez puede tardar 5-10 minutos^)
echo.
docker compose -f docker-compose.yml build
if errorlevel 1 (
    echo.
    echo  [ERROR] Fallo al construir las imagenes.
    echo  Revisa que el fichero .env esta bien configurado.
    echo.
    pause
    exit /b 1
)
echo.
echo  [OK] Imagenes construidas correctamente.
echo.

:: ─────────────────────────────────────────────────────────────
:: PASO 4 — Primer arranque
:: ─────────────────────────────────────────────────────────────
echo  [4/4] Arrancando por primera vez...
docker compose -f docker-compose.yml up -d
if errorlevel 1 (
    echo.
    echo  [ERROR] Fallo al arrancar los servicios.
    echo.
    pause
    exit /b 1
)

:: Esperar a que el backend arranque
echo.
echo  Esperando a que el backend este listo...
timeout /t 10 /nobreak >nul

:: ─────────────────────────────────────────────────────────────
:: Instalacion completada
:: ─────────────────────────────────────────────────────────────
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║         Instalacion completada con exito             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  La aplicacion esta corriendo en:
echo.
echo    Panel web:  http://localhost
echo    API docs:   http://localhost:8100/docs
echo.
echo  Credenciales iniciales:
echo    Usuario:    admin
echo    Contrasena: Admin1234
echo.
echo  IMPORTANTE: Cambia la contrasena en Ajustes tras el primer login.
echo.
echo  Para arrancar/parar la aplicacion en el futuro usa start.bat
echo.
pause
start http://localhost

endlocal
