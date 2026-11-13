@echo off
rem  JARVIS installer. Double-click to install or update JARVIS for your
rem  Windows account. It fetches the real installer (install.ps1) from the
rem  JARVIS repository on GitHub and runs it. Nothing here needs
rem  administrator rights, though Windows may ask once while installing
rem  Python or Git.
title Install JARVIS
echo.
echo   This will install JARVIS on this computer.
echo   It needs an internet connection, about 3 GB of disk space,
echo   and 10 to 20 minutes. You can keep using the computer meanwhile.
echo.
pause
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-Expression (Invoke-RestMethod 'https://raw.githubusercontent.com/Shadi-Atieh001/Jarvis/main/installer/install.ps1')"
if errorlevel 1 (
  echo.
  echo   The installer could not be started. Check your internet connection and try again.
  pause
)
