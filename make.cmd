@echo off
chcp 65001 >nul 2>&1
REM ============================================================================
REM  Шим для Windows: на большинстве машин make не установлен, а команды нужны
REM  те же. Это НЕ настоящий make, просто короткий диспетчер тех же действий,
REM  что описаны в Makefile. Держи оба файла в согласии.
REM
REM  Использование (PowerShell или cmd, из корня репозитория):
REM      .\make.cmd setup
REM      .\make.cmd seed
REM      .\make.cmd dev
REM      .\make.cmd check
REM
REM  ВАЖНО: файл обязан быть с переводами строк CRLF, иначе cmd.exe его не
REM  выполнит и молча зависнет. За этим следит .gitattributes.
REM ============================================================================
setlocal
set PYTHONUTF8=1
set ROOT=%~dp0
set VENV_PY=%ROOT%backend\.venv\Scripts\python.exe
set TARGET=%1
if "%TARGET%"=="" set TARGET=help

if /I "%TARGET%"=="help"  goto help
if /I "%TARGET%"=="setup" goto setup
if /I "%TARGET%"=="seed"  goto seed
if /I "%TARGET%"=="dev"   goto dev
if /I "%TARGET%"=="check" goto check
if /I "%TARGET%"=="build" goto build
if /I "%TARGET%"=="clean" goto clean
echo Неизвестная команда: %TARGET%

:help
echo   .\make.cmd setup  - поставить зависимости
echo   .\make.cmd seed   - залить демо-данные, 400 записей
echo   .\make.cmd dev    - backend :8000 и frontend :5173, в двух окнах
echo   .\make.cmd check  - тесты бэкенда и проверка типов фронта
echo   .\make.cmd build  - сборка фронта
echo   .\make.cmd clean  - удалить venv, node_modules, app.db
goto end

:setup
cd /d "%ROOT%backend"
python -m venv .venv
if errorlevel 1 goto fail
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto fail
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
cd /d "%ROOT%frontend"
call npm install
if errorlevel 1 goto fail
echo.
echo Готово. Скопируй .env.example в .env, вставь OPENAI_API_KEY, потом: .\make.cmd seed
goto end

:seed
cd /d "%ROOT%backend"
"%VENV_PY%" scripts\seed.py
goto end

:dev
echo backend  http://localhost:8000/docs
echo frontend http://localhost:5173
start "HackAlem backend" cmd /k "cd /d %ROOT%backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
start "HackAlem frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"
goto end

:check
cd /d "%ROOT%backend"
"%VENV_PY%" -m pytest
if errorlevel 1 goto fail
cd /d "%ROOT%frontend"
call npm run typecheck
if errorlevel 1 goto fail
echo check пройден
goto end

:build
cd /d "%ROOT%frontend"
call npm run build
goto end

:clean
if exist "%ROOT%backend\.venv" rmdir /s /q "%ROOT%backend\.venv"
if exist "%ROOT%backend\app.db" del /q "%ROOT%backend\app.db"
if exist "%ROOT%backend\.pytest_cache" rmdir /s /q "%ROOT%backend\.pytest_cache"
if exist "%ROOT%frontend\node_modules" rmdir /s /q "%ROOT%frontend\node_modules"
if exist "%ROOT%frontend\dist" rmdir /s /q "%ROOT%frontend\dist"
echo Убрано. Дальше: .\make.cmd setup
goto end

:fail
echo КОМАНДА ЗАВЕРШИЛАСЬ С ОШИБКОЙ
endlocal
exit /b 1

:end
endlocal
