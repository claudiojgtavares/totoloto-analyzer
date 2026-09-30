@echo off
setlocal

rem Usa sempre a pasta onde este ficheiro BAT se encontra.
cd /d "%~dp0"
title Totoloto Analyzer

echo A fechar instancias antigas do Flask...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$processos = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($processId in $processos) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }"

echo ========================================
echo       TOTOLOTO ANALYZER - ARRANQUE
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERRO: O ambiente Python .venv nao foi encontrado.
    echo Pasta esperada: "%~dp0.venv"
    echo.
    pause
    exit /b 1
)

if not exist "C:\xampp\mysql\bin\mysqld.exe" (
    echo ERRO: O MySQL do XAMPP nao foi encontrado.
    echo Caminho esperado: C:\xampp\mysql\bin\mysqld.exe
    echo.
    pause
    exit /b 1
)

echo [1/4] A verificar o MySQL...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$mysqlAtivo = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue; if (-not $mysqlAtivo) { Start-Process -FilePath 'C:\xampp\mysql\bin\mysqld.exe' -ArgumentList @('--defaults-file=C:\xampp\mysql\bin\my.ini','--standalone') -WorkingDirectory 'C:\xampp\mysql\bin' -WindowStyle Hidden; $limite = (Get-Date).AddSeconds(20); do { Start-Sleep -Milliseconds 500; $mysqlAtivo = Get-NetTCPConnection -LocalPort 3306 -State Listen -ErrorAction SilentlyContinue } until ($mysqlAtivo -or (Get-Date) -ge $limite); if (-not $mysqlAtivo) { exit 1 } }"

if errorlevel 1 (
    echo ERRO: Nao foi possivel iniciar o MySQL.
    echo Tente executar este ficheiro como administrador.
    echo.
    pause
    exit /b 1
)

echo [2/4] A activar o ambiente Python...
call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :erro

echo [3/4] A criar ou actualizar a base de dados...
"%~dp0.venv\Scripts\python.exe" "%~dp0criar_banco.py"
if errorlevel 1 goto :erro

echo [4/4] A iniciar o sistema...
echo.
echo O navegador sera aberto em http://127.0.0.1:5000
echo Mantenha esta janela aberta enquanto utiliza o sistema.
echo Para encerrar, prima Ctrl+C nesta janela.
echo.

start "" /min powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000'"
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"

echo.
echo O sistema foi encerrado.
pause
exit /b 0

:erro
echo.
echo ERRO: O sistema nao conseguiu arrancar.
pause
exit /b 1
