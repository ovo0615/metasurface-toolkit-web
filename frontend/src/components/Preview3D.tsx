import { useRef, useMemo, useEffect, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import * as THREE from 'three'
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js'

// 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

interface Preview3DProps {
  data: any | null; 
}

function InstancedElements({ data }: { data: any }) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null)
  const [baseWidth, setBaseWidth] = useState(1)
  const [loadError, setLoadError] = useState("")

  useEffect(() => {
    const loader = new OBJLoader()
    const url = '/static/unitcell.obj?t=' + Date.now()  // 經由 Vite proxy 轉發至後端
    loader.load(url, (obj: THREE.Group) => {
      // 合併所有 Mesh (如果有多個 part)
      const geometries: THREE.BufferGeometry[] = []
      obj.traverse((child: THREE.Object3D) => {
        if (child instanceof THREE.Mesh) {
          // 確保 clone 以免被原物件綁定
          geometries.push(child.geometry.clone())
        }
      })

      import('three/addons/utils/BufferGeometryUtils.js').then(({ mergeGeometries }) => {
        if (geometries.length > 0) {
          const geo = geometries.length === 1 ? geometries[0] : mergeGeometries(geometries)
          if (!geo) {
            setLoadError("合併模型幾何失敗。")
            return
          }
          geo.computeBoundingBox()
          const box = geo.boundingBox
          if (box) {
            setBaseWidth(box.max.x - box.min.x)
            geo.center()
          }
          setGeometry(geo)
        } else {
          setLoadError("模型中沒有找到可用的幾何網格 (Mesh)。")
        }
      })
    }, undefined, (err: unknown) => {
      console.error("Failed to load unitcell.obj", err)
      setLoadError("讀取 3D 模型失敗。")
    })
  }, [])

  const elements = useMemo(() => {
    return data?.rawElements || []
  }, [data])

  useEffect(() => {
    if (meshRef.current && geometry && elements.length > 0) {
      const dummy = new THREE.Object3D()
      elements.forEach((el: any, i: number) => {
        // 依 Lx 等比縮放 X 與 Y（原始設計 Ly = Lx），Z 為金屬厚度維持不變
        const scale = baseWidth > 0 ? (el.size_x / baseWidth) : 1

        dummy.position.set(el.x, el.y, 0)
        dummy.scale.set(scale, scale, 1)
        dummy.updateMatrix()
        meshRef.current!.setMatrixAt(i, dummy.matrix)
      })
      meshRef.current.instanceMatrix.needsUpdate = true
    }
  }, [geometry, elements, baseWidth])

  if (loadError) return <Html center><div style={{color:'red'}}>{loadError}</div></Html>
  if (!geometry || elements.length === 0) return null

  return (
    <instancedMesh ref={meshRef} args={[geometry, undefined, elements.length]}>
      <meshStandardMaterial color="#c0c0c0" metalness={0.8} roughness={0.2} />
    </instancedMesh>
  )
}

function Substrate({ bounds }: { bounds: any }) {
  if (!bounds) return null
  const w = bounds.max[0] - bounds.min[0]
  const h = bounds.max[1] - bounds.min[1]
  const cx = (bounds.max[0] + bounds.min[0]) / 2
  const cy = (bounds.max[1] + bounds.min[1]) / 2

  return (
    <mesh position={[cx, cy, -1]}>
      <boxGeometry args={[w, h, 2]} />
      <meshStandardMaterial color="#3a5f5f" roughness={0.8} />
    </mesh>
  )
}

export default function Preview3D({ data }: Preview3DProps) {
  const [camPos, setCamPos] = useState<[number, number, number]>([0, 0, 100])

  useEffect(() => {
    if (data && data.bounds) {
      const w = data.bounds.max[0] - data.bounds.min[0]
      const h = data.bounds.max[1] - data.bounds.min[1]
      const maxDim = Math.max(w, h)
      setCamPos([0, 0, maxDim * 1.5])
    }
  }, [data])

  return (
    <div style={{ width: '100%', height: '100%', background: '#0e121a' }}>
      <Canvas camera={{ position: camPos, fov: 45, up: [0, 0, 1] }}>
        <ambientLight intensity={0.5} />
        <directionalLight position={[100, 100, 200]} intensity={1.5} />
        <directionalLight position={[-100, -100, 200]} intensity={0.5} />
        
        <InstancedElements data={data} />
        <Substrate bounds={data?.bounds} />

        <OrbitControls makeDefault />
        <gridHelper args={[200, 50, '#555555', '#222222']} rotation={[Math.PI/2, 0, 0]} />
      </Canvas>
    </div>
  )
}
