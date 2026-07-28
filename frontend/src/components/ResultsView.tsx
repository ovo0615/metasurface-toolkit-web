// 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供
import { useState } from 'react'
import type { ResultsStatus } from '../api'

interface Props {
  data: ResultsStatus
  onBack: () => void
  onRefresh: () => void
  /** 仍在讀取中的階段文字（漸進顯示時用）；已完成則為 null */
  loadingPhase?: string | null
}

const TITLES: Record<string, { name: string; hint: string }> = {
  cuts: { name: '遠場方向圖（二維切面）', hint: 'phi = 0°／90° 兩個主平面。看形狀與相對電平：主瓣位置、旁瓣高低' },
  pattern3d: { name: '三維立體方向圖', hint: '上半部為反射波束，下半部為前向散射' },
  efield: { name: '表面電場分佈', hint: '最上層金屬的 |E|，可看出相位補償是否正常' },
}
const ORDER = ['cuts', 'pattern3d', 'efield']

export default function ResultsView({ data, onBack, onRefresh, loadingPhase }: Props) {
  const [zoom, setZoom] = useState<string | null>(null)
  const images = data.images || {}
  const s = data.summary || {}
  const shown = ORDER.filter(k => images[k])

  const card: React.CSSProperties = {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid var(--border-light)',
    borderRadius: '6px',
    padding: '12px',
  }

  // 旁瓣取兩切面中較差（較高）者評分；低於 -10 dB 屬正常
  const slls = [s.phi0?.sll_db, s.phi90?.sll_db].filter((x: any) => typeof x === 'number')
  const worstSll = slls.length ? Math.max(...slls) : null
  const fmtBw = (m: any) => (m && m.bw_3db != null ? `${m.bw_3db}°` : '—（過寬）')

  return (
    <div style={{ width: '100%', height: '100%', overflowY: 'auto', background: '#0e121a', padding: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <h3 style={{ margin: 0, color: 'var(--accent)' }}>模擬結果</h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={onRefresh}
            disabled={!!loadingPhase}
            title="重新從 AEDT 讀取最新結果（會重跑，較耗時）"
            style={{
              padding: '6px 14px', borderRadius: '4px',
              cursor: loadingPhase ? 'not-allowed' : 'pointer', opacity: loadingPhase ? 0.5 : 1,
              border: '1px solid var(--border-light)', background: 'transparent', color: 'var(--text-muted)'
            }}
          >
            ⟳ 重新讀取
          </button>
          <button
            onClick={onBack}
            style={{
              padding: '6px 14px', borderRadius: '4px', cursor: 'pointer',
              border: '1px solid var(--border-light)', background: 'transparent', color: 'var(--text-main)'
            }}
          >
            ← 返回陣列佈局
          </button>
        </div>
      </div>

      {loadingPhase && (
        <div style={{
          marginBottom: '16px', padding: '10px 12px', borderRadius: '6px',
          background: 'rgba(171,71,188,0.15)', border: '1px solid rgba(171,71,188,0.5)',
          fontSize: '0.88em', color: 'var(--text-main)'
        }}>
          ⏳ 仍在讀取：{loadingPhase}　— 以下為已完成的項目，其餘完成後會自動出現。
        </div>
      )}

      {/* 波束品質指標 */}
      {s.rcs_peak_dbsm !== undefined && (
        <div style={{ ...card, marginBottom: '16px' }}>
          <div style={{ fontSize: '0.85em', color: 'var(--text-muted)', marginBottom: '10px' }}>波束品質指標</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '20px 28px', fontVariantNumeric: 'tabular-nums' }}>
            <Stat label="設計方向" value={`θ ${s.design_theta}° / φ ${s.design_phi}°`} />
            <Stat
              label="實際波束方向"
              value={`θ ${s.reflect_theta}°`}
              tone={s.theta_error != null && s.theta_error <= (s.resolution ?? 2) ? 'good' : s.theta_error != null ? 'warn' : undefined}
              sub={s.theta_error != null ? `誤差 ${s.theta_error}°（解析度 ${s.resolution ?? 2}°）` : undefined}
            />
            <Stat label="峰值 RCS" value={`${s.rcs_peak_dbsm} dBsm`} sub="等效反射面積（絕對值，可跨設計比較）" />
            <Stat
              label="3dB 波束寬"
              value={`${fmtBw(s.phi0)} / ${fmtBw(s.phi90)}`}
              sub="phi = 0° / 90°；口徑越大越窄"
            />
            <Stat
              label="旁瓣電平"
              value={worstSll != null ? `${worstSll} dB` : '—'}
              tone={worstSll != null ? (worstSll <= -10 ? 'good' : 'warn') : undefined}
              sub="相對主瓣；低於 −10 dB 屬正常"
            />
            <Stat
              label="口徑"
              value={`${s.aperture_lambda} λ`}
              sub={`理論指向性上限約 ${s.directivity_theory_db} dBi`}
            />
          </div>
          <div style={{ fontSize: '0.78em', color: 'var(--text-muted)', marginTop: '12px', lineHeight: 1.7 }}>
            平面波照射下無法定義增益（無輸入功率），故以 RCS 表示絕對強度。
            口徑小於 2λ 時波束本來就寬、指向也不精確——判讀時請先對照「口徑」欄位。
          </div>
          {s.beam_note && <div style={{ color: '#ff9800', fontSize: '0.85em', marginTop: '8px' }}>{s.beam_note}</div>}
          {s.efield_note && <div style={{ color: '#ff9800', fontSize: '0.85em', marginTop: '8px' }}>{s.efield_note}</div>}
        </div>
      )}

      {/* 結果圖 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '16px' }}>
        {shown.map(k => (
          <div key={k} style={card}>
            <div style={{ color: 'var(--text-main)', marginBottom: '2px' }}>{TITLES[k].name}</div>
            <div style={{ fontSize: '0.78em', color: 'var(--text-muted)', marginBottom: '10px' }}>{TITLES[k].hint}</div>
            <img
              src={images[k]}
              alt={TITLES[k].name}
              onClick={() => setZoom(images[k])}
              style={{ width: '100%', borderRadius: '4px', background: '#fff', cursor: 'zoom-in', display: 'block' }}
            />
          </div>
        ))}
      </div>

      {shown.length === 0 && (
        <div style={{ color: 'var(--text-muted)' }}>沒有產生任何結果圖，請確認陣列已在 AEDT 中完成求解。</div>
      )}

      {/* 點圖放大 */}
      {zoom && (
        <div
          onClick={() => setZoom(null)}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 50,
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out', padding: '30px'
          }}
        >
          <img src={zoom} alt="放大檢視" style={{ maxWidth: '100%', maxHeight: '100%', background: '#fff', borderRadius: '4px' }} />
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'warn' }) {
  const color = tone === 'good' ? '#2ea043' : tone === 'warn' ? '#ff9800' : 'var(--text-main)'
  return (
    <div style={{ minWidth: '150px' }}>
      <div style={{ fontSize: '0.78em', color: 'var(--text-muted)', marginBottom: '2px' }}>{label}</div>
      <div style={{ fontSize: '1.1em', color }}>{value}</div>
      {sub && <div style={{ fontSize: '0.72em', color: 'var(--text-muted)', marginTop: '2px' }}>{sub}</div>}
    </div>
  )
}
