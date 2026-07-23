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
import threading
import re
import time

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

def _detect_project_params(master_path):
    """開啟母本量測 unit cell 尺寸（非真空物件最大 XY 尺寸）與 Setup 頻率，完成後關閉專案。
    若 AEDT 已在執行會直接沿用該視窗，只需數秒；否則會自動啟動 AEDT（較久）。"""
    from ansys.aedt.core import Hfss
    hfss = Hfss(project=master_path, non_graphical=False, new_desktop=False)
    cell_mm, freq_ghz = None, None
    try:
        model_units = hfss.modeler.model_units or "mm"
        u = _UNIT_TO_MM.get(model_units.lower(), 1.0)
        cell = 0.0
        for name in hfss.modeler.object_names:
            try:
                mat = (hfss.modeler[name].material_name or "").lower()
            except Exception:
                mat = ""
            if mat in ("vacuum", "air"):
                continue
            bb = hfss.modeler[name].bounding_box
            cell = max(cell, (bb[3] - bb[0]) * u, (bb[4] - bb[1]) * u)
        if cell > 0:
            cell_mm = round(cell, 4)
        try:
            fstr = str(hfss.setups[0].props.get("Frequency", "")).strip()
            m = re.match(r"([\d.]+)\s*(THz|GHz|MHz|kHz|Hz)", fstr, re.I)
            if m:
                mult = {"thz": 1000.0, "ghz": 1.0, "mhz": 1e-3, "khz": 1e-6, "hz": 1e-9}[m.group(2).lower()]
                freq_ghz = round(float(m.group(1)) * mult, 4)
        except Exception:
            pass
    finally:
        try:
            project_name = os.path.splitext(os.path.basename(master_path))[0]
            hfss.odesktop.CloseProject(project_name)
        except Exception:
            pass
    return cell_mm, freq_ghz

