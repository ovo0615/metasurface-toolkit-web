import React, { useRef, useMemo, useEffect, useState } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader'

// 此工具由虎門科技資深技術工程師 Jeff Hong 洪敬傑提供

interface Preview3DProps {
  data: any | null; 
}

function InstancedElements({ data }: { data: any }) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null)
  const [baseWidth, setBaseWidth] = useState(1)

  useEffect(() => {
    // 載入伺服器上的 unitcell.obj
    const loader = new OBJLoader()
    loader.load('http://127.0.0.1:8010/static/unitcell.obj', (obj) => {
      let geo: THREE.BufferGeometry | null = null
      obj.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          geo = child.geometry
        }
      })
      if (geo) {
        // 計算 bounding box 找出原始模型的 X 寬度
        geo.computeBoundingBox()
        const box = geo.boundingBox
        if (box) {
          setBaseWidth(box.max.x - box.min.x)
          // 將模型中心移至原點，方便進行縮放與旋轉
          geo.center()
        }
        setGeometry(geo)
      }
    }, undefined, (err) => {
      console.error("Failed to load unitcell.obj", err)
    })
  }, [])

  const elements = useMemo(() => {
    return data?.rawElements || []
  }, [data])

  useEffect(() => {
    if (meshRef.current && geometry && elements.length > 0) {
      const dummy = new THREE.Object3D()
      elements.forEach((el: any, i: number) => {
        // el 含有 x, y, size_x, phase 等
        // 算出縮放比例
        const scaleX = baseWidth > 0 ? (el.size_x / baseWidth) : 1
        
        dummy.position.set(el.x, el.y, 0)
        dummy.scale.set(scaleX, 1, 1)
        dummy.updateMatrix()
        meshRef.current!.setMatrixAt(i, dummy.matrix)
      })
      meshRef.current.instanceMatrix.needsUpdate = true
    }
  }, [geometry, elements, baseWidth])

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
