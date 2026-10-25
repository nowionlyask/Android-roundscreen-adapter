@echo off
chcp 65001 >nul
REM Watch Control 一键启动（Windows）
REM
REM 用法：
REM   run.bat            启动中转服务
REM   run.bat picker     启动点选工具
REM   run.bat setup      生成配对密钥

setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%WC_HOME%"=="" set WC_HOME=%USERPROFILE%\.config\watch-control
if not exist "%WC_HOME%" mkdir "%WC_HOME%"

if "%~1"=="setup" goto setup
if "%~1"=="picker" goto picker
goto server

:setup
if exist "%WC_HOME%\pairing.key" (
  echo [+] 配对密钥已存在: %WC_HOME%\pairing.key
) else (
  python -c "import secrets; print(secrets.token_hex(32))" > "%WC_HOME%\pairing.key"
  echo [+] 已生成配对密钥
)
echo     内容: 
type "%WC_HOME%\pairing.key"
echo.
echo 接下来设置手表地址（可选，手表访问后会自动学习）:
echo    set WATCH_ADDR=192.168.1.50:5555
goto end

:server
if "%PAIRING_KEY%"=="" (
  if exist "%WC_HOME%\pairing.key" (
    set /p PAIRING_KEY=<"%WC_HOME%\pairing.key"
  )
)
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=8787
echo [*] 启动中转服务
python server\app.py --host %HOST% --port %PORT%
goto end

:picker
if "%BILIAUTO_KEY%"=="" (
  if exist "%WC_HOME%\pairing.key" (
    set /p BILIAUTO_KEY=<"%WC_HOME%\pairing.key"
  )
)
if "%BILIAUTO_SERVER%"=="" set BILIAUTO_SERVER=http://127.0.0.1:8787
echo [*] 启动点选工具
python tap-tool\serve.py
goto end

:end
endlocal
