# =============================================================================
# 開發模式啟動腳本:兩個視窗(前端 Vite + 後端 uvicorn),支援前端即時預覽(HMR)
# 此範本由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供。
#
# 這是本專案「開發者」在修改前端程式碼時使用的啟動方式。
# 一般使用者／GitHub 下載後執行,請改用專案根目錄的 start.ps1(單一視窗生產模式,
# 不需要安裝 Node.js)。
#
# ★ 複製後請確認此檔存為「UTF-8 with BOM」,否則 Windows PowerShell 5.1
#   會用 Big5 解碼中文而噴出 parser 錯誤。
#
# 目錄假設:<專案>/dev.ps1、<專案>/backend、<專案>/frontend
# 前置需求:Python 3.9~3.12、Node.js 18+;uv 可有可無(沒有會自動裝進 venv)。
# =============================================================================

$ErrorActionPreference = "Stop"
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$venv     = Join-Path $backend ".venv"
$py       = Join-Path $venv "Scripts\python.exe"
$req      = Join-Path $backend "requirements.lock.txt"

# 本專案專屬固定埠(與 vite.config.ts 一致)
$BACKEND_PORT  = 8010
$FRONTEND_PORT = 5180

Write-Host "==== 啟動中 ====" -ForegroundColor Cyan

# --- 1~2. 建立虛擬環境並安裝套件(優先 uv,速度遠快於 pip)---
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if ($uv) {
    Write-Host "[1/4] 偵測到全域 uv,建立虛擬環境..." -ForegroundColor Yellow
    if (-not (Test-Path $py)) { & $uv venv $venv }
    Write-Host "[2/4] 以 uv 安裝後端套件..." -ForegroundColor Yellow
    & $uv pip install --python $py -r $req
} else {
    Write-Host "[1/4] 無全域 uv,改用 python -m venv 建立虛擬環境..." -ForegroundColor Yellow
    if (-not (Test-Path $py)) { python -m venv $venv }
    Write-Host "[2/4] 於虛擬環境安裝 uv,再以 uv 安裝後端套件..." -ForegroundColor Yellow
    & $py -m pip install --upgrade pip
    & $py -m pip install uv
    $uvLocal = Join-Path $venv "Scripts\uv.exe"
    if (Test-Path $uvLocal) {
        & $uvLocal pip install --python $py -r $req
    } else {
        Write-Host "    uv 不可用,回退純 pip..." -ForegroundColor Yellow
        & $py -m pip install -r $req
    }
}

# --- 3. 前端套件 ---
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[3/4] 安裝前端套件 (npm install)..." -ForegroundColor Yellow
    Push-Location $frontend; npm install; Pop-Location
} else {
    Write-Host "[3/4] 已安裝前端套件,略過。" -ForegroundColor Green
}

# --- 埠檢查:被佔用就提示並停止,避免開到別的網站 ---
function Test-PortInUse($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
foreach ($pair in @(@($FRONTEND_PORT, "前端"), @($BACKEND_PORT, "後端"))) {
    if (Test-PortInUse $pair[0]) {
        $pid0  = (Get-NetTCPConnection -LocalPort $pair[0] -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
        $name0 = (Get-Process -Id $pid0 -ErrorAction SilentlyContinue).ProcessName
        Write-Host "【警告】$($pair[1])埠 $($pair[0]) 已被 PID $pid0 ($name0) 佔用!" -ForegroundColor Red
        Write-Host "        請關閉該程式,或改用其他埠後再執行。" -ForegroundColor Red
        Read-Host "        按 Enter 結束"
        exit 1
    }
}

# --- 4. 啟動後端(新視窗)與前端 ---
Write-Host "[4/4] 啟動後端 uvicorn (127.0.0.1:$BACKEND_PORT)..." -ForegroundColor Yellow
Start-Process powershell -WorkingDirectory $backend -ArgumentList @(
    "-NoExit", "-Command",
    "& '$py' -m uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT"
)

Start-Sleep -Seconds 2
Write-Host "啟動前端 Vite (http://localhost:$FRONTEND_PORT)..." -ForegroundColor Yellow
Start-Process "http://localhost:$FRONTEND_PORT"
Push-Location $frontend; npm run dev; Pop-Location
