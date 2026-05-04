@echo off
setlocal EnableDelayedExpansion
title Trading Bot Platform — ngrok
cd /d "%~dp0"

:: ─────────────────────────────────────────────────────────────
:: Configuracion — edita estas dos variables
:: ─────────────────────────────────────────────────────────────
set NGROK_TOKEN=3C1hgr4NSW8bteBz1gzkwyCPYKG_4Qc8kGHfb4wKsC9dxyZVT
set NGROK_DOMAIN=sun-astronomical-rosella.ngrok-free.dev

:: ─────────────────────────────────────────────────────────────
:: Ruta al ejecutable de ngrok
:: ─────────────────────────────────────────────────────────────
set NGROK_EXE=C:\Apps\ngrok\ngrok.exe

cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║       Trading Bot Platform — Tunel ngrok             ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: Verificar que ngrok existe
if not exist "%NGROK_EXE%" (
    echo  [ERROR] No se encontro ngrok.exe en %NGROK_EXE%
    echo.
    echo  Descarga ngrok desde https://ngrok.com/download
    echo  y coloca ngrok.exe en C:\Apps\ngrok\
    echo.
    pause
    exit /b 1
)

:: Verificar que el token esta configurado
if "%NGROK_TOKEN%"=="PEGA_AQUI_TU_AUTHTOKEN" (
    echo  [ERROR] No has configurado tu Authtoken.
    echo  Edita ngrok.bat y rellena NGROK_TOKEN con tu token de ngrok.com
    echo.
    pause
    exit /b 1
)

:: Verificar que el dominio esta configurado
if "%NGROK_DOMAIN%"=="PEGA_AQUI_TU_DOMINIO.ngrok-free.app" (
    echo  [ERROR] No has configurado tu dominio estatico.
    echo  Edita ngrok.bat y rellena NGROK_DOMAIN con tu dominio de ngrok.com
    echo.
    pause
    exit /b 1
)

:: Configurar el authtoken (solo la primera vez)
"%NGROK_EXE%" config add-authtoken %NGROK_TOKEN% >nul 2>&1

:: Cerrar cualquier proceso ngrok existente para liberar el tunel
echo  [INFO] Cerrando tuneles ngrok previos...
taskkill /IM ngrok.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo  [OK] Iniciando tunel hacia http://localhost:80
echo.
echo  URL publica ^(para TradingView^):
echo  https://%NGROK_DOMAIN%/webhook/ID_DE_TU_BOT
echo.
echo  Panel web local:   http://localhost
echo  Panel ngrok:       http://localhost:4040
echo.
echo  [Cierra esta ventana para detener el tunel]
echo.

:: Arrancar el tunel con dominio estatico
"%NGROK_EXE%" http 80 --domain=%NGROK_DOMAIN%
