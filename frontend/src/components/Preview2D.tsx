import React, { useRef, useState, useEffect, useCallback } from 'react'

// 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

export interface PreviewData {
  layers: Record<string, any[]>
  layer_colors?: Record<string, number[]>
  layer_order?: string[]
  bounds: { min: [number, number]; max: [number, number] }
}

interface Preview2DProps {
  data: PreviewData | null
}

const BG_COLOR = '#0e121a'
const FALLBACK_PALETTE = ['#ff3b30', '#00e676', '#ffd600', '#00b0ff', '#e040fb', '#ff9100']

export default function Preview2D({ data }: Preview2DProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const [isDragging, setIsDragging] = useState(false)
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 })

  // ── 自動縮放至全板 ──
  const fitView = useCallback(() => {
    if (!data || !containerRef.current) return
    const { min, max } = data.bounds
    const cW = max[0] - min[0], cH = max[1] - min[1]
    if (cW <= 0 || cH <= 0) return
    const w = containerRef.current.clientWidth
    const h = containerRef.current.clientHeight
    const s = Math.min(w * 0.85 / cW, h * 0.85 / cH)
    const cx = (min[0] + max[0]) / 2, cy = (min[1] + max[1]) / 2
    setTransform({ x: w / 2 - cx * s, y: -h / 2 + cy * s, scale: s })
  }, [data])

  useEffect(() => { fitView() }, [data, fitView])

  // ── 繪圖 ──
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const cont = containerRef.current
    if (!canvas || !cont || !data) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rect = cont.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.scale(dpr, dpr)
    canvas.style.width = `${rect.width}px`
    canvas.style.height = `${rect.height}px`

    ctx.fillStyle = BG_COLOR
    ctx.fillRect(0, 0, rect.width, rect.height)

    ctx.save()
    // 將原點移至左下角，並反轉 Y 軸
    ctx.translate(transform.x, transform.y + rect.height)
    ctx.scale(transform.scale, -transform.scale)

    const layerOrder = data.layer_order || Object.keys(data.layers)
    for (const layerName of layerOrder) {
      const prims = data.layers[layerName]
      if (!prims) continue

      let color = FALLBACK_PALETTE[0]
      if (data.layer_colors && data.layer_colors[layerName]) {
        const c = data.layer_colors[layerName]
        color = `rgb(${c[0]},${c[1]},${c[2]})`
      }

      ctx.fillStyle = color
      ctx.strokeStyle = color

      prims.forEach(prim => {
        if (prim.kind === 'rect') {
          ctx.fillRect(prim.x, prim.y, prim.w, prim.h)
        } else if (prim.kind === 'polygon' && prim.points) {
          ctx.beginPath()
          ctx.moveTo(prim.points[0][0], prim.points[0][1])
          for (let i = 1; i < prim.points.length; i++) ctx.lineTo(prim.points[i][0], prim.points[i][1])
          ctx.closePath()
          ctx.fill()
        }
      })
    }
    ctx.restore()
  }, [data, transform])

  useEffect(() => { drawCanvas() }, [drawCanvas])

  useEffect(() => {
    const cont = containerRef.current
    if (!cont) return
    const obs = new ResizeObserver(() => drawCanvas())
    obs.observe(cont)
    return () => obs.disconnect()
  }, [drawCanvas])

  // ── 滑鼠事件 ──
  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const f = Math.exp(-e.deltaY * 0.001)
    const r = canvasRef.current!.getBoundingClientRect()
    const mx = e.clientX - r.left, my = e.clientY - r.top
    setTransform(prev => ({ x: mx - (mx - prev.x) * f, y: my - (my - prev.y) * f, scale: prev.scale * f }))
  }
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true)
    setDragStart({ x: e.clientX - transform.x, y: e.clientY - transform.y })
  }
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    setTransform(prev => ({ ...prev, x: e.clientX - dragStart.x, y: e.clientY - dragStart.y }))
  }
  const handleMouseUp = () => setIsDragging(false)

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <canvas ref={canvasRef} style={{ cursor: isDragging ? 'grabbing' : 'grab' }} />
      <button 
        onClick={(e) => { e.stopPropagation(); fitView(); }} 
        className="premium-btn" 
        style={{ position: 'absolute', bottom: '20px', right: '20px', background: 'rgba(255,255,255,0.1)', padding: '5px 15px', backdropFilter: 'blur(10px)' }}
      >
        Fit All
      </button>
    </div>
  )
}
