# Metasurface Toolkit Web

超穎表面（Metasurface）反射陣列／穿透陣列設計工具的 Web 版本，重現 Ansys MetaSurfaceToolkit 的核心流程：依饋源位置與波束方向計算每個陣列單元所需的補償相位，再透過「相位 → 尺寸（Lx）」對照表內插出實際單元尺寸，最後經由 PyAEDT 直接在 HFSS 中產生完整陣列模型。

> 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

## 功能

- **即時 2D 預覽**：參數改變即時重算陣列佈局（Canvas 平移／縮放）。
- **相位資料表上傳**：支援 `.csv` 與 `.xlsx`，需含 `phase` 與 `Lx` 欄位（內建 `Phase_dim_PG_45.csv`，140 GHz 蝴蝶結單元、cell 1 mm、Lx 20–270 µm）。
- **HFSS 一鍵建模（全自動）**：上傳 UnitCell 專案檔（`.aedt`／`.aedtz`，**不需先在 AEDT 開啟**），
  工具會自動開啟專案副本並分類物件：
  - 真空／空氣（輻射盒）→ 設為非模型
  - XY 尺寸接近 cell 尺寸 → 背景層（基板／接地），放大 N 倍成整板
  - 其餘 → 單元圖樣，逐格依 Lx「複製 → 等比縮放 → 定位」
  完成後存成 `<名稱>_array.aedt`，直接顯示在 AEDT 中。

## 系統需求（需預先安裝）

| 項目 | 用途 | 安裝方式 |
|---|---|---|
| Python 3.9–3.12 | 後端 FastAPI 服務 | [python.org](https://www.python.org/downloads/) |
| Node.js 18+ | 前端 Vite 開發伺服器 | [nodejs.org](https://nodejs.org/) |
| uv（建議） | 快速建立 venv 與安裝套件 | `pip install uv`（沒有也可，start.ps1 會自動處理） |
| Ansys AEDT（HFSS） | 「產生模型」與 `.aedtz` 轉檔功能 | 需已安裝並開啟目標專案 |

後端 Python 套件（由 `backend/requirements.txt` 自動安裝）：fastapi、uvicorn、pydantic、pandas、numpy、openpyxl、python-multipart、pyaedt、pythonnet。

## 快速開始

```powershell
.\start.ps1
```

腳本會自動：建立 venv（優先 uv）→ 安裝前後端套件 → 檢查埠 → 啟動後端（127.0.0.1:8010）與前端（http://localhost:5180）。

## 操作流程

1. 「選擇 Excel / CSV」上傳相位對照表（含 `phase` 與 `Lx` 欄位，Lx 單位 µm），2D 預覽隨即顯示。
2. 設定頻率、cell 尺寸、陣列數量、饋源座標與波束方向，預覽即時更新。
3. 「選擇 UnitCell 專案檔」上傳 `.aedt` 或 `.aedtz`（不需先在 AEDT 開啟該專案）。
4. 按「產生模型」——工具自動開啟專案副本、分類物件並建出完整陣列
   （若 AEDT 已在執行會直接開在同一視窗，否則自動啟動）。
5. 完成後按「釋放 AEDT」中斷 PyAEDT 連線。

> 注意：Unit Cell Size 需與專案中單元的實際尺寸一致，物件自動分類以此判斷「背景層」與「圖樣」。

## 設計公式

每個單元 (xᵢ, yᵢ) 的補償相位：

```
φᵢ = k₀ · ( dᵢ − sinθ₀ · ( xᵢ·cosφ₀ + yᵢ·sinφ₀ ) )    (mod 360°)
```

其中 dᵢ 為饋源到單元的距離，(θ₀, φ₀) 為目標波束方向，k₀ = 360°/λ。Reflectarray 與 Transmitarray 的相位分佈公式相同，差異在於饋源擺放側與單元設計本身。

## 專案結構

```
backend/app/main.py        FastAPI：相位計算、CSV 內插、PyAEDT 建模
frontend/src/App.tsx       參數面板與預覽資料組裝
frontend/src/components/   Preview2D（Canvas 2D 預覽）
start.ps1                  一鍵啟動（venv + 套件 + 前後端）
Phase_dim_PG_45.csv        內建相位對照表（140 GHz）
UnitCell140GHz.aedt        參考 HFSS 單元專案（a=1mm、Lx=140µm、Ly=Lx）
MetaSurfaceToolkit.pdf     原版 Ansys 工具簡報
Metasurface_ToolkitV3/     原版桌面工具（參考用）
```
