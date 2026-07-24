# Metasurface Toolkit Web

超穎表面（Metasurface）反射陣列／穿透陣列設計工具的 Web 版本，重現 Ansys MetaSurfaceToolkit 的核心流程：依饋源位置與波束方向計算每個陣列單元所需的補償相位，再透過「相位 → 尺寸（Lx）」對照表內插出實際單元尺寸，最後經由 PyAEDT 直接在 HFSS 中產生完整陣列模型。

> 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

## 功能

- **即時 2D 預覽**：參數改變即時重算陣列佈局（Canvas 平移／縮放）。
- **相位資料表上傳**：支援 `.csv` 與 `.xlsx`，欄位名稱含 `phase` 與 `Lx` 關鍵字即可（Lx 單位 µm）。
- **相位掃描自動化**：由上傳的 UnitCell 專案逐點縮放圖樣、求解、取 Floquet Port 反射相位，
  自動產生 phase–Lx 對照表並載入（可設定 Lx 範圍與點數，含進度與取消）。
- **專案參數自動偵測**：上傳專案檔時自動量測並帶入 Unit Cell Size 與 Frequency。
- **HFSS 一鍵建模（全自動）**：上傳 UnitCell 專案檔（`.aedt`／`.aedtz`，**不需先在 AEDT 開啟**），
  工具自動從母本複製副本並分類物件：
  - 真空／空氣（輻射盒）→ 刪除
  - XY ≥ 95% cell 且實心 → 背景層（基板／接地），放大 N 倍成整板
  - XY ≥ 95% cell 但面積 < 邊界盒 90% → 格柵層，逐格鋪排不縮放
  - 小於 cell → 單元圖樣，逐格依 Lx「複製 → 等比縮放 → 定位」

  完成後重新指定金屬 Perfect E、建立空氣盒（λ/4 淨空）＋Radiation 邊界＋垂直入射平面波，
  存成 `<名稱>_array.aedt` 可直接 Validate／求解。
- **進度與防呆**：建模顯示「第幾格／共幾格」並可取消；參數與專案不符、相位表比例異常時主動提示；
  單一 gRPC 指令失敗自動重試 3 次後跳過該格，不中止整批作業。

完整操作說明見 [操作說明 Artifact](https://claude.ai/code/artifact/e491c604-2c9b-45c6-8321-f788b9016a9b)。

## 系統需求（需預先安裝）

| 項目 | 用途 | 安裝方式 |
|---|---|---|
| Python 3.9–3.12 | 後端 FastAPI 服務 | [python.org](https://www.python.org/downloads/) |
| Node.js 18+ | 前端 Vite 開發伺服器 | [nodejs.org](https://nodejs.org/) |
| uv（建議） | 快速建立 venv 與安裝套件 | `pip install uv`（沒有也可，start.ps1 會自動處理） |
| Ansys AEDT（HFSS） | 產生陣列模型、相位掃描、專案參數偵測 | 公司授權安裝（實測 2026 R1、PyAEDT 1.2） |

後端 Python 套件（由 `backend/requirements.txt` 自動安裝）：fastapi、uvicorn、pydantic、pandas、numpy、openpyxl、python-multipart、pyaedt、pythonnet。

## 快速開始

```powershell
.\start.ps1
```

腳本會自動：建立 venv（優先 uv）→ 安裝前後端套件 → 檢查埠 → 啟動**兩個終端機視窗**
（後端 uvicorn `127.0.0.1:8010`、前端 Vite `http://localhost:5180`）。兩個視窗都需保持開啟；
後端視窗會印出 PyAEDT 的完整訊息，是排查問題的第一站。

## 操作流程

**已有相位表時：**

1. 「選擇 Excel / CSV」上傳相位對照表，2D 預覽隨即顯示。
2. 「選擇 UnitCell 專案檔」上傳 `.aedt` 或 `.aedtz`（不需先在 AEDT 開啟），Unit Cell Size 與 Frequency 自動帶入。
3. 設定陣列數量、饋源座標與波束方向，預覽即時更新。
4. 按「產生模型」，過程顯示進度，可隨時取消。
5. 在 AEDT 中 Validate 後求解；完成後按「釋放 AEDT」中斷連線。

**沒有相位表時：** 先做上述步驟 2，再用「③ 掃描產生相位表」設定 Lx 範圍與點數自動產生
（每點需完整求解一次），完成後自動載入，接續步驟 3。

> 建模期間請勿操作 AEDT，以免個別複製指令失敗（工具會重試並跳過，但仍以不操作為佳）。

## 已知的一組實測參數（Butterfly_element）

Frequency 10 GHz、Unit Cell Size 8 mm、Feed Z 40 mm、掃描 Lx 4000–7550 µm。
7 點掃描相位涵蓋 342°，據此建立的 5×5 陣列 Validation 通過、求解 13 秒完成。

## 設計公式

每個單元 (xᵢ, yᵢ) 的補償相位：

```
φᵢ = k₀ · ( dᵢ − sinθ₀ · ( xᵢ·cosφ₀ + yᵢ·sinφ₀ ) )    (mod 360°)
```

其中 dᵢ 為饋源到單元的距離，(θ₀, φ₀) 為目標波束方向，k₀ = 360°/λ。Reflectarray 與 Transmitarray 的相位分佈公式相同，差異在於饋源擺放側與單元設計本身。

## 專案結構

```
backend/app/main.py        FastAPI：相位計算、CSV 內插、PyAEDT 建模與掃描
backend/app/static/        執行期檔案（母本、陣列成品、掃描結果，未進版控）
frontend/src/App.tsx       參數面板與預覽資料組裝
frontend/src/components/   Preview2D（Canvas 2D 預覽）
start.ps1                  一鍵啟動（venv + 套件 + 前後端）
Butterfly_element.aedtz    蝴蝶結單元範例專案（10 GHz、cell 8 mm）
Butterfly_Phase_dim_TEST.csv  蝴蝶結示範用相位表（合成資料，非模擬結果）
Phase_dim_PG_45.csv        內建相位對照表（140 GHz、cell 1 mm 設計用）
MetaSurfaceToolkit.pdf     原版 Ansys 工具簡報
Metasurface_ToolkitV3/     原版桌面工具（參考用）
```

執行期產生的檔案以專案名稱為前綴：`_master.aedt`（母本）、`_array.aedt`（陣列成品）、
`_sweep.aedt`（掃描暫存）、`_phase_sweep.csv`（掃描產出的相位表）。
