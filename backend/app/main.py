# 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
#
# 設計流程改寫自 Ansys 官方 MetaSurfaceToolkit（見專案根目錄 MetaSurfaceToolkit.pdf，
# 原作者：Sharon Varghese、Nijas Kunju、Mahesh Babu，© 2020 ANSYS, Inc.）。
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
    # 註：目前僅支援 Reflectarray（反射陣列），故未設 mode 欄位。
    # Transmitarray（穿透陣列）需要不同的饋源擺放與單元設計，尚未實作與驗證，
    # 之後若要支援請在此新增欄位並在 generate_preview／generate_aedt 中實際分流。
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
            # 本工具目前僅針對 Reflectarray（反射陣列）實測與驗證過。
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
        _gen["phase"] = "收尾：刪除原始物件"
        try:
            hfss.modeler.delete(pattern_names + tile_names)
        except Exception:
            for n in pattern_names + tile_names:
                _set_nonmodel(hfss, n)

        # 真空物件（輻射盒）先刪除：掛在其面上的 Master/Slave 與 Floquet Port
        # 只適用於單一 unit cell，一併移除後陣列才能重建自己的邊界
        if excluded_names:
            try:
                hfss.modeler.delete(excluded_names)
            except Exception:
                for n in excluded_names:
                    _set_nonmodel(hfss, n)

        # 清除從 unit cell 母本帶入、對陣列已無意義的設定：
        #   Optimetrics 參數掃描（掃單元尺寸變數，誤按會對上千 sheet 跑數十變化）
        #   單元的相位／幅度對尺寸報告（其產出已變成相位表，陣列階段用不到）
        try:
            opt = hfss.odesign.GetModule("Optimetrics")
            opt_names = list(opt.GetSetupNames())
            if opt_names:
                opt.DeleteSetups(opt_names)
        except Exception:
            pass
        try:
            rm = hfss.odesign.GetModule("ReportSetup")
            stale = [r for r in rm.GetAllReportNames()
                     if "Vs Dimension" in r or "vs dimension" in r.lower()]
            for r in stale:
                try:
                    rm.DeleteReports([r])
                except Exception:
                    pass
        except Exception:
            pass

        # 重新指定 PerfE 給所有金屬複製體（複製貼上不會帶邊界）。
        # 必須分批送出：單次傳入上千個物件會讓 gRPC 呼叫卡死且無法回報進度。
        if pasted_metal:
            BATCH = 100
            total_m = len(pasted_metal)
            for i in range(0, total_m, BATCH):
                if _gen["cancel"]:
                    break
                _gen["phase"] = f"收尾：指定金屬邊界 {min(i + BATCH, total_m)}/{total_m}"
                try:
                    hfss.assign_perfecte_to_sheets(
                        pasted_metal[i:i + BATCH], name=f"PerfE_array_{i // BATCH}")
                except Exception:
                    pass
                # 每三批存檔一次，中途若發生異常不至於前功盡棄
                if (i // BATCH) % 3 == 2:
                    try:
                        hfss.save_project()
                    except Exception:
                        pass

        # ── 模擬環境：空氣盒（λ/4 淨空）＋Radiation＋垂直入射平面波 ──
        _gen["phase"] = "收尾：建立模擬環境"
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

# ── 模擬結果：遠場切面、3D 方向圖、波束指向數值、表面電場 ──
results_dir = os.path.join(static_dir, "results")
os.makedirs(results_dir, exist_ok=True)

_res = {"running": False, "current": 0, "total": 4, "phase": "",
        "images": None, "summary": None, "result": None, "error": None}
_res_lock = threading.Lock()

class ResultsOptions(ArrayConfig):
    """結果讀取選項。預設值依 39.9MB 大陣列（約 1350 個金屬面）的實測耗時決定：
      遠場切面＋指標  約 14 秒
      3D 方向圖       約 16 秒（5° 與 10° 取樣幾乎同速）
      表面電場圖      逾 7 分鐘 ← 唯一的重項目，故預設關閉
    電場圖之所以慢，是因為要對全部金屬面計算並算繪場值，成本隨陣列規模暴增。"""
    want_efield: bool = False
    want_cuts: bool = True
    want_3d: bool = True
    pattern3d_step: float = 5.0    # 3D 遠場球取樣步進（度）

def _export_report_jpg(hfss, plot_name):
    """匯出報告圖檔並回傳可供前端存取的 URL（加時間戳避免瀏覽器快取）。"""
    hfss.post.export_report_to_jpg(results_dir, plot_name)
    return f"/static/results/{plot_name}.jpg?t={int(time.time())}"

def _cut_metrics(th, v):
    """對單一切面（theta 已限制在 ±90°）計算峰值方向、3dB 波束寬、旁瓣電平。"""
    if not th:
        return None
    pk = max(v); pi = v.index(pk)
    half = pk - 3.0
    left = right = None
    for i in range(pi, 0, -1):
        if v[i - 1] <= half:
            t1, t2, v1, v2 = th[i - 1], th[i], v[i - 1], v[i]
            left = t2 - (t2 - t1) * (v2 - half) / (v2 - v1) if v2 != v1 else t1
            break
    for i in range(pi, len(v) - 1):
        if v[i + 1] <= half:
            t1, t2, v1, v2 = th[i], th[i + 1], v[i], v[i + 1]
            right = t1 + (t2 - t1) * (v1 - half) / (v1 - v2) if v1 != v2 else t2
            break
    bw = round(right - left, 1) if (left is not None and right is not None) else None
    # 旁瓣：峰值兩側第一個零陷（局部極小且低於峰值 3dB）之外的最大值
    def first_null(dirn):
        i = pi
        while 0 < i + dirn < len(v):
            j = i + dirn
            if v[j] > v[i] and v[i] < pk - 3:
                return i
            i = j
        return None
    ln, rn = first_null(-1), first_null(+1)
    outside = []
    if ln is not None:
        outside += v[:ln]
    if rn is not None:
        outside += v[rn + 1:]
    sll = round(max(outside) - pk, 1) if outside else None
    return {"peak_db": round(pk, 2), "peak_theta": th[pi], "bw_3db": bw, "sll_db": sll}

def _run_results(config: ArrayConfig):
    from ansys.aedt.core import Hfss
    master = _get_current_project()
    try:
        if not master:
            _res["error"] = "尚未上傳 UnitCell 專案，找不到對應的陣列專案。"
            return
        if master.endswith("_master.aedt"):
            array_path = master[: -len("_master.aedt")] + "_array.aedt"
        else:
            array_path = master
        if not os.path.exists(array_path):
            _res["error"] = "找不到陣列專案，請先按「產生模型」建立陣列。"
            return

        _res.update(phase="開啟專案中", current=0)
        # 若 AEDT 已開著這個陣列專案（剛按過「產生模型」的常見情況），
        # 直接沿用該視窗，避免重開檔案造成鎖衝突（Project is locked）。
        proj_name = os.path.splitext(os.path.basename(array_path))[0]
        try:
            from ansys.aedt.core import Desktop
            d = Desktop(new_desktop=False, non_graphical=False)
            already_open = proj_name in d.project_list
        except Exception:
            already_open = False
        if already_open:
            hfss = Hfss(project=proj_name, non_graphical=False, new_desktop=False)
        else:
            # 專案未開啟卻留有鎖檔＝前次工作階段異常結束的殘留（例如後端被中止）。
            # 這是本工具在 static/ 自行產生的工作副本，清除殘留鎖檔是安全的。
            stale_lock = array_path + ".lock"
            if os.path.exists(stale_lock):
                try:
                    os.remove(stale_lock)
                except Exception:
                    pass
            hfss = Hfss(project=array_path, non_graphical=False, new_desktop=False)

        if not hfss.setups:
            _res["error"] = "專案沒有 Analysis Setup。"
            return
        setup_name = hfss.setups[0].name
        try:
            solved = hfss.setups[0].is_solved
        except Exception:
            solved = True
        if not solved:
            _res["error"] = ("陣列尚未求解。請先在 AEDT 中執行 Analyze，"
                             "完成後再按「顯示模擬結果」。")
            return
        sweep = f"{setup_name} : LastAdaptive"

        # 頻率與口徑一律以「專案本身」為準，不信任前端狀態——
        # 頁面重新整理後前端可能仍是預設參數，用錯頻率會查不到解。
        freq_ghz = config.frequency
        try:
            fstr = str(hfss.setups[0].props.get("Frequency", "")).strip()
            m = re.match(r"([\d.]+)\s*(THz|GHz|MHz|kHz|Hz)", fstr, re.I)
            if m:
                mult = {"thz": 1000.0, "ghz": 1.0, "mhz": 1e-3, "khz": 1e-6, "hz": 1e-9}[m.group(2).lower()]
                freq_ghz = float(m.group(1)) * mult
        except Exception:
            pass
        freq_str = f"{freq_ghz:g}GHz"

        # 口徑量測。務必避免「逐一查詢每個物件」——每個物件的 material_name 與
        # bounding_box 各是一次 gRPC 往返，上千個物件會累積成好幾分鐘。
        # 改為單次取得整體邊界盒（含空氣盒），再扣掉本工具建立空氣盒時用的 λ/4 淨空。
        _res.update(phase="量測陣列口徑")
        ap_mm = None
        try:
            u_mm = _UNIT_TO_MM.get((hfss.modeler.model_units or "mm").lower(), 1.0)
            lam_mm = 300.0 / freq_ghz if freq_ghz > 0 else 30.0
            bb = hfss.modeler.get_model_bounding_box()   # 單次呼叫
            if bb and len(bb) >= 6:
                span = max(float(bb[3]) - float(bb[0]), float(bb[4]) - float(bb[1])) * u_mm
                has_airbox = "airbox_array" in hfss.modeler.object_names
                ap_mm = span - 2 * (lam_mm / 4.0) if has_airbox else span
                if ap_mm <= 0:
                    ap_mm = None
        except Exception:
            pass

        images, summary = {}, {}

        # 清除母本帶來的單元報告，以及上一次執行留下的遠場報告。
        # 後者非清不可：專案中只要已存在報告，AEDT 就會拒絕建立場圖，
        # 導致第二次以後執行時表面電場圖無法產生。
        OUR_REPORTS = ("ScatteredField_Cuts", "Pattern3D")
        try:
            rm = hfss.odesign.GetModule("ReportSetup")
            for r in list(rm.GetAllReportNames()):
                if "vs dimension" in r.lower() or r in OUR_REPORTS:
                    try:
                        rm.DeleteReports([r])
                    except Exception:
                        pass
        except Exception:
            pass

        # 依「由輕到重」的順序產生，每完成一項就立即回報，
        # 讓前端不必等全部跑完就能看到已完成的圖。
        def publish():
            _res["images"] = dict(images)
            _res["summary"] = dict(summary)

        steps = []
        if config.want_efield:
            steps.append("efield")
        if config.want_cuts:
            steps.append("cuts")
        steps.append("metrics")
        if config.want_3d:
            steps.append("pattern3d")
        _res["total"] = len(steps)
        done = 0

        # ① 表面電場分佈（最上層金屬）
        # 註：必須在建立遠場報告之前執行，否則 AEDT 會拒絕建立場圖
        if config.want_efield:
            done += 1
            _res.update(phase="產生表面電場圖", current=done)
            try:
                metal = [n for n in hfss.modeler.object_names
                         if n.startswith("Polyline") or n.startswith("out")]
                if not metal:
                    summary["efield_note"] = "找不到金屬物件，略過表面電場圖。"
                else:
                    # 挑出最上層金屬需要逐一查 bounding_box（每次一個 gRPC 往返），
                    # 物件多時代價極高，因此僅在小模型才精挑，大陣列直接用全部金屬。
                    if len(metal) <= 150:
                        zmax = max(hfss.modeler[n].bounding_box[5] for n in metal)
                        top = [n for n in metal
                               if abs(hfss.modeler[n].bounding_box[5] - zmax) < 1e-6]
                    else:
                        top = metal
                        summary["efield_note"] = (
                            f"金屬物件較多（{len(metal)} 件），電場圖顯示全部金屬層"
                            "（未篩選最上層，以避免逐一查詢造成的長時間等待）。")
                    for old in list(hfss.post.field_plot_names):
                        if old.startswith("Efield_Top"):
                            try:
                                hfss.post.delete_field_plot(old)
                            except Exception:
                                pass
                    plot_name = f"Efield_Top_{int(time.time())}"
                    fp = hfss.post.create_fieldplot_surface(
                        top, "Mag_E",
                        intrinsics={"Freq": freq_str, "Phase": "0deg"},
                        plot_name=plot_name)
                    if not fp:
                        summary["efield_note"] = "AEDT 未能建立表面電場圖（可能是解中沒有場資料）。"
                    else:
                        jpg = os.path.join(results_dir, "Efield_Top.jpg")
                        hfss.post.export_field_jpg(jpg, plot_name, "Fields")
                        if os.path.exists(jpg):
                            images["efield"] = f"/static/results/Efield_Top.jpg?t={int(time.time())}"
                        else:
                            summary["efield_note"] = "表面電場圖匯出失敗（檔案未產生）。"
            except Exception as e:
                summary["efield_note"] = f"表面電場圖產生失敗：{e}"
            publish()

        # ② 遠場方向圖（二維切面）——只掃兩個 phi 平面，遠比 3D 輕
        rpt = None
        if config.want_cuts:
            done += 1
            _res.update(phase="產生遠場切面圖", current=done)
            try:
                if "FarField_Cuts" not in [f.name for f in hfss.field_setups]:
                    hfss.insert_infinite_sphere(theta_start=-180, theta_stop=180, theta_step=2,
                                                phi_start=0, phi_stop=90, phi_step=90,
                                                name="FarField_Cuts")
                rpt = hfss.post.create_report(
                    expressions=["dB(rETotal)"], report_category="Far Fields",
                    context="FarField_Cuts", setup_sweep_name=sweep,
                    primary_sweep_variable="Theta",
                    variations={"Phi": ["0deg", "90deg"], "Freq": [freq_str]},
                    plot_name="ScatteredField_Cuts")
                if rpt:
                    images["cuts"] = _export_report_jpg(hfss, "ScatteredField_Cuts")
            except Exception as e:
                summary["cuts_note"] = f"遠場切面圖產生失敗：{e}"
            publish()

        # ③ 波束品質指標——改由切面資料計算（2° 解析度優於 3D 的 5°/10°），
        #    因此不需要 3D 方向圖也能取得完整指標。
        done += 1
        _res.update(phase="計算波束指標", current=done)
        try:
            lam = 300.0 / freq_ghz if freq_ghz > 0 else 30.0
            ap = ap_mm if ap_mm else config.num_elements * config.unit_cell_size
            summary.update({
                "design_theta": config.beam_theta, "design_phi": config.beam_phi,
                "aperture_lambda": round(ap / lam, 2),
                "directivity_theory_db": round(10 * math.log10(4 * math.pi * ap * ap / (lam * lam)), 1),
                "resolution": 2,
            })
            if config.want_cuts:
                for phi_lbl, key in (("0deg", "phi0"), ("90deg", "phi90")):
                    dc = hfss.post.get_solution_data(
                        expressions="dB(rETotal)", report_category="Far Fields",
                        context="FarField_Cuts", setup_sweep_name=sweep,
                        variations={"Freq": [freq_str], "Phi": [phi_lbl]},
                        primary_sweep_variable="Theta")
                    if dc:
                        th = [float(t) for t in dc.primary_sweep_values]
                        _, vv = dc.get_expression_data(expression="dB(rETotal)", formula="real")
                        pts = [(t, float(x)) for t, x in zip(th, vv) if abs(t) <= 90]
                        m = _cut_metrics([q[0] for q in pts], [q[1] for q in pts])
                        if m:
                            summary[key] = m
                # 峰值取兩切面中較高者；RCS = 4π|rE|²/|Einc|²（Einc 預設 1 V/m）
                peaks = [summary[k]["peak_db"] for k in ("phi0", "phi90") if k in summary]
                if peaks:
                    summary["rcs_peak_dbsm"] = round(max(peaks) + 10.99, 1)
                ref = summary.get("phi0") or summary.get("phi90")
                if ref:
                    summary["reflect_theta"] = ref["peak_theta"]
                    summary["theta_error"] = round(abs(ref["peak_theta"] - config.beam_theta), 1)
            else:
                summary["beam_note"] = "未產生遠場切面圖，無法計算波束寬與旁瓣電平。"
        except Exception as e:
            summary["beam_note"] = f"波束指標計算失敗：{e}"
        publish()

        # ④ 三維立體方向圖（選用）——方向數 = (180/step+1) × (360/step)，
        #    5° 約 2664 個、10° 約 684 個，但實測兩者都約 16 秒：
        #    成本主要在載入場解，而非逐方向積分。
        if config.want_3d:
            done += 1
            step3d = max(2.0, float(config.pattern3d_step or 10.0))
            _res.update(phase=f"產生 3D 方向圖（{step3d:g}° 取樣）", current=done)
            try:
                sph = f"FarField_3D_{step3d:g}".replace(".", "p")
                if sph not in [f.name for f in hfss.field_setups]:
                    hfss.insert_infinite_sphere(
                        theta_start=0, theta_stop=180, theta_step=step3d,
                        phi_start=0, phi_stop=360 - step3d, phi_step=step3d,
                        name=sph)
                r3 = hfss.post.create_report(
                    expressions=["dB(rETotal)"], report_category="Far Fields",
                    context=sph, setup_sweep_name=sweep,
                    plot_type="3D Polar Plot",
                    primary_sweep_variable="Phi", secondary_sweep_variable="Theta",
                    variations={"Freq": [freq_str]}, plot_name="Pattern3D")
                if r3:
                    images["pattern3d"] = _export_report_jpg(hfss, "Pattern3D")
            except Exception as e:
                summary["pattern3d_note"] = f"3D 方向圖產生失敗：{e}"
            publish()

        try:
            hfss.save_project()
        except Exception:
            pass

        publish()
        _res["result"] = f"已產生 {len(images)} 張結果圖。"
    except Exception as e:
        _res["error"] = f"讀取模擬結果時發生錯誤：{str(e)}"
    finally:
        _res.update(running=False, phase="完成")

@app.post("/api/results")
def start_results(config: ResultsOptions):
    try:
        from ansys.aedt.core import Hfss  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=500, detail="PyAEDT 尚未安裝或環境未正確載入")
    with _res_lock:
        if _res["running"] or _gen["running"] or _sweep["running"]:
            return {"status": "error", "message": "已有作業進行中，請等它完成或先取消。"}
        _res.update(running=True, current=0, total=4, phase="準備中",
                    images=None, summary=None, result=None, error=None)
    threading.Thread(target=_run_results, args=(config,), daemon=True).start()
    return {"status": "started", "message": "正在讀取模擬結果..."}

@app.get("/api/results/status")
def results_status():
    return {k: _res[k] for k in
            ("running", "current", "total", "phase", "images", "summary", "result", "error")}

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

# ── 生產環境：託管前端建置成品（frontend/dist）──
# 必須放在所有 /api 路由之後掛載，避免遮蔽 API 路徑。
# 開發時（npm run dev）由 Vite 開發伺服器提供頁面，此掛載不會生效（dist 目錄通常不存在）；
# 對外發布（GitHub 下載）時 dist 已隨版控附上，使用者僅需啟動這個後端即可，不需安裝 Node.js。
_frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8010)
