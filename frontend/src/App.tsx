// 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
import React, { useState, useEffect, useRef } from 'react'
import Preview2D from './components/Preview2D'
import ResultsView from './components/ResultsView'
import type { PreviewData } from './components/Preview2D'
import { fetchPreview, generateModel, uploadFile, uploadProject, releaseAedt, getGenerateStatus, cancelGenerate, startSweep, getSweepStatus, cancelSweep, startResults, getResultsStatus } from './api'
import type { ArrayConfig, GenerateStatus, SweepStatus, ResultsStatus } from './api'
import './index.css'

export default function App() {
  // 預設值對齊內建資料表 Phase_dim_PG_45.csv（140GHz 蝴蝶結單元、cell 1mm）
  const [config, setConfig] = useState<ArrayConfig>({
    mode: "Reflectarray",
    shape: "Square",
    frequency: 140,
    unit_cell_size: 1,
    num_elements: 20,
    feed_x: 0,
    feed_y: 0,
    feed_z: 16,
    beam_theta: 0,
    beam_phi: 0
  })

  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState("")
  const [fileName, setFileName] = useState("尚未選擇")
  const [projectName, setProjectName] = useState("尚未選擇")
  // 使用者尚未上傳相位表前，不顯示預覽以免誤以為已匯入
  const [dataReady, setDataReady] = useState(false)
  // 建模作業進度（null 表示沒有進行中的作業）
  const [genStatus, setGenStatus] = useState<GenerateStatus | null>(null)
  const pollRef = useRef<number | null>(null)
  // 相位掃描設定與進度
  const [sweepCfg, setSweepCfg] = useState({ lx_min_um: 600, lx_max_um: 2800, points: 9 })
  const [sweepStatus, setSweepStatus] = useState<SweepStatus | null>(null)
  const sweepPollRef = useRef<number | null>(null)
  // 模擬結果（圖檔與波束指向數值）
  const [resStatus, setResStatus] = useState<ResultsStatus | null>(null)
  const [results, setResults] = useState<ResultsStatus | null>(null)
  const resPollRef = useRef<number | null>(null)
  // 由專案自動帶入的欄位（帶入後鎖定，避免誤觸改動；可刻意解鎖）
  const [autoFilled, setAutoFilled] = useState({ unit_cell_size: false, frequency: false })
  const [fieldsUnlocked, setFieldsUnlocked] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const projectInputRef = useRef<HTMLInputElement>(null)

  const cellLocked = autoFilled.unit_cell_size && !fieldsUnlocked
  const freqLocked = autoFilled.frequency && !fieldsUnlocked

  // 元件卸載時停止輪詢
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (sweepPollRef.current) clearInterval(sweepPollRef.current)
    if (resPollRef.current) clearInterval(resPollRef.current)
  }, [])

  const handleResults = async () => {
    setMsg("正在讀取模擬結果...")
    try {
      const res = await startResults(config)
      if (res.status !== "started") {
        setMsg(res.message)
        return
      }
      setResStatus({ running: true, current: 0, total: 4, phase: "準備中", images: null, summary: null, result: null, error: null })
      if (resPollRef.current) clearInterval(resPollRef.current)
      resPollRef.current = window.setInterval(async () => {
        try {
          const s = await getResultsStatus()
          setResStatus(s)
          if (!s.running) {
            if (resPollRef.current) clearInterval(resPollRef.current)
            resPollRef.current = null
            setResStatus(null)
            if (s.error) {
              setMsg(`發生錯誤：${s.error}`)
            } else {
              setResults(s)          // 切換到結果檢視
              setMsg(s.result || "結果已產生。")
            }
          }
        } catch { /* 下一秒再試 */ }
      }, 1000)
    } catch (e: any) {
      setMsg(e.message || "讀取結果失敗")
    }
  }

  const handleSweep = async () => {
    setMsg("正在啟動相位掃描...")
    try {
      const res = await startSweep(sweepCfg.lx_min_um, sweepCfg.lx_max_um, sweepCfg.points)
      if (res.status !== "started") {
        setMsg(res.message)
        return
      }
      setMsg(res.message)
      setSweepStatus({ running: true, current: 0, total: 0, phase: "準備中", result: null, error: null, csv_url: null })
      if (sweepPollRef.current) clearInterval(sweepPollRef.current)
      sweepPollRef.current = window.setInterval(async () => {
        try {
          const s = await getSweepStatus()
          setSweepStatus(s)
          if (!s.running) {
            if (sweepPollRef.current) clearInterval(sweepPollRef.current)
            sweepPollRef.current = null
            setSweepStatus(null)
            setMsg(s.error ? `發生錯誤：${s.error}` : (s.result || "掃描完成。"))
            if (!s.error && s.csv_url) {
              // 掃描成功：後端已載入新相位表，更新來源顯示並重算預覽
              setFileName(s.csv_url.split("/").pop() || "掃描結果")
              setDataReady(true)
              loadPreview(config)
            }
          }
        } catch { /* 下一秒再試 */ }
      }, 1000)
    } catch (e: any) {
      setMsg(e.message || "啟動掃描失敗")
    }
  }

  const loadPreview = async (currentConfig: ArrayConfig) => {
    try {
      const data = await fetchPreview(currentConfig)
      
      const bowties = data.elements.map((el: any) => {
        const W = el.size_x;
        const H = el.size_y; // 後端已回傳實際 Ly（原始設計 Ly = Lx）
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
    setMsg("正在啟動建模作業...")
    try {
      const res = await generateModel(config)
      if (res.status !== "started") {
        setMsg(res.message)
        return
      }
      // 後端對「相位表與 cell 尺寸不成比例」等情況的警告，在建模期間持續顯示
      setMsg(res.warning || "")
      setGenStatus({ running: true, current: 0, total: 0, phase: "準備中", result: null, error: null })
      // 每秒輪詢進度，結束後顯示結果
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = window.setInterval(async () => {
        try {
          const s = await getGenerateStatus()
          setGenStatus(s)
          if (!s.running) {
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
            setGenStatus(null)
            setMsg(s.error ? `發生錯誤：${s.error}` : (s.result || "建模完成。"))
          }
        } catch { /* 後端暫時無回應時下一秒再試 */ }
      }, 1000)
    } catch (e: any) {
      setMsg(e.message || "發生錯誤")
    }
  }

  const handleCancel = async () => {
    try {
      const res = await cancelGenerate()
      setMsg(res.message)
    } catch (e: any) {
      setMsg(e.message || "取消失敗")
    }
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
      setDataReady(true)
      // 重新載入預覽
      loadPreview(config)
    } catch (e: any) {
      setMsg(e.message || "上傳失敗")
    }
    setLoading(false)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const handleProjectChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setLoading(true)
    setMsg(`正在上傳專案 ${file.name} 並偵測參數（AEDT 未開啟時會自動啟動，請稍候）...`)
    try {
      const res = await uploadProject(file)
      setProjectName(file.name)
      // 自動帶入偵測到的專案參數（unit cell 尺寸、Setup 頻率）並鎖定
      if (res.detected) {
        setConfig(c => ({
          ...c,
          unit_cell_size: res.detected.unit_cell_size ?? c.unit_cell_size,
          frequency: res.detected.frequency ?? c.frequency,
        }))
        setAutoFilled({
          unit_cell_size: res.detected.unit_cell_size != null,
          frequency: res.detected.frequency != null,
        })
        setFieldsUnlocked(false)
      }
      setMsg(res.message)
    } catch (e: any) {
      setMsg(e.message || "上傳專案失敗")
    }
    setLoading(false)
    if (projectInputRef.current) projectInputRef.current.value = ""
  }

  // 註：index.css 定義的是 --border-light／--text-main，先前誤用不存在的
  //     --border／--bg-input／--text，導致所有輸入框其實都沒有框線。
  const inputStyle = { width: '100%', padding: '8px', background: 'rgba(0,0,0,0.25)', border: '1px solid var(--border-light)', color: 'var(--text-main)', borderRadius: '4px' }
  // 由專案帶入而鎖定的欄位：虛線框與淡字明確表示不可編輯，數值仍清楚可讀
  const lockedInputStyle = {
    ...inputStyle,
    background: 'rgba(255,255,255,0.04)',
    border: '1px dashed var(--border-light)',
    color: 'var(--text-muted)',
    cursor: 'not-allowed' as const,
  }
  const labelRowStyle = { display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px' }
  const lockTagStyle = { fontSize: '0.72em', color: 'var(--text-muted)', whiteSpace: 'nowrap' as const }

  return (
    <div className="app-container">
      {/* 左側面板 - 參數控制 */}
      <div className="glass-panel" style={{ width: '320px', padding: '20px', overflowY: 'auto', flexShrink: 0 }}>
        <h2 style={{ color: 'var(--accent)', marginTop: 0 }}>Metasurface Toolkit</h2>
        <p style={{ fontSize: '0.9em', color: 'var(--text-muted)' }}>此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供</p>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', marginTop: '20px' }}>
          
          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>① 相位資料表（phase–Lx）：</div>
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

          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '5px' }}>② UnitCell 專案檔（不需先開啟）：</div>
            <div style={{ color: 'var(--accent)', marginBottom: '10px', wordBreak: 'break-all' }}>{projectName}</div>
            <input
              type="file"
              accept=".aedt, .aedtz"
              ref={projectInputRef}
              style={{ display: 'none' }}
              onChange={handleProjectChange}
            />
            <button className="premium-btn" style={{ width: '100%', background: '#ff9800' }} onClick={() => projectInputRef.current?.click()} disabled={loading}>
              📂 選擇 UnitCell 專案檔
            </button>
          </div>

          <div style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '8px' }}>
              ③ 由 UnitCell 自動產生相位表（逐點求解，較耗時）：
            </div>
            <div style={{ display: 'flex', gap: '5px', marginBottom: '8px' }}>
              <label style={{ flex: 1, fontSize: '0.8em' }}>Lx 最小 [µm]
                <input type="number" value={sweepCfg.lx_min_um} onChange={e => setSweepCfg({ ...sweepCfg, lx_min_um: parseFloat(e.target.value) })} style={inputStyle} />
              </label>
              <label style={{ flex: 1, fontSize: '0.8em' }}>Lx 最大 [µm]
                <input type="number" value={sweepCfg.lx_max_um} onChange={e => setSweepCfg({ ...sweepCfg, lx_max_um: parseFloat(e.target.value) })} style={inputStyle} />
              </label>
              <label style={{ flex: 1, fontSize: '0.8em' }}>點數
                <input type="number" value={sweepCfg.points} onChange={e => setSweepCfg({ ...sweepCfg, points: parseInt(e.target.value) })} style={inputStyle} />
              </label>
            </div>
            {sweepStatus ? (
              <>
                <div style={{ fontSize: '0.85em', color: 'var(--text)', marginBottom: '6px' }}>
                  {sweepStatus.phase}
                  {sweepStatus.total > 0 && `：${sweepStatus.current} / ${sweepStatus.total} 點`}
                </div>
                <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden', marginBottom: '8px' }}>
                  <div style={{
                    height: '100%', borderRadius: '3px', background: '#42a5f5',
                    width: sweepStatus.total > 0 ? `${(sweepStatus.current / sweepStatus.total * 100).toFixed(1)}%` : '5%',
                    transition: 'width 0.5s'
                  }} />
                </div>
                <button className="premium-btn" style={{ width: '100%', background: '#d32f2f' }}
                        onClick={async () => { const r = await cancelSweep(); setMsg(r.message) }}>
                  ⏹ 取消掃描
                </button>
              </>
            ) : (
              <button className="premium-btn" style={{ width: '100%', background: '#1976d2' }} onClick={handleSweep} disabled={loading || !!genStatus}>
                🔄 掃描產生相位表
              </button>
            )}
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
            <span style={labelRowStyle}>Frequency [GHz]{freqLocked && <span style={lockTagStyle}>🔒 由專案帶入</span>}</span>
            <input
              type="number"
              value={config.frequency}
              readOnly={freqLocked}
              onChange={e => { if (!freqLocked) setConfig({...config, frequency: parseFloat(e.target.value)}) }}
              style={freqLocked ? lockedInputStyle : inputStyle}
            />
          </label>
          <label>
            <span style={labelRowStyle}>Unit Cell Size [mm]{cellLocked && <span style={lockTagStyle}>🔒 由專案帶入</span>}</span>
            <input
              type="number"
              value={config.unit_cell_size}
              readOnly={cellLocked}
              onChange={e => { if (!cellLocked) setConfig({...config, unit_cell_size: parseFloat(e.target.value)}) }}
              style={cellLocked ? lockedInputStyle : inputStyle}
            />
          </label>
          {(freqLocked || cellLocked) && (
            <button
              onClick={() => setFieldsUnlocked(true)}
              style={{
                alignSelf: 'flex-start', marginTop: '-8px', padding: 0,
                background: 'none', border: 'none', color: 'var(--text-muted)',
                fontSize: '0.8em', textDecoration: 'underline', cursor: 'pointer'
              }}
            >
              解鎖編輯（偵測值與專案不符時才需要）
            </button>
          )}
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
            {genStatus ? (
              <button className="premium-btn" onClick={handleCancel} style={{ flex: 1, background: '#d32f2f' }}>
                ⏹ 取消建模
              </button>
            ) : (
              <>
                <button className="premium-btn" onClick={handleGenerate} disabled={loading} style={{ flex: 1 }}>
                  {loading ? "處理中..." : "產生模型"}
                </button>
                <button
                  className="premium-btn"
                  onClick={async () => {
                    setLoading(true);
                    setMsg("正在釋放...");
                    try {
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
              </>
            )}
          </div>

          {!genStatus && (
            <button
              className="premium-btn"
              style={{ width: '100%', background: '#6a1b9a', marginTop: '10px' }}
              onClick={handleResults}
              disabled={loading || !!resStatus || !!sweepStatus}
            >
              {resStatus ? `讀取中：${resStatus.phase}` : "📊 顯示模擬結果"}
            </button>
          )}
          {resStatus && (
            <div style={{ marginTop: '8px', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
              <div style={{
                height: '100%', borderRadius: '3px', background: '#ab47bc',
                width: `${(resStatus.current / resStatus.total * 100).toFixed(0)}%`, transition: 'width 0.5s'
              }} />
            </div>
          )}

          {/* 建模進度 */}
          {genStatus && (
            <div style={{ marginTop: '12px' }}>
              <div style={{ fontSize: '0.9em', color: 'var(--text)', marginBottom: '6px' }}>
                {genStatus.phase}
                {genStatus.total > 0 && `：${genStatus.current} / ${genStatus.total} 格（${Math.round(genStatus.current / genStatus.total * 100)}%）`}
              </div>
              <div style={{ height: '8px', background: 'rgba(255,255,255,0.1)', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: '4px', background: 'var(--accent)',
                  width: genStatus.total > 0 ? `${(genStatus.current / genStatus.total * 100).toFixed(1)}%` : '5%',
                  transition: 'width 0.5s'
                }} />
              </div>
              <div style={{
                marginTop: '10px', padding: '8px 10px', borderRadius: '4px',
                background: 'rgba(211,47,47,0.15)', border: '1px solid rgba(211,47,47,0.5)',
                fontSize: '0.82em', lineHeight: 1.6
              }}>
                ⚠ 建模期間請勿操作 AEDT<br />
                按下 Validate、開啟對話框或執行復原，會使指令永久卡死而必須重來。
              </div>
            </div>
          )}

          {msg && <div style={{ color: 'var(--accent)', fontSize: '0.9em', marginTop: '10px' }}>{msg}</div>}
        </div>
      </div>

      {/* 中央預覽：尚未提供資料前顯示引導畫面 */}
      <div style={{ flex: 1, position: 'relative' }}>
        {results ? (
          <ResultsView data={results} onBack={() => setResults(null)} />
        ) : !dataReady ? (
          <div style={{
            width: '100%', height: '100%', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: '12px',
            background: '#0e121a', color: 'var(--text-muted)', textAlign: 'center', padding: '20px'
          }}>
            <div style={{ fontSize: '3em' }}>📐</div>
            <div style={{ fontSize: '1.2em', color: 'var(--text)' }}>尚未載入資料</div>
            <div style={{ maxWidth: '440px', lineHeight: 1.8 }}>
              操作步驟：<br />
              ①「選擇 Excel / CSV」上傳 phase–Lx 相位資料表，即可看到陣列佈局預覽<br />
              ②「選擇 UnitCell 專案檔」上傳 .aedt / .aedtz（不需先在 AEDT 開啟）<br />
              ③ 按「產生模型」自動在 AEDT 建立完整陣列
            </div>
          </div>
        ) : (
          <Preview2D data={previewData} />
        )}
      </div>
    </div>
  )
}
