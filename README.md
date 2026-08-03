# Metasurface Toolkit Web

超穎表面（Metasurface）反射陣列設計工具的 Web 版本：依饋源位置與波束方向計算每個陣列單元所需的補償相位，透過「相位 → 尺寸（Lx）」對照表內插出實際單元尺寸，再經由 PyAEDT 直接在 Ansys HFSS 中產生完整陣列模型、建立模擬環境並讀取結果。

> 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

## 原作者歸屬

本專案的設計流程（相位補償公式、Reflectarray 建模步驟）改寫自 Ansys 官方 **MetaSurfaceToolkit**
簡報，原作者為：

> © 2020 ANSYS, Inc. — Sharon Varghese、Nijas Kunju、Mahesh Babu

原簡報為 Ansys, Inc. 版權所有之官方教材，未包含於本專案，請透過 Ansys 官方管道取得。

原版為 AEDT 內建的 IronPython 桌面工具。本專案將其設計流程重新實作為 React + FastAPI 的網頁應用，
並擴充了 UnitCell 相位自動掃描、HFSS 全自動建模、模擬結果讀取（遠場方向圖、波束品質指標等）等原版沒有的功能。

## 功能

- **即時 2D 預覽**：參數改變即時重算陣列佈局（Canvas 平移／縮放）。
- **相位資料表上傳**：支援 `.csv` 與 `.xlsx`，欄位名稱含 `phase` 與 `Lx` 關鍵字即可（Lx 單位 µm）。
- **相位掃描自動化**：由上傳的 UnitCell 專案逐點縮放圖樣、求解、取 Floquet Port 反射相位，
  自動產生 phase–Lx 對照表並載入（可設定 Lx 範圍與點數，含進度與取消）。
- **專案參數自動偵測**：上傳專案檔時自動量測並帶入 Unit Cell Size 與 Frequency，帶入後鎖定避免誤觸。
- **HFSS 一鍵建模（全自動）**：上傳 UnitCell 專案檔（`.aedt`／`.aedtz`，**不需先在 AEDT 開啟**），
  工具自動從母本複製副本並分類物件：
  - 真空／空氣（輻射盒）→ 刪除
  - XY ≥ 95% cell 且實心 → 背景層（基板／接地），放大 N 倍成整板
  - XY ≥ 95% cell 但面積 < 邊界盒 90% → 格柵層，逐格鋪排不縮放
  - 小於 cell → 單元圖樣，逐格依 Lx「複製 → 等比縮放 → 定位」

  完成後重新指定金屬 Perfect E、建立空氣盒（λ/4 淨空）＋Radiation 邊界＋垂直入射平面波，
  存成 `<名稱>_array.aedt` 可直接 Validate／求解。
- **模擬結果讀取**：遠場方向圖（二維切面／三維立體）、表面電場分佈、波束品質指標
  （峰值 RCS、3dB 波束寬、旁瓣電平、口徑與理論指向性上限），可分項勾選、漸進顯示。
- **進度與防呆**：建模顯示「第幾格／共幾格」並可取消；參數與專案不符、相位表比例異常時主動提示；
  單一 gRPC 指令失敗自動重試 3 次後跳過該格，不中止整批作業。

詳細操作步驟與畫面截圖見 [docs/操作說明.md](docs/操作說明.md)。

## 系統需求

