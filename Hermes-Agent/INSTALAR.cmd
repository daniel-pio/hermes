@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar-tudo.ps1"
if errorlevel 1 (
  echo.
  echo Instalacao nao concluida. Leia a mensagem acima e tente novamente.
  pause
  exit /b 1
)
pause
