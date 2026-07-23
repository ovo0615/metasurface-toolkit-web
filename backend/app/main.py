# 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import math
import pandas as pd
import numpy as np
import os
import shutil

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 建立並掛載靜態資料夾
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

class ArrayConfig(BaseModel):
    mode: str
    shape: str
    frequency: float
    unit_cell_size: float
    num_elements: int
    feed_x: float
    feed_y: float
    feed_z: float
    beam_theta: float
    beam_phi: float

# 記錄目前上傳的 UnitCell 專案檔路徑（寫入檔案，後端重啟後仍可用）
_project_marker = os.path.join(static_dir, "current_project.txt")

def _get_current_project():
    if os.path.exists(_project_marker):
        p = open(_project_marker, encoding="utf-8").read().strip()
        if p and os.path.exists(p):
            return p
    return None

# 全域存放目前相位陣列
phase_data = np.array([-180, 180])
lx_data = np.array([20, 270])

def load_data(df: pd.DataFrame):
    global phase_data, lx_data
    # 尋找包含 phase 與 Lx 關鍵字的欄位
    phase_col = [col for col in df.columns if 'phase' in col.lower()]
    lx_col = [col for col in df.columns if 'lx' in col.lower()]
    
    if not phase_col or not lx_col:
        raise ValueError("檔案必須包含 'phase' 與 'Lx' 相關名稱的欄位！")
        
    df = df.sort_values(by=phase_col[0])
    phase_data = df[phase_col[0]].to_numpy()
    lx_data = df[lx_col[0]].to_numpy()

# 啟動時預設讀取資料夾內的 Phase_dim_PG_45.csv
default_csv = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Phase_dim_PG_45.csv"))
if os.path.exists(default_csv):
    try:
        load_data(pd.read_csv(default_csv))
    except Exception as e:
        print("預設 CSV 載入失敗:", e)

def get_lx_from_phase(phase_deg):
    # 將相位對應到 -180 ~ 180 的區間
    phase_deg = ((phase_deg + 180) % 360) - 180
    return float(np.interp(phase_deg, phase_data, lx_data))

@app.post("/api/upload")
async def upload_data(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        import io
        
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif file.filename.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="不支援的檔案格式，請上傳 .csv 或 .xlsx")
            
        load_data(df)
        return {"status": "success", "message": "資料表更新成功！預覽畫面已重新計算。"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"讀取失敗: {str(e)}")

