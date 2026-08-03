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
function Get-PythonSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Prefix = @()
    )
    # py.exe 找不到指定版本時會寫入 stderr（"No suitable Python runtime found"）。
    # 在 $ErrorActionPreference = "Stop" 下，即使用 2>$null 導向，PowerShell 5.1
    # 仍會先把該行 stderr 包成終止例外(NativeCommandError)才套用重導向，導致腳本中止。
    # 必須用 try/catch 吞掉，才能繼續嘗試下一個版本。
    try {
        $arguments = @()
        if ($Prefix.Count -gt 0) { $arguments += $Prefix }
        $arguments += @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        $verOut = & $Exe @arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        if ($verOut -match "^3\.(9|10|11|12)$") { return [string]$verOut }
        return $null
    } catch {
        return $null
    }
}

function Find-CompatiblePython {
    $candidates = New-Object System.Collections.Generic.List[object]
    foreach ($ver in @("3.12", "3.11", "3.10", "3.9")) {
        $candidates.Add([pscustomobject]@{ Exe = "py"; Prefix = @("-$ver-64") })
    }
    foreach ($cmd in @("python3.12", "python3.11", "python3.10", "python3.9", "python")) {
        $candidates.Add([pscustomobject]@{ Exe = $cmd; Prefix = @() })
    }
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        $version = Get-PythonSignature -Exe $candidate.Exe -Prefix $candidate.Prefix
        if (-not $version) { continue }
        return [pscustomobject]@{ Exe = $candidate.Exe; Prefix = $candidate.Prefix; Version = $version }
    }
    return $null
}

if (-not (Test-Path $py)) {
    Write-Host "[1/3] 尚未建立虛擬環境,尋找相容的 Python（3.9~3.12,64 位元）..." -ForegroundColor Yellow
    $pythonInfo = Find-CompatiblePython
    if ($null -eq $pythonInfo) {
        Write-Host "       找不到相容版本,嘗試以 WinGet 安裝 Python 3.12（僅新增,不影響現有版本）..." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            try {
                winget install --id Python.Python.3.12 --exact --source winget --scope user `
                    --architecture x64 --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
            } catch { }
            $pythonInfo = Find-CompatiblePython
        }
        if ($null -eq $pythonInfo) {
            Write-Host "【錯誤】找不到相容的 64 位元 Python,且無法自動安裝。" -ForegroundColor Red
            Write-Host "        請至 https://www.python.org/downloads/ 手動安裝 Python 3.10（建議）,或洽 IT 協助。" -ForegroundColor Red
            Read-Host "        按 Enter 結束"
            exit 1
        }
    }
    $label = if ($pythonInfo.Prefix.Count -gt 0) { "$($pythonInfo.Exe) $($pythonInfo.Prefix -join ' ')" } else { $pythonInfo.Exe }
    Write-Host "       使用 $label 建立虛擬環境..." -ForegroundColor Yellow
    $venvArgs = @()
    if ($pythonInfo.Prefix.Count -gt 0) { $venvArgs += $pythonInfo.Prefix }
    $venvArgs += @("-m", "venv", $venv)
    & $pythonInfo.Exe @venvArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) {
        Write-Host "【錯誤】建立虛擬環境失敗。" -ForegroundColor Red
        Read-Host "        按 Enter 結束"
        exit 1
    }
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

# --- 4. 啟動:服務以子程序執行,主程序輪詢就緒後才開啟瀏覽器 ---
Write-Host "[3/3] 啟動服務 http://127.0.0.1:$PORT ..." -ForegroundColor Yellow
Write-Host "      所有資料處理皆在本機進行,不會上傳雲端。關閉此視窗即可結束程式。" -ForegroundColor DarkGray
Write-Host ""

# ---------------------------------------------------------------------------
# 為什麼不用 Start-Job 開瀏覽器（實際事故,勿改回去,詳見 ansys-gs-hub/start.ps1）
#
# 舊版用 Start-Job 開一個背景工作輪詢連接埠、就緒後開啟瀏覽器。Start-Job 會
# 另外啟動一個 PowerShell 子程序執行序列化的 script block,這正是防毒軟體的
# 行為偵測特徵,實測會被判定為可疑行為攔截,導致瀏覽器完全沒開、使用者連
# 錯誤訊息都看不到。
#
# 現在改成:uvicorn 以子程序執行（啟動的是 python.exe,不是 PowerShell）,
# 主程序自己輪詢連接埠、就緒後直接開瀏覽器,開啟失敗時把網址印出來。
# ---------------------------------------------------------------------------

$appUrl = "http://127.0.0.1:$PORT"
$server = $null
try {
    $server = Start-Process -FilePath $py `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$PORT", "--app-dir", $backend) `
        -NoNewWindow -PassThru

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($server.HasExited) { break }
        Start-Sleep -Milliseconds 500
        $ok = Test-NetConnection -ComputerName 127.0.0.1 -Port $PORT -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($ok) { $ready = $true; break }
    }

    if ($ready) {
        $opened = $false
        try {
            Start-Process $appUrl
            $opened = $true
        } catch { }
        Write-Host ""
        if ($opened) {
            Write-Host "服務已就緒,已開啟瀏覽器:$appUrl" -ForegroundColor Green
        } else {
            Write-Host "服務已就緒,但無法自動開啟瀏覽器。請自行在瀏覽器輸入下列網址:" -ForegroundColor Red
            Write-Host "    $appUrl" -ForegroundColor Cyan
        }
    } elseif (-not $server.HasExited) {
        Write-Host ""
        Write-Host "服務啟動逾時,仍未回應。請自行在瀏覽器輸入下列網址確認:" -ForegroundColor Red
        Write-Host "    $appUrl" -ForegroundColor Cyan
    }
    Write-Host ""

    if (-not $server.HasExited) {
        Wait-Process -Id $server.Id
    }
} finally {
    if ($null -ne $server) {
        try {
            if (-not $server.HasExited) {
                & taskkill /PID $server.Id /T /F | Out-Null
                Start-Sleep -Milliseconds 500
            }
        } catch { }
        try {
            if (-not $server.HasExited) { $server.Kill() }
        } catch { }
    }
    Write-Host ""
    $leftover = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue
    if ($leftover) {
        Write-Host "服務已結束,但連接埠 $PORT 仍被佔用（PID $($leftover[0].OwningProcess)）。" -ForegroundColor Red
    } else {
        Write-Host "服務已結束,連接埠 $PORT 已釋放。" -ForegroundColor Green
    }
}
