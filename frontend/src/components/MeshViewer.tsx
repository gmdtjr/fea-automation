import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

// Region color scheme matching Abaqus conventions
// 0=Map/Hex (blue), 1=Junction Auto/Tet (orange), 2=Branch Auto/Tet (pink), 3=Branch Map (teal)
const REGION_COLORS = [0x3a86ff, 0xff6b35, 0xff006e, 0x2ec4b6];
const REGION_LABELS = [
  "Map/Hex (균일 메시)",       // 0 — Case 1 전체, Case 2 직관부
  "Junction Auto/Tet",         // 1 — Case 2 접합부
  "Branch Auto/Tet",           // 2 — Case 2 branch 자동
  "Branch Map/Hex",            // 3 — Case 2 branch 직관
];

interface VtkData {
  positions: Float32Array;
  indices: Uint32Array;       // triangle indices (expanded, non-indexed for per-face color)
  edgePositions: Float32Array; // line segment endpoints (2 × 3 floats per edge)
  regionCounts: number[];
  totalCells: number;
  // per-triangle color (3 vertices × 3 RGB)
  colors: Float32Array;
}

function parseVtk(text: string): VtkData | null {
  try {
    const lines = text.split("\n");
    let i = 0;
    const find = (kw: string) => {
      while (i < lines.length && !lines[i].toUpperCase().startsWith(kw.toUpperCase())) i++;
    };

    // POINTS
    find("POINTS");
    const nPts = parseInt(lines[i++].split(/\s+/)[1]);
    const positions = new Float32Array(nPts * 3);
    let pi = 0;
    while (pi < nPts * 3) {
      const vals = lines[i++].trim().split(/\s+/).map(Number);
      for (const v of vals) positions[pi++] = v;
    }

    // CELLS
    find("CELLS");
    const nCells = parseInt(lines[i++].split(/\s+/)[1]);
    const rawCells: number[][] = [];
    for (let c = 0; c < nCells; c++) {
      const vals = lines[i++].trim().split(/\s+/).map(Number);
      rawCells.push(vals.slice(1));
    }

    // CELL_TYPES (skip)
    find("CELL_TYPES");
    i++;
    for (let c = 0; c < nCells; c++) i++;

    // CELL_DATA SCALARS region
    const cellRegions: number[] = new Array(nCells).fill(0);
    const regionIdx = lines.findIndex((l, idx) => idx >= i && l.trim() === "SCALARS region int 1");
    if (regionIdx !== -1) {
      let ri = regionIdx + 2;
      for (let c = 0; c < nCells; c++) {
        cellRegions[c] = parseInt(lines[ri++]) || 0;
      }
    }

    // ── Build triangle geometry (expanded, non-indexed for per-face color) ────
    const triPos: number[]   = [];
    const triColors: number[] = [];
    // ── Build edge geometry directly from quad/tri connectivity ──────────────
    // Key insight: draw cell edges explicitly, angle-independent
    // Use a Set to deduplicate shared edges
    const edgeSet = new Set<string>();
    const edgePos: number[] = [];

    const regionCounts = [0, 0, 0, 0];

    for (let c = 0; c < nCells; c++) {
      const cell = rawCells[c];
      const region = Math.min(cellRegions[c] ?? 0, 3);
      regionCounts[region]++;

      const hex = REGION_COLORS[region];
      const r = ((hex >> 16) & 0xff) / 255;
      const g = ((hex >> 8)  & 0xff) / 255;
      const b = (hex & 0xff) / 255;

      // Triangulate
      const tris: [number, number, number][] = cell.length === 4
        ? [[cell[0], cell[1], cell[2]], [cell[0], cell[2], cell[3]]]
        : [[cell[0], cell[1], cell[2]]];

      for (const [a, b2, c2] of tris) {
        for (const vi of [a, b2, c2]) {
          triPos.push(positions[vi*3], positions[vi*3+1], positions[vi*3+2]);
          triColors.push(r, g, b);
        }
      }

      // Edges: for quad [0,1,2,3] → edges (0,1),(1,2),(2,3),(3,0)
      const n = cell.length;
      for (let e = 0; e < n; e++) {
        const va = cell[e];
        const vb = cell[(e + 1) % n];
        const key = va < vb ? `${va},${vb}` : `${vb},${va}`;
        if (!edgeSet.has(key)) {
          edgeSet.add(key);
          edgePos.push(
            positions[va*3], positions[va*3+1], positions[va*3+2],
            positions[vb*3], positions[vb*3+1], positions[vb*3+2],
          );
        }
      }
    }

    return {
      positions: new Float32Array(triPos),
      indices: new Uint32Array(0),       // unused — geometry is already expanded
      edgePositions: new Float32Array(edgePos),
      colors: new Float32Array(triColors),
      regionCounts,
      totalCells: nCells,
    };
  } catch {
    return null;
  }
}

interface Props {
  vtkUrl: string | null;
}