@app.post("/api/upload_project")
def upload_project(file: UploadFile = File(...)):
    """上傳 UnitCell 專案檔（.aedt 或 .aedtz），存為 <名稱>_array.aedt 供產生陣列使用。
    不需要（也不應該）先在 AEDT 中開啟原始專案。"""
    try:
        lower = file.filename.lower()
        if not (lower.endswith('.aedt') or lower.endswith('.aedtz')):
            raise HTTPException(status_code=400, detail="不支援的格式，請上傳 .aedt 或 .aedtz 專案檔")

        stem = os.path.splitext(os.path.basename(file.filename))[0]
        raw_path = os.path.join(static_dir, file.filename)
        with open(raw_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 統一整理成 <stem>_array.aedt（改名可避免與使用者已開啟的同名專案衝突）
        target = os.path.join(static_dir, f"{stem}_array.aedt")
        if os.path.exists(target):
            os.remove(target)

        if lower.endswith('.aedtz'):
            # .aedtz 是 zip 壓縮檔，取出其中的 .aedt 並改名
            import zipfile
            with zipfile.ZipFile(raw_path) as zf:
                aedt_members = [m for m in zf.namelist() if m.lower().endswith('.aedt')]
                if not aedt_members:
                    raise HTTPException(status_code=400, detail="壓縮檔中找不到 .aedt 專案")
                with zf.open(aedt_members[0]) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            os.remove(raw_path)
        else:
            shutil.move(raw_path, target)

        with open(_project_marker, "w", encoding="utf-8") as f:
            f.write(target)

        return {"status": "success", "message": f"專案已上傳（{os.path.basename(target)}）。設定好參數後即可按「產生模型」。"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上傳專案失敗: {str(e)}")

@app.post("/api/preview")
def generate_preview(config: ArrayConfig):
    elements = []
    
    # 物理常數與波數計算
    c = 300 # 光速 mm/ns
    wavelength = c / config.frequency if config.frequency > 0 else 30
    k0 = 360 / wavelength # 波數 (deg/mm)
    
    theta_rad = math.radians(config.beam_theta)
    phi_rad = math.radians(config.beam_phi)
    
    N = config.num_elements
    pitch = config.unit_cell_size
    
    for r in range(N):
        for c_idx in range(N):
            x = (c_idx - N/2.0 + 0.5) * pitch
            y = (r - N/2.0 + 0.5) * pitch
            
            # 1. 計算空間相位延遲 (Spatial Delay)
            # Feed 位置到陣列單元的物理距離
            di = math.sqrt((x - config.feed_x)**2 + (y - config.feed_y)**2 + (0 - config.feed_z)**2)
            
            # 2. 計算波束轉向所需相位 (Beam Steering)
            steering = x * math.sin(theta_rad) * math.cos(phi_rad) + y * math.sin(theta_rad) * math.sin(phi_rad)
            
            # 3. 結合並求出陣列單元真正需要的補償相位
            # 標準相位補償公式：phi = k0 * (di - sin(theta)*(x*cos(phi0)+y*sin(phi0)))
            # Reflectarray 與 Transmitarray 的相位分佈公式相同，
            # 差別在於饋源擺放位置（反射式在正面、穿透式在背面）與單元設計本身。
            phase_req = k0 * (di - steering)

            phase = phase_req % 360
            
            # 透過數值內插法從 CSV 中取得真實尺寸 (Lx um)
            lx_um = get_lx_from_phase(phase)
            lx_mm = lx_um / 1000.0 # 換算為 mm 以便於前端繪圖比例相符
                
            elements.append({
                "id": f"{r}_{c_idx}",
                "x": x,
                "y": y,
                "phase": phase,
                "size_x": lx_mm,
                "size_y": lx_mm  # 原始 140GHz 蝴蝶結設計中 Ly = Lx，元件為等比縮放
            })
            
    return {
        "status": "success",
        "elements": elements,
        "bounds": {
            "minX": -N/2.0 * pitch,
            "maxX": N/2.0 * pitch,
            "minY": -N/2.0 * pitch,
            "maxY": N/2.0 * pitch
        }
    }

# 模型單位換算為 mm 的係數
_UNIT_TO_MM = {
    "nm": 1e-6, "um": 1e-3, "mm": 1.0, "cm": 10.0,
    "meter": 1000.0, "m": 1000.0, "mil": 0.0254, "in": 25.4, "inch": 25.4,
}

def _selection(name: str):
    return ["NAME:Selections", "Selections:=", name, "NewPartsModelFlag:=", "Model"]

def _set_nonmodel(hfss, name):
    """把物件設為非模型（相容新舊 pyaedt 屬性名）。"""
    try:
        obj = hfss.modeler[name]
        if hasattr(obj, "is_model"):
            obj.is_model = False  # pyaedt >= 1.x
        else:
            obj.model = False     # 舊版 pyaedt
    except Exception:
        pass

@app.post("/api/generate")
def generate_aedt(config: ArrayConfig):
    # 仿原版 MetaSurfaceToolkit 流程：開啟使用者上傳的 UnitCell 專案副本，
    # 自動分類物件後建立完整陣列，全程不需要手動輸入物件名稱。
    # 分類規則：
    #   - 材質為真空／空氣（輻射盒等）→ 設為非模型，不參與陣列
    #   - XY 尺寸接近 unit cell 尺寸（>= 95%）→ 背景層（基板／接地），放大 N 倍成整板
    #   - 其餘 → 單元圖樣，逐格「複製 → 依 Lx 縮放 → 移動」
    # 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供

    try:
        from ansys.aedt.core import Hfss
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")

    project_path = _get_current_project()
    if not project_path:
        return {"status": "error", "message": "請先按「選擇 UnitCell 專案檔」上傳 .aedt 或 .aedtz！"}

    # 取得要建立的陣列清單（含每個單元的相位與對應 Lx 尺寸）
    res = generate_preview(config)
    elements = res["elements"]
    N = config.num_elements

    try:
        # 開啟上傳的專案副本（若使用者已開著 AEDT 就直接在同一視窗開啟，否則自動啟動）
        hfss = Hfss(project=project_path, non_graphical=False, new_desktop=False)

        oeditor = hfss.modeler.oeditor
        model_units = hfss.modeler.model_units or "mm"
        unit_to_mm = _UNIT_TO_MM.get(model_units.lower(), 1.0)
        pitch_mu = config.unit_cell_size / unit_to_mm  # unit cell 尺寸換算成模型單位

        # ── 自動分類 ──
        pattern_names, background_names, excluded_names = [], [], []
        for name in hfss.modeler.object_names:
            try:
                mat = (hfss.modeler[name].material_name or "").lower()
            except Exception:
                mat = ""
            if mat in ("vacuum", "air"):
                excluded_names.append(name)
                continue
            bb = hfss.modeler[name].bounding_box
            dx, dy = bb[3] - bb[0], bb[4] - bb[1]
            if dx >= 0.95 * pitch_mu and dy >= 0.95 * pitch_mu:
                background_names.append(name)
            else:
                pattern_names.append(name)

        if not pattern_names:
            return {"status": "error",
                    "message": (f"找不到比 unit cell（{config.unit_cell_size}mm）小的圖樣物件可以縮放！"
                                f"請確認 Unit Cell Size 設定與專案尺寸一致。"
                                f"目前物件：{', '.join(hfss.modeler.object_names[:20])}")}

        # ── 背景層：以原點為中心放大 N 倍，成為整片大板 ──
        for name in background_names:
            bb = hfss.modeler[name].bounding_box
            cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
            oeditor.Scale(
                _selection(name),
                ["NAME:ScaleParameters",
                 "ScaleX:=", str(N), "ScaleY:=", str(N), "ScaleZ:=", "1"])
            # 縮放以全域原點為基準，中心會跑到 N*c，平移使其置中於原點
            if abs(cx) > 1e-9 or abs(cy) > 1e-9:
                oeditor.Move(
                    _selection(name),
                    ["NAME:TranslateParameters",
                     "TranslateVectorX:=", f"{-N * cx}{model_units}",
                     "TranslateVectorY:=", f"{-N * cy}{model_units}",
                     "TranslateVectorZ:=", "0mm"])

        # ── 單元圖樣：逐格複製、縮放、定位 ──
        bbs = [hfss.modeler[n].bounding_box for n in pattern_names]
        xmin = min(b[0] for b in bbs); ymin = min(b[1] for b in bbs)
        xmax = max(b[3] for b in bbs); ymax = max(b[4] for b in bbs)
        base_lx_mm = (xmax - xmin) * unit_to_mm
        base_cx = (xmin + xmax) / 2.0
        base_cy = (ymin + ymax) / 2.0
        if base_lx_mm <= 0:
            return {"status": "error", "message": f"圖樣物件 {pattern_names} 的 X 方向寬度為 0，無法縮放。"}

        sel_str = ",".join(pattern_names)
        created = 0
        for el in elements:
            scale_x = el["size_x"] / base_lx_mm  # 依 CSV 內插出的 Lx 對原始寬度的比例

            oeditor.Copy(["NAME:Selections", "Selections:=", sel_str])
            pasted = oeditor.Paste()
            if not pasted:
                continue
            new_sel = ",".join(pasted) if isinstance(pasted, (list, tuple)) else str(pasted)

            # 先把複製體中心移回原點（Scale 是以全域原點為基準）
            if abs(base_cx) > 1e-9 or abs(base_cy) > 1e-9:
                oeditor.Move(
                    _selection(new_sel),
                    ["NAME:TranslateParameters",
                     "TranslateVectorX:=", f"{-base_cx}{model_units}",
                     "TranslateVectorY:=", f"{-base_cy}{model_units}",
                     "TranslateVectorZ:=", "0mm"])

            # 依 Lx 等比縮放 X 與 Y（Z 維持不變，保留各層高度）
            oeditor.Scale(
                _selection(new_sel),
                ["NAME:ScaleParameters",
                 "ScaleX:=", str(scale_x), "ScaleY:=", str(scale_x), "ScaleZ:=", "1"])

            oeditor.Move(
                _selection(new_sel),
                ["NAME:TranslateParameters",
                 "TranslateVectorX:=", f"{el['x']}mm",
                 "TranslateVectorY:=", f"{el['y']}mm",
                 "TranslateVectorZ:=", "0mm"])
            created += 1

        # ── 收尾：刪除原始圖樣（此為專案副本），真空物件設非模型，存檔 ──
        try:
            hfss.modeler.delete(pattern_names)
        except Exception:
            for n in pattern_names:
                _set_nonmodel(hfss, n)
        for n in excluded_names:
            _set_nonmodel(hfss, n)
        try:
            hfss.save_project()
        except Exception:
            pass

        return {
            "status": "success",
            "message": (f"成功！已建立 {N}x{N} 陣列（{created} 個單元）於專案 {os.path.basename(project_path)}。"
                        f"圖樣：{', '.join(pattern_names)}｜"
                        f"背景層（已放大 {N} 倍）：{', '.join(background_names) or '無'}｜"
                        f"已忽略（真空／空氣）：{', '.join(excluded_names) or '無'}"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"與 HFSS 連線或建立模型時發生錯誤: {str(e)}")

@app.post("/api/release")
def release_aedt():
    try:
        from ansys.aedt.core import Hfss
        # 嘗試連線，但如果不成功代表本來就沒有開啟，直接 return 成功
        try:
            hfss = Hfss(new_desktop=False)
            hfss.release_desktop(close_projects=False, close_desktop=False)
            return {"status": "success", "message": "已成功釋放 AEDT 連線資源。"}
        except Exception as inner_e:
            return {"status": "success", "message": "目前沒有偵測到活動中的 AEDT 連線，無需釋放。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"釋放連線時發生錯誤: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8010)
