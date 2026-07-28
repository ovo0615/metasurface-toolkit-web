@echo off
REM 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
REM 正式發布版啟動器：單一視窗、單一埠（127.0.0.1:8010），不需要安裝 Node.js
REM 開發者若需要前端即時預覽（Vite HMR），請改用 dev.bat
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
