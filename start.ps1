# =============================================================================
# 正式發布啟動腳本:單一視窗、單一埠（127.0.0.1:8010）
# 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供。
#
# 這是 GitHub 發布版的啟動方式:一般使用者只需要安裝 Python,不需要安裝
# Node.js（前端已預先建置為 frontend\dist,隨版控一起下載）。
# 若你是本專案開發者、需要即時預覽前端修改（Vite HMR）,請改用 dev.ps1。
#
# ★ 此檔須為「UTF-8 with BOM」,否則 Windows PowerShell 5.1 會用 Big5
#   解碼中文而噴出 parser 錯誤。
#
# 前置需求:Python 3.9~3.12（64 位元）。找不到相容版本時會嘗試以 WinGet
#           安裝 Python 3.12（僅新增,不會移除或降版你既有的 Python）。
# 首次啟動需要網路連線以下載後端套件；之後可離線執行。
# 所有資料處理皆在本機進行,不會上傳雲端。關閉此視窗即可結束程式。
# =============================================================================

$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding  = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$distIndex = Join-Path $root "frontend\dist\index.html"
$venv    = Join-Path $backend ".venv"
$py      = Join-Path $venv "Scripts\python.exe"
$req     = Join-Path $backend "requirements.lock.txt"
$PORT    = 8010

Write-Host "==== Metasurface Toolkit Web 啟動中 ====" -ForegroundColor Cyan

# --- 0. 檢查前端建置成品是否存在 ---
if (-not (Test-Path $distIndex)) {
    Write-Host "【錯誤】找不到 frontend\dist\index.html。" -ForegroundColor Red
    Write-Host "        正式發布版應已包含建置好的前端。請確認下載的是完整的" -ForegroundColor Red
    Write-Host "        Source ZIP 或 Release ZIP,而非手動整理後遺漏了 dist 資料夾。" -ForegroundColor Red
    Read-Host "        按 Enter 結束"
    exit 1
}

# --- 1. 尋找相容的 64 位元 Python（3.9~3.12），必要時建立虛擬環境 ---
function Find-CompatiblePython {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($ver in @("3.12", "3.11", "3.10", "3.9")) {
            & py "-$ver-64" -c "exit()" 2>$null
            if ($LASTEXITCODE -eq 0) { $candidates += "py -$ver-64" }
        }
    }
    foreach ($cmd in @("python3.12", "python3.11", "python3.10", "python3.9", "python")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $verOut = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            if ($verOut -match "^3\.(9|10|11|12)$") { $candidates += $cmd }
        }
    }
    return $candidates
}

if (-not (Test-Path $py)) {
    Write-Host "[1/3] 尚未建立虛擬環境,尋找相容的 Python（3.9~3.12,64 位元）..." -ForegroundColor Yellow
    $found = Find-CompatiblePython
    if ($found.Count -eq 0) {
        Write-Host "       找不到相容版本,嘗試以 WinGet 安裝 Python 3.12（僅新增,不影響現有版本）..." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            winget install --id Python.Python.3.12 --exact --source winget --scope user `
                --architecture x64 --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
            $found = Find-CompatiblePython
        }
        if ($found.Count -eq 0) {
            Write-Host "【錯誤】找不到相容的 64 位元 Python,且無法自動安裝。" -ForegroundColor Red
            Write-Host "        請至 https://www.python.org/downloads/ 手動安裝 Python 3.10（建議）,或洽 IT 協助。" -ForegroundColor Red
            Read-Host "        按 Enter 結束"
            exit 1
        }
    }
    $pythonCmd = $found[0]
    Write-Host "       使用 $pythonCmd 建立虛擬環境..." -ForegroundColor Yellow
    Invoke-Expression "$pythonCmd -m venv `"$venv`""
} else {
    Write-Host "[1/3] 虛擬環境已存在,略過建立。" -ForegroundColor Green
}

# --- 2. 安裝後端套件（優先 uv,沒有則自動裝進 venv）---
Write-Host "[2/3] 安裝後端套件..." -ForegroundColor Yellow
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if ($uv) {
    & $uv pip install --python $py -r $req
} else {
    & $py -m pip install --upgrade pip
    & $py -m pip install uv
    $uvLocal = Join-Path $venv "Scripts\uv.exe"
    if (Test-Path $uvLocal) {
        & $uvLocal pip install --python $py -r $req
    } else {
        Write-Host "       uv 不可用,回退純 pip..." -ForegroundColor Yellow
        & $py -m pip install -r $req
    }
}

# --- 3. 埠檢查:被佔用就提示並停止,不自動關閉未知程序 ---
$existing = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $procId = $existing[0].OwningProcess
    $name0  = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
    Write-Host "【警告】埠 $PORT 已被 PID $procId ($name0) 佔用！" -ForegroundColor Red
    Write-Host "        請關閉該程式,或改用其他埠後再執行。" -ForegroundColor Red
    Read-Host "        按 Enter 結束"
    exit 1
}

# --- 4. 啟動（前景執行；關閉此視窗即停止服務）---
Write-Host "[3/3] 啟動服務 http://127.0.0.1:$PORT ..." -ForegroundColor Yellow
Write-Host "      所有資料處理皆在本機進行,不會上傳雲端。關閉此視窗即可結束程式。" -ForegroundColor DarkGray

# 背景輪詢服務就緒狀態,就緒後才開啟瀏覽器（最多等 30 秒）
Start-Job -ScriptBlock {
    param($port)
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($ok) { Start-Process "http://127.0.0.1:$port"; break }
    }
} -ArgumentList $PORT | Out-Null

& $py -m uvicorn app.main:app --host 127.0.0.1 --port $PORT --app-dir $backend
