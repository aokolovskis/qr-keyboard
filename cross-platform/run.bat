@echo off
rem Starts QRKeyboard on Windows. Everything it needs (uv, Python, libraries) is downloaded
rem into this folder (.tools\ and .venv\) on first run; nothing is installed system-wide.
setlocal
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "UV_VERSION=0.9.5"
set "TOOLS=%HERE%\.tools"

set "UV_CACHE_DIR=%TOOLS%\cache"
set "UV_PYTHON_INSTALL_DIR=%TOOLS%\python"
set "UV_PYTHON_BIN_DIR=%TOOLS%\bin"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_PROJECT_ENVIRONMENT=%HERE%\.venv"
set "UV_NO_CONFIG=1"

set "ARCH=x86_64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=aarch64"

if not exist "%TOOLS%\uv.exe" (
    echo Downloading uv %UV_VERSION% into the .tools folder ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol='Tls12';" ^
      "New-Item -ItemType Directory -Force -Path $env:TOOLS | Out-Null;" ^
      "$zip = Join-Path $env:TOOLS 'uv.zip';" ^
      "Invoke-WebRequest -UseBasicParsing -OutFile $zip -Uri ('https://github.com/astral-sh/uv/releases/download/' + $env:UV_VERSION + '/uv-' + $env:ARCH + '-pc-windows-msvc.zip');" ^
      "Expand-Archive -Force -Path $zip -DestinationPath $env:TOOLS; Remove-Item $zip"
    if errorlevel 1 (
        echo Download failed.
        pause
        exit /b 1
    )
)

"%TOOLS%\uv.exe" run --project "%HERE%" --frozen python "%HERE%\qrkeyboard.py" %*
if errorlevel 1 pause
endlocal