| 項目 | 用途 | 安裝方式 |
|---|---|---|
| Windows 10/11（64 位元） | 執行環境 | — |
| Python 3.9–3.12（64 位元） | 後端 FastAPI 服務 | [python.org](https://www.python.org/downloads/)；找不到相容版本時 `start.ps1` 會嘗試以 WinGet 自動安裝 Python 3.12（僅新增，不會移除或降版你既有的 Python） |
| Ansys AEDT（HFSS） | 產生陣列模型、相位掃描、專案參數偵測、讀取模擬結果 | 需自備商業授權；實測版本 2026 R1 |

一般使用者**不需要安裝 Node.js**——前端已預先建置完成並隨版控一起下載。Node.js 僅在你想修改前端原始碼、
使用 `dev.ps1` 開發模式（Vite 即時預覽）時才需要，見下方〈開發模式〉。

後端 Python 套件（`backend/requirements.lock.txt` 已鎖定版本，首次啟動自動安裝，需要網路連線）：
fastapi、uvicorn、pydantic、pandas、numpy、openpyxl、python-multipart、pyaedt、pythonnet。

## 下載與啟動

### 方式一：GitHub 網頁下載（不需要 Git）

1. 於本頁點選綠色 **Code → Download ZIP**。
2. 解壓縮到任意資料夾。
3. 雙擊 **`start.bat`**。

### 方式二：git clone

```powershell
git clone https://github.com/<你的帳號>/metasurface-toolkit-web.git
cd metasurface-toolkit-web
.\start.bat
```

`start.bat` 會依序：偵測相容的 Python → 建立虛擬環境（`backend\.venv`）→ 安裝後端套件 →
啟動單一伺服器 `http://127.0.0.1:8010`，就緒後自動開啟瀏覽器。**全程只有一個視窗、一個網址**，
關閉該視窗即結束程式。所有資料處理皆在本機進行，不會上傳雲端。

首次啟動需要網路連線下載套件；之後可離線執行。若埠 8010 被佔用，腳本會顯示佔用的 PID／程序名稱並停止，
不會自動關閉不明程序。

### 開發模式（修改前端原始碼時使用）

```powershell
.\dev.ps1
```

會另外安裝 Node.js 相依套件、開啟前端 Vite 開發伺服器（`http://localhost:5180`，支援即時預覽）與後端
uvicorn 兩個視窗。此模式需要額外安裝 **Node.js 18+**。修改完成後執行 `cd frontend; npm run build`
重新產生 `frontend/dist`，`start.bat` 才會看到最新版本。

## 操作流程

**已有相位表時：**

1. 「選擇 Excel / CSV」上傳相位對照表，2D 預覽隨即顯示。
2. 「選擇 UnitCell 專案檔」上傳 `.aedt` 或 `.aedtz`（不需先在 AEDT 開啟），Unit Cell Size 與 Frequency 自動帶入並鎖定。
3. 設定陣列數量、饋源座標與波束方向，預覽即時更新。
4. 按「產生模型」，過程顯示進度，可隨時取消。
5. 在 AEDT 中 Validate 後求解；按「讀取模擬結果」查看遠場方向圖與波束品質指標；完成後按「釋放 AEDT」中斷連線。

**沒有相位表時：** 先做上述步驟 2，再用「③ 掃描產生相位表」設定 Lx 範圍與點數自動產生
（每點需完整求解一次），完成後自動載入，接續步驟 3。

> 建模期間請勿操作 AEDT（尤其是 Validate、對話框、復原），會使執行中的指令永久卡死而必須重來。

完整步驟圖解（含 5×5／30×30／100×100 陣列實測截圖）見 [docs/操作說明.md](docs/操作說明.md)。

## 已知的一組實測參數（Butterfly_element）

Frequency 10 GHz、Unit Cell Size 8 mm、Feed Z 40 mm、掃描 Lx 4000–7550 µm。
7 點掃描相位涵蓋 342°；曾實測至 100×100 陣列規模仍可正常建模與參數調整
（見〈docs/操作說明.md〉的大陣列截圖）。

## 設計公式

每個單元 (xᵢ, yᵢ) 的補償相位：

```
φᵢ = k₀ · ( dᵢ − sinθ₀ · ( xᵢ·cosφ₀ + yᵢ·sinφ₀ ) )    (mod 360°)
```

其中 dᵢ 為饋源到單元的距離，(θ₀, φ₀) 為目標波束方向，k₀ = 360°/λ。目前僅實作並驗證過
Reflectarray（反射陣列）；Transmitarray（穿透陣列）因饋源擺放與單元設計不同、尚未實作與驗證，暫未提供。

## 專案結構

```
start.bat / start.ps1      正式發布啟動器：單一視窗、單一埠，不需要 Node.js
dev.bat / dev.ps1          開發模式啟動器：雙視窗（Vite HMR + uvicorn），需要 Node.js
backend/app/main.py        FastAPI：相位計算、CSV 內插、PyAEDT 建模、掃描與結果讀取
backend/app/static/        執行期檔案（母本、陣列成品、掃描結果，未進版控）
frontend/src/App.tsx       參數面板與預覽資料組裝
frontend/src/components/   Preview2D（Canvas 2D 預覽）、ResultsView（模擬結果檢視）
frontend/dist/             前端建置成品（已隨版控提供，供 start.bat 直接託管）
docs/操作說明.md            完整操作說明與截圖
Butterfly_element.aedtz    蝴蝶結單元範例專案（10 GHz、cell 8 mm）
Butterfly_Phase_dim_TEST.csv  蝴蝶結示範用相位表（合成資料，非模擬結果）
Phase_dim_PG_45.csv        內建相位對照表（140 GHz、cell 1 mm 設計用）
```

執行期產生的檔案以專案名稱為前綴：`_master.aedt`（母本）、`_array.aedt`（陣列成品）、
`_sweep.aedt`（掃描暫存）、`_phase_sweep.csv`（掃描產出的相位表）。

## 授權

本專案程式碼以 [MIT License](LICENSE) 釋出。設計流程參考 Ansys 官方 MetaSurfaceToolkit 簡報
（原作者：Sharon Varghese、Nijas Kunju、Mahesh Babu，© 2020 ANSYS, Inc.），該簡報本身著作權
仍屬原作者與 Ansys, Inc. 所有，未隨本專案散布，亦不受本專案 MIT License 涵蓋。
