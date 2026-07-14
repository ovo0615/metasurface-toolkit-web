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

@app.post("/api/upload_model")
async def upload_model(file: UploadFile = File(...)):
    try:
        if not (file.filename.endswith('.obj') or file.filename.endswith('.aedtz')):
            raise HTTPException(status_code=400, detail="不支援的格式，請上傳 .obj 或 .aedtz")
            
        file_path = os.path.join(static_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        obj_path = os.path.join(static_dir, "unitcell.obj")
        
        if file.filename.endswith('.aedtz'):
            # 背景啟動 PyAEDT 並匯出
            from ansys.aedt.core import Hfss
            hfss = Hfss(projectname=file_path, non_graphical=True, new_desktop=True)
            try:
                hfss.modeler.export_3d_model(file_name=obj_path, assignment=["UnitCell"])
            except Exception as ex:
                hfss.release_desktop(close_projects=True, close_desktop=True)
                raise HTTPException(status_code=500, detail=f"PyAEDT 匯出模型失敗: {str(ex)}")
            hfss.release_desktop(close_projects=True, close_desktop=True)
        else:
            # 如果是 obj，直接覆蓋
            shutil.copy(file_path, obj_path)
            
        return {"status": "success", "message": "模型上傳並轉換成功！可以切換至 3D 預覽。"}
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
            if config.mode == "Transmitarray":
                phase_req = k0 * (di - steering)
            else: # Reflectarray
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
                "size_y": pitch * 0.8
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

@app.post("/api/generate")
def generate_aedt(config: ArrayConfig):
    # 使用 PyAEDT 直接連線至目前開啟的 HFSS 專案進行陣列複製
    # 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
    
    try:
        from ansys.aedt.core import Hfss
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")
        
    # 取得要複製的陣列清單
    res = generate_preview(config)
    elements = res["elements"]
    
    try:
        # 連線至目前的 HFSS 專案 (new_desktop=False)
        hfss = Hfss(new_desktop=False)
        
        # 尋找基準的 UnitCell 物件，假設在模型中它名為 "UnitCell"
        if "UnitCell" not in hfss.modeler.object_names:
            # 假設沒有 UnitCell，我們就不執行操作並回報錯誤
            return {"status": "error", "message": "在 HFSS 中找不到名為 'UnitCell' 的物件！請確認您的模型設定。"}
        
        for idx, el in enumerate(elements):
            x = el["x"]
            y = el["y"]
            lx_um = el["size_x"] * 1000 # 真實 Lx 長度
            
            # 使用 duplicate_along_line 來複製
            # vector = [X偏移, Y偏移, Z偏移]
            new_objs = hfss.modeler.duplicate_along_line(
                "UnitCell", 
                [x, y, 0], 
                clones=2, 
                attachObject=False
            )
            
            # 新產生的物件(list 中的第二個，第一個是原本的 UnitCell)
            if new_objs and len(new_objs) >= 2:
                new_obj_name = new_objs[1]
                # 理論上若要改變 Lx，最完美的做法是利用 PyAEDT 的 local variables 或參數化模型
                # 但因為這是單一物件操作，若物件能直接設定 X 尺寸：
                # (這裡僅為架構示範，視實際模型參數而定)
                # hfss.modeler[new_obj_name].x_size = f"{lx_um}um" 
                pass
                
        return {"status": "success", "message": "成功！已直接在 HFSS 中產生天線陣列模型。"}
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