@app.post("/api/upload_project")
def upload_project(file: UploadFile = File(...)):
    """上傳 UnitCell 專案檔（.aedt 或 .aedtz），存為母本 <名稱>_master.aedt。
    每次建模自動從母本複製新副本，不需要（也不應該）先在 AEDT 中開啟原始專案。"""
    try:
        lower = file.filename.lower()
        if not (lower.endswith('.aedt') or lower.endswith('.aedtz')):
            raise HTTPException(status_code=400, detail="不支援的格式，請上傳 .aedt 或 .aedtz 專案檔")

        stem = os.path.splitext(os.path.basename(file.filename))[0]
        raw_path = os.path.join(static_dir, file.filename)
        with open(raw_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 存為母本 <stem>_master.aedt；每次建模會從母本複製新的 <stem>_array.aedt，
        # 因此重複建模不需重新上傳，也不會疊在上一次的結果上
        target = os.path.join(static_dir, f"{stem}_master.aedt")
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

        # 自動偵測專案參數（unit cell 尺寸、Setup 頻率），供前端直接帶入欄位
        detected = None
        try:
            cell_mm, freq_ghz = _detect_project_params(target)
            if cell_mm or freq_ghz:
                detected = {"unit_cell_size": cell_mm, "frequency": freq_ghz}
        except Exception:
            pass

        if detected:
            parts = []
            if detected.get("unit_cell_size"):
                parts.append(f"Unit Cell Size {detected['unit_cell_size']:g} mm")
            if detected.get("frequency"):
                parts.append(f"Frequency {detected['frequency']:g} GHz")
            hint = f"已自動帶入專案參數：{'、'.join(parts)}。"
        else:
            hint = "（無法自動偵測專案參數，請手動確認 Unit Cell Size 與 Frequency。）"

        return {"status": "success", "detected": detected,
                "message": f"專案已上傳（母本：{os.path.basename(target)}）。{hint}設定好其餘參數後即可按「產生模型」。"}
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

# ── 建模作業狀態（供進度查詢與取消）──
_gen = {"running": False, "cancel": False, "current": 0, "total": 0,
        "phase": "", "result": None, "error": None}
_gen_lock = threading.Lock()

def _run_generate(config: ArrayConfig):
    """實際的建模流程，在背景執行緒中執行，隨時更新 _gen 進度並回應取消要求。"""
    from ansys.aedt.core import Hfss, Desktop
    hfss = None
    master_path = _get_current_project()
    try:
        res = generate_preview(config)
        elements = res["elements"]
        N = config.num_elements
        _gen.update(total=len(elements), current=0, phase="開啟專案中")

        # 從母本複製全新工作副本（每次建模都是乾淨狀態）
        if master_path.endswith("_master.aedt"):
            project_path = master_path[: -len("_master.aedt")] + "_array.aedt"
        else:
            project_path = master_path  # 相容舊版上傳（無母本）
        project_name = os.path.splitext(os.path.basename(project_path))[0]

        # 若上一次的副本仍開啟於 AEDT，先關閉（不存檔）以釋放檔案鎖
        desktop = Desktop(new_desktop=False, non_graphical=False)
        if project_name in desktop.project_list:
            desktop.odesktop.CloseProject(project_name)

        if master_path.endswith("_master.aedt"):
            lock = project_path + ".lock"
            if os.path.exists(lock):
                os.remove(lock)
            shutil.copy(master_path, project_path)

        hfss = Hfss(project=project_path, non_graphical=False, new_desktop=False)

        def cancelled():
            if _gen["cancel"]:
                _gen["phase"] = "取消中，關閉未存檔專案"
                try:
                    hfss.odesktop.CloseProject(project_name)
                except Exception:
                    pass
                _gen["result"] = "已取消。半成品專案未存檔，磁碟上的副本仍是乾淨狀態，可直接重新產生。"
                return True
            return False

        if cancelled():
            return

        oeditor = hfss.modeler.oeditor
        model_units = hfss.modeler.model_units or "mm"
        unit_to_mm = _UNIT_TO_MM.get(model_units.lower(), 1.0)
        pitch_mu = config.unit_cell_size / unit_to_mm

        # ── 金屬物件清單（來自 Perfect E 邊界的物件 id）──
        metal_ids = set()
        for b in hfss.boundaries:
            if b.type == "Perfect E":
                for oid in (b.props.get("Objects", []) or []):
                    metal_ids.add(oid)
        metal_names = set()
        for n in hfss.modeler.object_names:
            try:
                if hfss.modeler[n].id in metal_ids:
                    metal_names.add(n)
            except Exception:
                pass

        # ── 自動分類 ──
        # pattern：比 cell 小的圖樣（逐格複製＋依 Lx 縮放）
        # tile：cell 大小但稀疏的金屬 sheet（如 cell 間格柵），逐格複製「不」縮放
        # background：cell 大小的實心層（基板／接地），放大 N 倍
        _gen["phase"] = "分類物件中"
        pattern_names, background_names, tile_names, excluded_names = [], [], [], []
        sheet_set = set(hfss.modeler.sheet_names)
        zmin_mu, zmax_mu = None, None
        bg_max_mu = 0.0
        for name in hfss.modeler.object_names:
            try:
                mat = (hfss.modeler[name].material_name or "").lower()
            except Exception:
                mat = ""
            if mat in ("vacuum", "air"):
                excluded_names.append(name)
                continue
            bb = hfss.modeler[name].bounding_box
            zmin_mu = bb[2] if zmin_mu is None else min(zmin_mu, bb[2])
            zmax_mu = bb[5] if zmax_mu is None else max(zmax_mu, bb[5])
            dx, dy = bb[3] - bb[0], bb[4] - bb[1]
            if dx >= 0.95 * pitch_mu and dy >= 0.95 * pitch_mu:
                bg_max_mu = max(bg_max_mu, dx, dy)
                # 稀疏度判別：sheet 面積遠小於邊界盒面積＝格柵類
                is_sparse_sheet = False
                if name in sheet_set:
                    try:
                        area = sum(f.area for f in hfss.modeler[name].faces)
                        if area < 0.9 * dx * dy:
                            is_sparse_sheet = True
                    except Exception:
                        pass
                if is_sparse_sheet:
                    tile_names.append(name)
                else:
                    background_names.append(name)
            else:
                pattern_names.append(name)

        # 防呆：背景層（基板／接地）的尺寸就是專案真正的 unit cell 尺寸，
        # 與使用者填的 Unit Cell Size 不符時直接擋下，避免建出錯誤模型
        if background_names:
            detected_mm = bg_max_mu * unit_to_mm
            if abs(detected_mm - config.unit_cell_size) / detected_mm > 0.10:
                freq_hint = ""
                try:
                    fstr = str(hfss.setups[0].props.get("Frequency", "")).strip()
                    if fstr:
                        freq_hint = f"，Frequency 建議對應專案 Setup 的 {fstr}"
                except Exception:
                    pass
                _gen["error"] = (
                    f"參數與專案不符：偵測到專案的 unit cell 尺寸約為 {detected_mm:.4g} mm，"
                    f"但 Unit Cell Size 填的是 {config.unit_cell_size} mm。"
                    f"請將 Unit Cell Size 改為 {detected_mm:.4g} mm{freq_hint}，再重新產生。")
                try:
                    hfss.odesktop.CloseProject(project_name)
                except Exception:
                    pass
                return

        if not pattern_names:
            _gen["error"] = (f"找不到比 unit cell（{config.unit_cell_size}mm）小的圖樣物件可以縮放！"
                             f"請確認 Unit Cell Size 設定與專案尺寸一致。"
                             f"目前物件：{', '.join(hfss.modeler.object_names[:20])}")
            return

        # ── 背景層：放大 N 倍成整板 ──
        _gen["phase"] = "放大背景層中"
        for name in background_names:
            if cancelled():
                return
            bb = hfss.modeler[name].bounding_box
            cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
            oeditor.Scale(
                _selection(name),
                ["NAME:ScaleParameters",
                 "ScaleX:=", str(N), "ScaleY:=", str(N), "ScaleZ:=", "1"])
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
            _gen["error"] = f"圖樣物件 {pattern_names} 的 X 方向寬度為 0，無法縮放。"
            return

        sel_str = ",".join(pattern_names)
        tile_str = ",".join(tile_names)
        pasted_metal = []  # 所有複製出的金屬 sheet，最後統一重新指定 PerfE
        created = 0
        skipped = 0  # 因 AEDT 暫時無回應而跳過的格數
        for idx, el in enumerate(elements):
            if cancelled():
                return
            _gen.update(phase="建立單元中", current=idx + 1)
            scale_x = el["size_x"] / base_lx_mm

            # 複製＋貼上：AEDT 忙碌或被操作時單一指令可能失敗，重試 3 次
            pasted = None
            for _attempt in range(3):
                try:
                    oeditor.Copy(["NAME:Selections", "Selections:=", sel_str])
                    pasted = oeditor.Paste()
                    if pasted:
                        break
                except Exception:
                    time.sleep(1.5)
            if not pasted:
                skipped += 1
                continue
            new_sel = ",".join(pasted) if isinstance(pasted, (list, tuple)) else str(pasted)

            try:
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
             # 記錄金屬複製體（AEDT 的複製貼上不會帶邊界，最後要重新指定 PerfE）
             plist = list(pasted) if isinstance(pasted, (list, tuple)) else [str(pasted)]
             for src, newn in zip(pattern_names, plist):
                if src in metal_names:
                    pasted_metal.append(newn)

             # 格柵層（cell 間格柵等）：逐格複製、不縮放、直接定位（重試 3 次）
             if tile_names:
                pasted_t = None
                for _attempt in range(3):
                    try:
                        oeditor.Copy(["NAME:Selections", "Selections:=", tile_str])
                        pasted_t = oeditor.Paste()
                        if pasted_t:
                            break
                    except Exception:
                        time.sleep(1.5)
                if pasted_t:
                    tsel = ",".join(pasted_t) if isinstance(pasted_t, (list, tuple)) else str(pasted_t)
                    oeditor.Move(
                        _selection(tsel),
                        ["NAME:TranslateParameters",
                         "TranslateVectorX:=", f"{el['x']}mm",
                         "TranslateVectorY:=", f"{el['y']}mm",
                         "TranslateVectorZ:=", "0mm"])
                    tlist = list(pasted_t) if isinstance(pasted_t, (list, tuple)) else [str(pasted_t)]
                    for src, newn in zip(tile_names, tlist):
                        if src in metal_names:
                            pasted_metal.append(newn)
             created += 1
            except Exception:
                skipped += 1
                continue

        # ── 收尾：刪除原始圖樣／格柵與真空物件（此為專案副本）──
        _gen["phase"] = "收尾與存檔中"
        try:
            hfss.modeler.delete(pattern_names + tile_names)
        except Exception:
            for n in pattern_names + tile_names:
                _set_nonmodel(hfss, n)

        # 重新指定 PerfE 給所有金屬複製體（複製貼上不會帶邊界）
        if pasted_metal:
            try:
                hfss.assign_perfecte_to_sheets(pasted_metal, name="PerfE_array")
            except Exception:
                pass
        if excluded_names:
            try:
                hfss.modeler.delete(excluded_names)
            except Exception:
                for n in excluded_names:
                    _set_nonmodel(hfss, n)

        # ── 模擬環境：空氣盒（λ/4 淨空）＋Radiation＋垂直入射平面波 ──
        env_msg = ""
        try:
            wavelength_mm = 300.0 / config.frequency if config.frequency > 0 else 30.0
            margin_mu = (wavelength_mm / 4.0) / unit_to_mm
            half_ap_mu = (N * config.unit_cell_size / 2.0) / unit_to_mm
            x0 = y0 = -half_ap_mu - margin_mu
            z0 = (zmin_mu if zmin_mu is not None else 0) - margin_mu
            z1 = (zmax_mu if zmax_mu is not None else 0) + margin_mu
            sx = sy = 2 * (half_ap_mu + margin_mu)
            try:
                box = hfss.modeler.create_box(
                    origin=[x0, y0, z0], sizes=[sx, sy, z1 - z0],
                    name="airbox_array", material="vacuum")
            except TypeError:
                box = hfss.modeler.create_box([x0, y0, z0], [sx, sy, z1 - z0],
                                              name="airbox_array", matname="vacuum")
            try:
                box.transparency = 0.95
            except Exception:
                pass
            hfss.assign_radiation_boundary_to_objects("airbox_array")
            if not hfss.excitation_names:
                hfss.plane_wave(
                    vector_format="Cartesian", origin=[0, 0, 0],
                    polarization=[1, 0, 0], propagation_vector=[0, 0, -1],
                    name="IncPWave1")
            env_msg = "已自動建立空氣盒＋Radiation 邊界＋平面波激勵，可直接 Validate／求解。"
        except Exception as env_e:
            env_msg = f"模擬環境自動建立失敗（{env_e}），請手動建立空氣盒與激勵。"

        try:
            hfss.save_project()
        except Exception:
            pass

        skip_note = ""
        if skipped:
            skip_note = (f"⚠ 有 {skipped} 格因 AEDT 暫時無回應被跳過（已自動重試仍失敗）。"
                         f"建議建模期間不要操作 AEDT，或重新產生一次。")
        _gen["result"] = (skip_note +
                          f"成功！已建立 {N}x{N} 陣列（{created} 個單元）於專案 {os.path.basename(project_path)}。"
                          f"圖樣：{', '.join(pattern_names)}｜"
                          f"背景層（已放大 {N} 倍）：{', '.join(background_names) or '無'}｜"
                        f"格柵層（逐格鋪排）：{', '.join(tile_names) or '無'}｜"
                        f"金屬複製體已重新指定 PerfE：{len(pasted_metal)} 件｜"
                          f"已刪除（真空／空氣）：{', '.join(excluded_names) or '無'}｜"
                          f"{env_msg}")
    except Exception as e:
        _gen["error"] = f"與 HFSS 連線或建立模型時發生錯誤: {str(e)}"
    finally:
        _gen.update(running=False, phase="完成")

@app.post("/api/generate")
def generate_aedt(config: ArrayConfig):
    # 啟動背景建模作業後立即回傳；進度由 /api/generate/status 查詢，
    # /api/generate/cancel 可隨時取消。
    # 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
    try:
        from ansys.aedt.core import Hfss  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")

    if not _get_current_project():
        return {"status": "error", "message": "請先按「選擇 UnitCell 專案檔」上傳 .aedt 或 .aedtz！"}

    with _gen_lock:
        if _gen["running"]:
            return {"status": "error", "message": "已有建模作業進行中，請等它完成或先取消。"}
        _gen.update(running=True, cancel=False, current=0, total=0,
                    phase="準備中", result=None, error=None)

    # 相位表與 cell 尺寸的合理性提示：最大 Lx 遠小於 cell 時，
    # 幾乎可以肯定用錯了資料表（例如把 140GHz 的表套在 10GHz 專案上）
    warning = None
    try:
        max_lx_mm = float(np.max(lx_data)) / 1000.0
        if max_lx_mm < 0.05 * config.unit_cell_size:
            warning = (f"⚠ 注意：目前相位表的最大 Lx 僅 {max_lx_mm:.3g} mm，"
                       f"不到 cell（{config.unit_cell_size:g} mm）的 5%，patch 會非常小。"
                       f"請確認相位表是否對應此 unit cell 設計（內建 Phase_dim_PG_45 為 140GHz／1mm 設計用）。")
    except Exception:
        pass

    threading.Thread(target=_run_generate, args=(config,), daemon=True).start()
    return {"status": "started", "message": "建模作業已開始。", "warning": warning}

@app.get("/api/generate/status")
def generate_status():
    return {k: _gen[k] for k in ("running", "current", "total", "phase", "result", "error")}

@app.post("/api/generate/cancel")
def generate_cancel():
    if _gen["running"]:
        _gen["cancel"] = True
        return {"status": "success", "message": "取消要求已送出，將在目前操作結束後停止。"}
    return {"status": "success", "message": "目前沒有進行中的建模作業。"}

# ── Unit cell 相位掃描（自動產生 phase–Lx 表）──
class SweepConfig(BaseModel):
    lx_min_um: float = 600.0
    lx_max_um: float = 2800.0
    points: int = 9

_sweep = {"running": False, "cancel": False, "current": 0, "total": 0,
          "phase": "", "result": None, "error": None, "csv_url": None}
_sweep_lock = threading.Lock()

def _run_sweep(cfg: SweepConfig):
    """逐點縮放圖樣並求解 unit cell，取 S11 反射相位，輸出 phase–Lx CSV。
    沿用原專案的週期邊界（Master/Slave＋Floquet Port）與 Setup。"""
    from ansys.aedt.core import Hfss, Desktop
    hfss = None
    master_path = _get_current_project()
    try:
        n_pts = max(2, int(cfg.points))
        _sweep.update(total=n_pts, current=0, phase="開啟專案中")

        # 從母本複製掃描專用副本
        if master_path.endswith("_master.aedt"):
            work = master_path[: -len("_master.aedt")] + "_sweep.aedt"
        else:
            work = os.path.splitext(master_path)[0] + "_sweep.aedt"
        proj_name = os.path.splitext(os.path.basename(work))[0]

        desktop = Desktop(new_desktop=False, non_graphical=False)
        if proj_name in desktop.project_list:
            desktop.odesktop.CloseProject(proj_name)
        lock = work + ".lock"
        if os.path.exists(lock):
            os.remove(lock)
        shutil.copy(master_path, work)

        hfss = Hfss(project=work, non_graphical=False, new_desktop=False)

        def cancelled():
            if _sweep["cancel"]:
                _sweep["phase"] = "取消中"
                try:
                    hfss.odesktop.CloseProject(proj_name)
                except Exception:
                    pass
                _sweep["result"] = "已取消掃描。"
                return True
            return False

        model_units = hfss.modeler.model_units or "mm"
        u = _UNIT_TO_MM.get(model_units.lower(), 1.0)

        # 自動分類：cell 尺寸＝非真空物件最大 XY 尺寸；比 cell 小的即為圖樣
        _sweep["phase"] = "分類物件中"
        cell_mu = 0.0
        infos = []
        for name in hfss.modeler.object_names:
            try:
                mat = (hfss.modeler[name].material_name or "").lower()
            except Exception:
                mat = ""
            if mat in ("vacuum", "air"):
                continue
            bb = hfss.modeler[name].bounding_box
            infos.append((name, bb))
            cell_mu = max(cell_mu, bb[3] - bb[0], bb[4] - bb[1])
        pattern_names = [n for n, bb in infos
                         if (bb[3] - bb[0]) < 0.95 * cell_mu and (bb[4] - bb[1]) < 0.95 * cell_mu]
        if not pattern_names:
            _sweep["error"] = "找不到可縮放的圖樣物件（比 unit cell 小的物件）。"
            return

        bbs = [bb for n, bb in infos if n in pattern_names]
        xmin = min(b[0] for b in bbs); ymin = min(b[1] for b in bbs)
        xmax = max(b[3] for b in bbs); ymax = max(b[4] for b in bbs)
        base_lx_um = (xmax - xmin) * u * 1000.0
        base_cx = (xmin + xmax) / 2.0
        base_cy = (ymin + ymax) / 2.0
        if base_lx_um <= 0:
            _sweep["error"] = "圖樣 X 方向寬度為 0。"
            return

        sel_str = ",".join(pattern_names)
        oeditor = hfss.modeler.oeditor

        # 若圖樣未置中於原點，先移回原點（Scale 以全域原點為基準）
        if abs(base_cx) > 1e-9 or abs(base_cy) > 1e-9:
            oeditor.Move(
                _selection(sel_str),
                ["NAME:TranslateParameters",
                 "TranslateVectorX:=", f"{-base_cx}{model_units}",
                 "TranslateVectorY:=", f"{-base_cy}{model_units}",
                 "TranslateVectorZ:=", "0mm"])

        # 反射相位表達式：取第一個 S(x,x) 對角項（Floquet Port 自反射）
        traces = []
        try:
            traces = hfss.get_traces_for_plot(category="S")
        except Exception:
            pass
        expr = None
        for t in traces:
            m = re.match(r"S\((.+?),(.+?)\)", t)
            if m and m.group(1) == m.group(2):
                expr = t
                break
        if expr is None and traces:
            expr = traces[0]
        if expr is None:
            _sweep["error"] = "專案沒有可用的 S 參數（找不到 Floquet Port／激勵）。請確認 unit cell 專案含有週期邊界與埠。"
            return

        setup_name = hfss.setups[0].name if hfss.setups else None
        if not setup_name:
            _sweep["error"] = "專案沒有 Analysis Setup。"
            return

        # 逐點掃描：縮放到目標 Lx → 求解 → 取相位
        rows = []
        current_lx = base_lx_um
        for i in range(n_pts):
            if cancelled():
                return
            target_lx = cfg.lx_min_um + (cfg.lx_max_um - cfg.lx_min_um) * i / (n_pts - 1)
            _sweep.update(phase=f"求解中（Lx={target_lx:.0f}um）", current=i + 1)

            factor = target_lx / current_lx
            oeditor.Scale(
                _selection(sel_str),
                ["NAME:ScaleParameters",
                 "ScaleX:=", str(factor), "ScaleY:=", str(factor), "ScaleZ:=", "1"])
            current_lx = target_lx

            ok = hfss.analyze_setup(setup_name)
            if not ok:
                _sweep["error"] = f"Lx={target_lx:.0f}um 的求解失敗，請檢查 AEDT 訊息視窗。"
                return
            sol = hfss.post.get_solution_data(
                expressions=expr,
                setup_sweep_name=f"{setup_name} : LastAdaptive")
            if not sol:
                _sweep["error"] = f"無法讀取 {expr} 的解（Lx={target_lx:.0f}um）。"
                return
            try:
                # pyaedt >= 1.x：formula="phase" 回傳弳度（phaserad 會重複轉換，勿用），自行轉成度
                _, vals = sol.get_expression_data(expression=expr, formula="phase")
                ph = math.degrees(float(vals[0]))
            except AttributeError:
                # 舊版 pyaedt
                re_v = sol.data_real()[0]
                im_v = sol.data_imag()[0]
                ph = math.degrees(math.atan2(im_v, re_v))
            ph = ((ph + 180.0) % 360.0) - 180.0  # 正規化到 -180 ~ 180
            rows.append((ph, target_lx))

        # 輸出 CSV 並載入為目前相位表
        _sweep["phase"] = "輸出 CSV 中"
        stem = proj_name.replace("_sweep", "")
        csv_name = f"{stem}_phase_sweep.csv"
        csv_path = os.path.join(static_dir, csv_name)
        df = pd.DataFrame(rows, columns=["phase", "Lx [um]"])
        df.to_csv(csv_path, index=False)
        load_data(df.copy())

        try:
            hfss.save_project()
        except Exception:
            pass

        _sweep["csv_url"] = f"/static/{csv_name}"
        ph_min = min(r[0] for r in rows)
        ph_max = max(r[0] for r in rows)
        coverage_hint = ""
        if (ph_max - ph_min) < 90.0:
            cell_hint = cell_mu * u  # cell 尺寸（mm）
            coverage_hint = (f"⚠ 相位涵蓋僅 {ph_max - ph_min:.1f}°，不足以做相位補償（理想需接近 360°）。"
                             f"表示此 Lx 範圍離共振區太遠，建議把 Lx 範圍往大尺寸調整"
                             f"（最大可到 cell 的 90% ≈ {cell_hint * 0.9 * 1000:.0f} um）並增加點數後重掃。")
        _sweep["result"] = (f"掃描完成！共 {len(rows)} 點（Lx {cfg.lx_min_um:.0f}–{cfg.lx_max_um:.0f} um，"
                            f"相位範圍 {ph_min:.1f}° ~ {ph_max:.1f}°）。"
                            f"已自動載入為目前相位表，CSV 可從 {csv_name} 下載。{coverage_hint}")
    except Exception as e:
        _sweep["error"] = f"相位掃描發生錯誤: {str(e)}"
    finally:
        _sweep.update(running=False, phase="完成")

@app.post("/api/sweep")
def start_sweep(cfg: SweepConfig):
    try:
        from ansys.aedt.core import Hfss  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")
    if not _get_current_project():
        return {"status": "error", "message": "請先按「選擇 UnitCell 專案檔」上傳 .aedt 或 .aedtz！"}
    if cfg.lx_max_um <= cfg.lx_min_um:
        return {"status": "error", "message": "Lx 最大值必須大於最小值。"}
    with _sweep_lock:
        if _sweep["running"] or _gen["running"]:
            return {"status": "error", "message": "已有作業進行中，請等它完成或先取消。"}
        _sweep.update(running=True, cancel=False, current=0, total=0,
                      phase="準備中", result=None, error=None, csv_url=None)
    threading.Thread(target=_run_sweep, args=(cfg,), daemon=True).start()
    return {"status": "started", "message": "相位掃描已開始（每點需完整求解一次，請耐心等候）。"}

@app.get("/api/sweep/status")
def sweep_status():
    return {k: _sweep[k] for k in ("running", "current", "total", "phase", "result", "error", "csv_url")}

@app.post("/api/sweep/cancel")
def sweep_cancel():
    if _sweep["running"]:
        _sweep["cancel"] = True
        return {"status": "success", "message": "取消要求已送出。"}
    return {"status": "success", "message": "目前沒有進行中的掃描。"}

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
