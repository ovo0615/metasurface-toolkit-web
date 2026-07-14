// 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
import React, { useState, useEffect, useRef } from 'react'
import Preview2D from './components/Preview2D'
import Preview3D from './components/Preview3D'
import type { PreviewData } from './components/Preview2D'
import { fetchPreview, generateModel, uploadFile, uploadModel } from './api'
import type { ArrayConfig } from './api'
import './index.css'

export default function App() {
  const [config, setConfig] = useState<ArrayConfig>({
    mode: "Reflectarray",
    shape: "Square",
    frequency: 10,
    unit_cell_size: 8,
    num_elements: 40,
    feed_x: 0,
    feed_y: 0,
    feed_z: 320,
    beam_theta: 0,
    beam_phi: 0
  })

  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState("")
  const [fileName, setFileName] = useState("預設 (Phase_dim_PG_45.csv)")
  const [modelName, setModelName] = useState("無 (使用內建 2D)")
  const [viewMode, setViewMode] = useState<"2D" | "3D">("2D")
  const fileInputRef = useRef<HTMLInputElement>(null)
  const modelInputRef = useRef<HTMLInputElement>(null)

  const loadPreview = async (currentConfig: ArrayConfig) => {
    try {
      const data = await fetchPreview(currentConfig)
      
      const bowties = data.elements.map((el: any) => {
        const W = el.size_x;
        const H = el.size_y * 0.8; // 高度佔 cell 的 80%
        const cx = el.x;
        const cy = el.y;
        // 蝴蝶結的中央縮腰寬度，設為總寬度的 20%
        const waist = W * 0.1; 
        return {
          kind: 'polygon',
          points: [
            [cx - W/2, cy + H/2],
            [cx - waist, cy],
            [cx - W/2, cy - H/2],
            [cx + W/2, cy - H/2],
            [cx + waist, cy],
            [cx + W/2, cy + H/2]
          ]
        }
      })

      const grid = [];
      const minX = data.bounds.minX;
      const maxX = data.bounds.maxX;
      const minY = data.bounds.minY;
      const maxY = data.bounds.maxY;

      // 產生垂直格線
      for(let c = 0; c <= currentConfig.num_elements; c++) {
         grid.push({
           kind: 'rect',
           x: minX + c * currentConfig.unit_cell_size - 0.02,
           y: minY,
           w: 0.04,
           h: maxY - minY
         });
      }
      // 產生水平格線
      for(let r = 0; r <= currentConfig.num_elements; r++) {
         grid.push({
           kind: 'rect',
           x: minX,
           y: minY + r * currentConfig.unit_cell_size - 0.02,
           w: maxX - minX,
           h: 0.04
         });
      }

      // 底板
      const substrate = [{
         kind: 'rect',
         x: minX,
         y: minY,
         w: maxX - minX,
         h: maxY - minY
      }];

      const layers: Record<string, any[]> = {
        'Substrate': substrate,
        'Grid': grid,
        'Metal': bowties
      }
      
      const layer_colors: Record<string, number[]> = {
        'Substrate': [70, 100, 100], // 沉穩的墨綠色底板
        'Grid': [110, 130, 130],     // 稍亮的格線
        'Metal': [190, 190, 190]     // 金屬銀灰色天線
      }

      setPreviewData({
        layers,
        layer_colors,
        layer_order: ['Substrate', 'Grid', 'Metal'],
        bounds: {
          min: [minX, minY],
          max: [maxX, maxY]
        },
        rawElements: data.elements
      })
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    loadPreview(config)
  }, [config])

  const handleGenerate = async () => {
    setLoading(true)
    setMsg("正在呼叫 HFSS 建模，請稍候...")
    try {
      const res = await generateModel(config)
      setMsg(res.message)
    } catch (e: any) {
      setMsg(e.message || "發生錯誤")
    }
    setLoading(false)
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    
    setLoading(true)
    setMsg(`正在上傳 ${file.name}...`)
    try {
      const res = await uploadFile(file)
      setFileName(file.name)
      setMsg(res.message)
      // 重新載入預覽
      loadPreview(config)
    } catch (e: any) {
      setMsg(e.message || "上傳失敗")
    }
    setLoading(false)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleModelChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    
    setLoading(true)
    setMsg(`正在處理模型 ${file.name}...`)
    try {
      const res = await uploadModel(file)
      setModelName(file.name)
      setMsg(res.message)
      setViewMode("3D") // 自動切換到 3D
      // 強制重新載入預覽或觸發 3D 元件更新
      loadPreview(config)
    } catch (e: any) {
      setMsg(e.message || "上傳模型失敗")
    }
    setLoading(false)
    if (modelInputRef.current) modelInputRef.current.value = ""
  }

  const inputStyle = { width: '100%', padding: '8px', background: 'var(--bg-input)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: '4px' }

  return (
    <div className="app-container">
      {/* 左側面板 - 參數控制 */}
      <div className="glass-panel" style={{ width: '320px', padding: '20px', overflowY: 'auto', flexShrink: 0 }}>
        <h2 style={{ color: 'var(--accent)', marginTop: 0 }}>Metasurface Toolkit</h2>
        <p style={{ fontSize: '0.9em', color: 'var(--text-muted)' }}>此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供</p>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', marginTop: '20px' }}>
          
          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>真實 3D 模型 (UnitCell)：</div>
            <div style={{ color: 'var(--accent)', marginBottom: '10px', wordBreak: 'break-all' }}>{modelName}</div>
            <input 
              type="file" 
              accept=".obj, .aedtz" 
              ref={modelInputRef} 
              style={{ display: 'none' }} 
              onChange={handleModelChange} 
            />
            <button className="premium-btn" style={{ width: '100%', background: '#ff9800', marginBottom: '10px' }} onClick={() => modelInputRef.current?.click()} disabled={loading}>
              📂 選擇 UnitCell 模型
            </button>
            <div style={{ display: 'flex', gap: '5px' }}>
              <button 
                onClick={() => setViewMode("2D")} 
                style={{ flex: 1, padding: '5px', borderRadius: '4px', border: '1px solid #555', background: viewMode === '2D' ? '#555' : 'transparent', color: 'white', cursor: 'pointer' }}>
                2D 預覽
              </button>
              <button 
                onClick={() => setViewMode("3D")} 
                style={{ flex: 1, padding: '5px', borderRadius: '4px', border: '1px solid #555', background: viewMode === '3D' ? '#555' : 'transparent', color: 'white', cursor: 'pointer' }}>
                3D 預覽
              </button>
            </div>
          </div>

          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>目前資料來源：</div>
            <div style={{ color: 'var(--accent)', marginBottom: '10px', wordBreak: 'break-all' }}>{fileName}</div>
            <input 
              type="file" 
              accept=".csv, .xlsx" 
              ref={fileInputRef} 
              style={{ display: 'none' }} 
              onChange={handleFileChange} 
            />
            <button className="premium-btn" style={{ width: '100%', background: '#2ea043' }} onClick={() => fileInputRef.current?.click()} disabled={loading}>
              📁 選擇 Excel / CSV
            </button>
          </div>

          <label>
            Mode of Operation
            <select value={config.mode} onChange={e => setConfig({...config, mode: e.target.value})} style={inputStyle}>
              <option value="Reflectarray">Reflectarray</option>
              <option value="Transmitarray">Transmitarray</option>
            </select>
          </label>
          <label>
            Shape of Array
            <select value={config.shape} onChange={e => setConfig({...config, shape: e.target.value})} style={inputStyle}>
              <option value="Square">Square</option>
            </select>
          </label>
          <label>
            Frequency [GHz]
            <input type="number" value={config.frequency} onChange={e => setConfig({...config, frequency: parseFloat(e.target.value)})} style={inputStyle} />
          </label>
          <label>
            Unit Cell Size [mm]
            <input type="number" value={config.unit_cell_size} onChange={e => setConfig({...config, unit_cell_size: parseFloat(e.target.value)})} style={inputStyle} />
          </label>
          <label>
            Number of Elements
            <input type="number" value={config.num_elements} onChange={e => setConfig({...config, num_elements: parseInt(e.target.value)})} style={inputStyle} />
          </label>
          
          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>Feed Coordinates [mm]</div>
            <div style={{ display: 'flex', gap: '5px' }}>
              <label style={{flex: 1}}>X <input type="number" value={config.feed_x} onChange={e => setConfig({...config, feed_x: parseFloat(e.target.value)})} style={inputStyle} /></label>
              <label style={{flex: 1}}>Y <input type="number" value={config.feed_y} onChange={e => setConfig({...config, feed_y: parseFloat(e.target.value)})} style={inputStyle} /></label>
              <label style={{flex: 1}}>Z <input type="number" value={config.feed_z} onChange={e => setConfig({...config, feed_z: parseFloat(e.target.value)})} style={inputStyle} /></label>
            </div>
          </div>

          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>Beam Direction [deg]</div>
            <div style={{ display: 'flex', gap: '5px' }}>
              <label style={{flex: 1}}>Phi <input type="number" value={config.beam_phi} onChange={e => setConfig({...config, beam_phi: parseFloat(e.target.value)})} style={inputStyle} /></label>
              <label style={{flex: 1}}>Theta <input type="number" value={config.beam_theta} onChange={e => setConfig({...config, beam_theta: parseFloat(e.target.value)})} style={inputStyle} /></label>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
            <button className="premium-btn" onClick={handleGenerate} disabled={loading} style={{ flex: 1 }}>
              {loading ? "處理中..." : "產生模型"}
            </button>
            <button 
              className="premium-btn" 
              onClick={async () => {
                setLoading(true);
                setMsg("正在釋放...");
                try { 
                  const { releaseAedt } = await import('./api');
                  const res = await releaseAedt(); 
                  setMsg(res.message); 
                } catch(e: any) { setMsg(e.message); }
                setLoading(false);
              }} 
              disabled={loading} 
              style={{ flex: 1, background: '#d32f2f' }}
            >
              釋放 AEDT
            </button>
          </div>
          {msg && <div style={{ color: 'var(--accent)', fontSize: '0.9em', marginTop: '10px' }}>{msg}</div>}
        </div>
      </div>

      {/* 中央預覽 */}
      <div style={{ flex: 1, position: 'relative' }}>
        {viewMode === '2D' ? (
          <Preview2D data={previewData} />
        ) : (
          <Preview3D data={previewData} />
        )}
      </div>
    </div>
  )
}

// 輔助函數
const inputStyle = {
  width: '100%', padding: '8px', marginTop: '5px', borderRadius: '4px', border: '1px solid var(--border-light)', background: 'rgba(0,0,0,0.2)', color: 'white'
}

function hslToRgb(h: number, s: number, l: number) {
  let r, g, b;
  if(s == 0){ r = g = b = l; }
  else{
      var hue2rgb = function hue2rgb(p: number, q: number, t: number){
          if(t < 0) t += 1;
          if(t > 1) t -= 1;
          if(t < 1/6) return p + (q - p) * 6 * t;
          if(t < 1/2) return q;
          if(t < 2/3) return p + (q - p) * (2/3 - t) * 6;
          return p;
      }
      var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      var p = 2 * l - q;
      r = hue2rgb(p, q, h + 1/3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1/3);
  }
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}
