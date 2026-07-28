@echo off
REM 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
REM 開發模式：兩個視窗（前端 Vite HMR + 後端 uvicorn），需要 Node.js
REM 一般使用者∕GitHub 下載後執行，請改用 start.bat（單一視窗生產模式）
powershell -ExecutionPolicy Bypass -File "%~dp0dev.ps1"
pause