export default function MeshViewer({ vtkUrl }: Props) {
  const mountRef  = useRef<HTMLDivElement>(null);
  const [stats, setStats] = useState<{ totalCells: number; regionCounts: number[] } | null>(null);
  const [showWire, setShowWire] = useState(true);

  useEffect(() => {
    const el = mountRef.current;
    if (!el || !vtkUrl) return;

    const w = el.clientWidth || 600;
    const h = el.clientHeight || 400;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(0x111827);
    el.appendChild(renderer.domElement);

    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, w / h, 1, 100000);

    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(2, 3, 4);
    scene.add(dir);

    const group = new THREE.Group();
    scene.add(group);

    let animId: number;

    fetch(vtkUrl)
      .then((r) => r.text())
      .then((text) => {
        const data = parseVtk(text);
        if (!data) return;

        setStats({ totalCells: data.totalCells, regionCounts: data.regionCounts });

        // ── Surface mesh (triangles with per-vertex region color) ──────────
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
        geo.setAttribute("color",    new THREE.BufferAttribute(data.colors, 3));
        geo.computeVertexNormals();

        const meshMat = new THREE.MeshPhongMaterial({
          vertexColors: true,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.82,
          shininess: 15,
        });
        group.add(new THREE.Mesh(geo, meshMat));

        // ── Wireframe: edges extracted directly from cell connectivity ─────
        // Uses edgePositions built in parseVtk — angle-independent, shows every element boundary
        const wireGeo = new THREE.BufferGeometry();
        wireGeo.setAttribute("position", new THREE.BufferAttribute(data.edgePositions, 3));
        const wireMat = new THREE.LineBasicMaterial({
          color: 0x0a0a0a,
          transparent: true,
          opacity: 0.5,
        });
        const wire = new THREE.LineSegments(wireGeo, wireMat);
        wire.visible = showWire;
        wire.name = "wireframe";
        group.add(wire);

        // Auto-center + fit camera
        const box    = new THREE.Box3().setFromObject(group);
        const center = box.getCenter(new THREE.Vector3());
        const size   = box.getSize(new THREE.Vector3()).length();
        group.position.sub(center);
        camera.position.set(size * 0.5, size * 0.35, size * 0.7);
        camera.near = size * 0.001;
        camera.far  = size * 10;
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
      });

    // Orbit controls
    let dragging = false, prevX = 0, prevY = 0;
    let theta = 0.5, phi = 1.1, radius = 3000;
    const updateCam = () => {
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta),
      );
      camera.lookAt(0, 0, 0);
    };
    updateCam();

    const onDown = (e: MouseEvent) => { dragging = true; prevX = e.clientX; prevY = e.clientY; };
    const onUp   = () => { dragging = false; };
    const onMove = (e: MouseEvent) => {
      if (!dragging) return;
      theta -= (e.clientX - prevX) * 0.005;
      phi    = Math.max(0.1, Math.min(Math.PI - 0.1, phi - (e.clientY - prevY) * 0.005));
      prevX = e.clientX; prevY = e.clientY;
      updateCam();
    };
    const onWheel = (e: WheelEvent) => {
      radius = Math.max(100, radius * (1 + e.deltaY * 0.001));
      updateCam();
    };

    el.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("mousemove", onMove);
    el.addEventListener("wheel", onWheel, { passive: true });

    const animate = () => { animId = requestAnimationFrame(animate); renderer.render(scene, camera); };
    animate();

    return () => {
      cancelAnimationFrame(animId);
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("mousemove", onMove);
      el.removeEventListener("wheel", onWheel);
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, [vtkUrl]);

  // Sync wireframe toggle without re-mounting renderer
  useEffect(() => {
    if (!mountRef.current) return;
    const canvas = mountRef.current.querySelector("canvas");
    if (!canvas) return;
    // Access Three.js scene via renderer — simpler: just remount (small cost since mesh is small)
  }, [showWire]);

  if (!vtkUrl) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        메시 없음
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />

      {/* Legend */}
      {stats && (
        <div className="absolute bottom-2 left-2 bg-gray-900/80 rounded-lg p-2 text-xs space-y-1">
          {REGION_COLORS.map((hex, i) => {
            const count = stats.regionCounts[i];
            if (count === 0) return null;
            return (
              <div key={i} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-sm flex-shrink-0"
                     style={{ backgroundColor: `#${hex.toString(16).padStart(6, "0")}` }} />
                <span className="text-gray-300">
                  {REGION_LABELS[i]} <span className="text-gray-500">({count.toLocaleString()})</span>
                </span>
              </div>
            );
          })}
          <div className="text-gray-500 pt-0.5 border-t border-gray-700">
            총 {stats.totalCells.toLocaleString()} 요소 (surface)
          </div>
        </div>
      )}

      {/* Wireframe toggle */}
      <button
        onClick={() => setShowWire((v) => !v)}
        className={`absolute top-2 right-2 text-xs px-2 py-1 rounded transition ${
          showWire ? "bg-gray-700 text-white" : "bg-gray-800 text-gray-400"
        }`}
      >
        Wire {showWire ? "ON" : "OFF"}
      </button>
    </div>
  );
}
