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
    unitcell_name: str = "UnitCell"  # HFSS 中作為陣列基準的物件名稱

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

def _export_stl(hfss, names):
    """以 STL 格式匯出指定物件到 static/unitcell.stl（相容新舊 pyaedt API）。"""
    try:
        return hfss.modeler.export_3d_model(
            file_name="unitcell", file_path=static_dir,
            file_format=".stl", assignment_to_export=names)  # pyaedt >= 1.x
    except TypeError:
        return hfss.modeler.export_3d_model(
            file_name=os.path.join(static_dir, "unitcell.stl"), assignment=names)  # 舊版

@app.post("/api/upload_model")
def upload_model(file: UploadFile = File(...)):
    # 注意：此端點為同步函式（def 而非 async def），
    # FastAPI 會將其放入 threadpool 執行，避免 PyAEDT 的長時間作業卡住整個伺服器。
    try:
        allowed = ('.obj', '.stl', '.aedtz')
        if not file.filename.lower().endswith(allowed):
            raise HTTPException(status_code=400, detail="不支援的格式，請上傳 .obj、.stl 或 .aedtz")

        file_path = os.path.join(static_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 清除舊的預覽模型，避免前端載到過期檔案
        for old in ("unitcell.obj", "unitcell.stl"):
            old_p = os.path.join(static_dir, old)
            if os.path.exists(old_p) and os.path.abspath(old_p) != os.path.abspath(file_path):
                os.remove(old_p)

        if file.filename.lower().endswith('.aedtz'):
            # 背景啟動 PyAEDT（non-graphical）開啟壓縮專案並匯出 STL
            from ansys.aedt.core import Hfss
            hfss = Hfss(project=file_path, non_graphical=True, new_desktop=True)
            try:
                # 自動挑選要匯出的物件：排除真空／空氣（輻射盒等），保留金屬與介質
                solids = []
                for n in hfss.modeler.object_names:
                    try:
                        mat = (hfss.modeler[n].material_name or "").lower()
                        if mat not in ("vacuum", "air"):
                            solids.append(n)
                    except Exception:
                        solids.append(n)
                names = solids + list(hfss.modeler.sheet_names)
                if not names:
                    raise RuntimeError("專案中沒有可匯出的物件")
                _export_stl(hfss, names)
            except Exception as ex:
                hfss.release_desktop(close_projects=True, close_desktop=True)
                raise HTTPException(status_code=500, detail=f"PyAEDT 匯出模型失敗: {str(ex)}")
            hfss.release_desktop(close_projects=True, close_desktop=True)
        elif file.filename.lower().endswith('.stl'):
            shutil.copy(file_path, os.path.join(static_dir, "unitcell.stl"))
        else:
            shutil.copy(file_path, os.path.join(static_dir, "unitcell.obj"))

        return {"status": "success", "message": "模型上傳並轉換成功！可以切換至 3D 預覽。"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上傳模型失敗: {str(e)}")

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

@app.post("/api/generate")
def generate_aedt(config: ArrayConfig):
    # 使用 PyAEDT 直接連線至目前開啟的 HFSS 專案，
    # 以「複製 → 依 Lx 縮放 → 移動到定位」的方式產生完整陣列。
    # 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供

    try:
        from ansys.aedt.core import Hfss
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")

    # 取得要複製的陣列清單（含每個單元的相位與對應 Lx 尺寸）
    res = generate_preview(config)
    elements = res["elements"]

    try:
        # 連線至目前的 HFSS 專案 (new_desktop=False)
        hfss = Hfss(new_desktop=False)

        # 尋找基準物件（名稱可由前端設定，支援逗號分隔的多物件清單，預設 "UnitCell"）
        base_names = [n.strip() for n in (config.unitcell_name or "UnitCell").split(",") if n.strip()]
        missing = [n for n in base_names if n not in hfss.modeler.object_names]
        if missing:
            return {"status": "error", "message": f"在 HFSS 中找不到物件：{', '.join(missing)}！目前物件：{', '.join(hfss.modeler.object_names[:20])}"}

        oeditor = hfss.modeler.oeditor
        model_units = hfss.modeler.model_units or "mm"
        unit_to_mm = _UNIT_TO_MM.get(model_units.lower(), 1.0)

        # 讀取所有基準物件的聯合邊界盒，取得原始 Lx 寬度與中心點（模型單位）
        bbs = [hfss.modeler[n].bounding_box for n in base_names]  # [xmin, ymin, zmin, xmax, ymax, zmax]
        xmin = min(b[0] for b in bbs); ymin = min(b[1] for b in bbs)
        xmax = max(b[3] for b in bbs); ymax = max(b[4] for b in bbs)
        base_lx_mm = (xmax - xmin) * unit_to_mm
        base_cx = (xmin + xmax) / 2.0
        base_cy = (ymin + ymax) / 2.0

        if base_lx_mm <= 0:
            return {"status": "error", "message": f"{base_names} 的 X 方向寬度為 0，無法進行縮放。"}

        sel_str = ",".join(base_names)
        created = 0
        for el in elements:
            x_mm = el["x"]
            y_mm = el["y"]
            scale_x = el["size_x"] / base_lx_mm  # 依 CSV 內插出的 Lx 對原始寬度的比例

            # 1. 複製基準物件群（貼上後與原件重疊於原位）
            oeditor.Copy(["NAME:Selections", "Selections:=", sel_str])
            pasted = oeditor.Paste()
            if not pasted:
                continue
            new_sel = ",".join(pasted) if isinstance(pasted, (list, tuple)) else str(pasted)

            # 2. 先把複製體中心移回原點（Scale 是以全域原點為基準）
            if abs(base_cx) > 1e-9 or abs(base_cy) > 1e-9:
                oeditor.Move(
                    _selection(new_sel),
                    ["NAME:TranslateParameters",
                     "TranslateVectorX:=", f"{-base_cx}{model_units}",
                     "TranslateVectorY:=", f"{-base_cy}{model_units}",
                     "TranslateVectorZ:=", "0mm"])

            # 3. 依 Lx 等比縮放 X 與 Y（原始設計 Ly = Lx；Z 維持不變，保留各層高度）
            oeditor.Scale(
                _selection(new_sel),
                ["NAME:ScaleParameters",
                 "ScaleX:=", str(scale_x),
                 "ScaleY:=", str(scale_x),
                 "ScaleZ:=", "1"])

            # 4. 移動到陣列中的實際位置
            oeditor.Move(
                _selection(new_sel),
                ["NAME:TranslateParameters",
                 "TranslateVectorX:=", f"{x_mm}mm",
                 "TranslateVectorY:=", f"{y_mm}mm",
                 "TranslateVectorZ:=", "0mm"])
            created += 1

        # 5. 把原始基準物件設為非模型物件（保留當範本，避免與陣列重疊參與模擬）
        for n in base_names:
            try:
                obj = hfss.modeler[n]
                if hasattr(obj, "is_model"):
                    obj.is_model = False  # pyaedt >= 1.x
                else:
                    obj.model = False     # 舊版 pyaedt
            except Exception:
                pass

        return {
            "status": "success",
            "message": f"成功！已在 HFSS 中產生 {created} 個單元的陣列模型（原始 {sel_str} 已設為非模型物件）。",
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
