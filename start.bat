@echo off
REM Windows: двойной клик → Git Bash с окружением autoreels + меню.
REM После выхода из меню интерактивный shell остаётся с командами ar (rcfile + -i).
cd /d "%~dp0"
where bash >nul 2>nul || (echo Git Bash не найден - установите Git for Windows & pause & exit /b 1)
bash --rcfile ./start.sh -i
