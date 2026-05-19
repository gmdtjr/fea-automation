import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

// Region colors: 0=Map/Hex, 1=Junction, 2=Branch Auto, 3=Branch Map
const REGION_COLORS = [0x3a86ff, 0xff6b35, 0xff006e, 0x2ec4b6];
const REGION_LABELS = [
  "Map/Hex (균일 메시)",
  "Junction Auto/Tet",
  "Branch Auto/Tet",
  "Branch Map/Hex",
];

// VTK cell types that are already surface elements (no face extraction needed)
const SURFACE_TYPES = new Set([5, 9]); // Triangle(5), Quad(9)

// Face connectivity tables — local vertex indices per element type
// Ordering is consistent but direction doesn't matter (DoubleSide material)
const TET4_FACES: number[][] = [
  [0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 3, 2],
];
const HEX8_FACES: number[][] = [
  [0, 3, 2, 1], [4, 5, 6, 7],
  [0, 1, 5, 4], [1, 2, 6, 5],
  [2, 3, 7, 6], [3, 0, 4, 7],
];
const WEDGE6_FACES: number[][] = [
  [0, 2, 1], [3, 4, 5],
  [0, 1, 4, 3], [1, 2, 5, 4], [0, 3, 5, 2],
];

function cellFaces(cellType: number, verts: number[]): number[][] {
  const pick = (table: number[][]) => table.map((f) => f.map((i) => verts[i]));
  switch (cellType) {
    case 5:  return [verts];          // Tri
    case 9:  return [verts];          // Quad
    case 10: return pick(TET4_FACES); // Tet4 (C3D4)
    case 24: return pick(TET4_FACES); // Tet10 — corner nodes 0-3 only
    case 12: return pick(HEX8_FACES); // Hex8 (C3D8/C3D8R)
    case 25: return pick(HEX8_FACES); // Hex20 — corner nodes 0-7 only
    case 13: return pick(WEDGE6_FACES);// Wedge6 (C3D6)
    default: return [verts];
  }
}

// Jet colormap: blue → cyan → green → yellow → red
function jetColor(t: number): [number, number, number] {
  t = Math.max(0, Math.min(1, t));
  return [
    Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 3))),
    Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 2))),
    Math.min(1, Math.max(0, 1.5 - Math.abs(4 * t - 1))),
  ];
}

interface VtkData {
  triPositions: Float32Array;
  triColors: Float32Array;
  edgePositions: Float32Array;
  regionCounts: number[];
  totalCells: number;
  isVolume: boolean;
  misesRange: [number, number] | null;
}

function parseVtk(text: string): VtkData | null {
  try {
    const lines = text.split("\n");
    let i = 0;
    const advance = (kw: string) => {
      while (i < lines.length && !lines[i].toUpperCase().startsWith(kw.toUpperCase())) i++;
    };

    // POINTS
    advance("POINTS");
    const nPts = parseInt(lines[i++].split(/\s+/)[1]);
    const pts = new Float32Array(nPts * 3);
    let pi = 0;
    while (pi < nPts * 3) {
      for (const v of lines[i++].trim().split(/\s+/).map(Number)) pts[pi++] = v;
    }

    // CELLS
    advance("CELLS");
    const nCells = parseInt(lines[i++].split(/\s+/)[1]);
    const rawCells: number[][] = [];
    for (let c = 0; c < nCells; c++) {
      const vals = lines[i++].trim().split(/\s+/).map(Number);
      rawCells.push(vals.slice(1));
    }

    // CELL_TYPES (previously skipped — now parsed)
    advance("CELL_TYPES");
    i++;
    const cellTypes: number[] = [];
    for (let c = 0; c < nCells; c++) cellTypes.push(parseInt(lines[i++].trim()) || 9);
    const postTypesLine = i;

    const isVolume = cellTypes.some((t) => !SURFACE_TYPES.has(t));

    // SCALARS: region int (mock) or mises float (real Abaqus)
    const cellRegions = new Int32Array(nCells);
    const cellMises = new Float64Array(nCells);
    let hasMises = false;

    const rIdx = lines.findIndex(
      (l, idx) => idx >= postTypesLine && /^SCALARS\s+region/i.test(l.trim())
    );
    if (rIdx !== -1) {
      let ri = rIdx + 2; // skip LOOKUP_TABLE line
      for (let c = 0; c < nCells; c++) cellRegions[c] = parseInt(lines[ri++]) || 0;
    }

    const mIdx = lines.findIndex(
      (l, idx) => idx >= postTypesLine && /^SCALARS\s+mises/i.test(l.trim())
    );
    if (mIdx !== -1) {
      hasMises = true;
      let ri = mIdx + 2;
      for (let c = 0; c < nCells; c++) cellMises[c] = parseFloat(lines[ri++]) || 0;
    }

    let misesMin = 0, misesMax = 0;
    if (hasMises) {
      misesMin = Infinity; misesMax = -Infinity;
      for (let c = 0; c < nCells; c++) {
        if (cellMises[c] < misesMin) misesMin = cellMises[c];
        if (cellMises[c] > misesMax) misesMax = cellMises[c];
      }
    }

    // Region counts (per cell, used for legend)
    const regionCounts = [0, 0, 0, 0];
    for (let c = 0; c < nCells; c++) regionCounts[Math.min(cellRegions[c], 3)]++;

    // ── External face extraction ─────────────────────────────────────────────
    // Each face is keyed by sorted vertex set.
    // Volumetric: internal faces appear twice (count=2) → filter out.
    // Surface: each cell is its own face (count=1 always).
    const faceMap = new Map<string, {
      verts: number[]; count: number; region: number; mises: number;
    }>();

    for (let c = 0; c < nCells; c++) {
      const faces = cellFaces(cellTypes[c], rawCells[c]);
      const region = Math.min(cellRegions[c], 3);
      const mises = cellMises[c];
      for (const face of faces) {
        const key = [...face].sort((a, b) => a - b).join(",");
        const e = faceMap.get(key);
        if (e) { e.count++; }
        else   { faceMap.set(key, { verts: face, count: 1, region, mises }); }
      }
    }

    // ── Triangulate external faces + collect wireframe edges ─────────────────
    const triPos: number[] = [];
    const triCol: number[] = [];
    const edgeSet = new Set<string>();
    const edgePos: number[] = [];

    for (const { verts, count, region, mises } of faceMap.values()) {
      // Skip internal faces for volumetric meshes
      if (isVolume && count !== 1) continue;

      // Color: jet colormap for mises, region palette for mock
      let r: number, g: number, b: number;
      if (hasMises) {
        const t = misesMax > misesMin ? (mises - misesMin) / (misesMax - misesMin) : 0.5;
        [r, g, b] = jetColor(t);
      } else {
        const hex = REGION_COLORS[region];
        r = ((hex >> 16) & 0xff) / 255;
        g = ((hex >> 8)  & 0xff) / 255;
        b = (hex & 0xff) / 255;
      }

      // Fan triangulation (works for tri and quad faces)
      for (let t = 1; t < verts.length - 1; t++) {
        for (const vi of [verts[0], verts[t], verts[t + 1]]) {
          triPos.push(pts[vi * 3], pts[vi * 3 + 1], pts[vi * 3 + 2]);
          triCol.push(r, g, b);
        }
      }

      // Edges of this face (deduplicated globally)
      for (let e = 0; e < verts.length; e++) {
        const va = verts[e], vb = verts[(e + 1) % verts.length];
        const ek = va < vb ? `${va},${vb}` : `${vb},${va}`;
        if (!edgeSet.has(ek)) {
          edgeSet.add(ek);
          edgePos.push(
            pts[va * 3], pts[va * 3 + 1], pts[va * 3 + 2],
            pts[vb * 3], pts[vb * 3 + 1], pts[vb * 3 + 2],
          );
        }
      }
    }

    return {
      triPositions: new Float32Array(triPos),
      triColors: new Float32Array(triCol),
      edgePositions: new Float32Array(edgePos),
      regionCounts,
      totalCells: nCells,
      isVolume,
      misesRange: hasMises ? [misesMin, misesMax] : null,
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
  const wireRef   = useRef<THREE.LineSegments | null>(null);
  const showWireRef = useRef(true);
  const [stats, setStats] = useState<{
    totalCells: number;
    regionCounts: number[];
    isVolume: boolean;
    misesRange: [number, number] | null;
  } | null>(null);
  const [showWire, setShowWire] = useState(true);

  // Wireframe toggle: update directly without re-parsing VTK
  useEffect(() => {
    showWireRef.current = showWire;
    if (wireRef.current) wireRef.current.visible = showWire;
  }, [showWire]);

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

        setStats({
          totalCells: data.totalCells,
          regionCounts: data.regionCounts,
          isVolume: data.isVolume,
          misesRange: data.misesRange,
        });

        // Surface mesh
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(data.triPositions, 3));
        geo.setAttribute("color",    new THREE.BufferAttribute(data.triColors, 3));
        geo.computeVertexNormals();
        group.add(new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
          vertexColors: true,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.82,
          shininess: 15,
        })));

        // Wireframe (edges from external faces only)
        const wireGeo = new THREE.BufferGeometry();
        wireGeo.setAttribute("position", new THREE.BufferAttribute(data.edgePositions, 3));
        const wire = new THREE.LineSegments(wireGeo, new THREE.LineBasicMaterial({
          color: 0x0a0a0a,
          transparent: true,
          opacity: 0.5,
        }));
        wire.visible = showWireRef.current;
        wireRef.current = wire;
        group.add(wire);

        // Fit camera to mesh
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
      wireRef.current = null;
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("mousemove", onMove);
      el.removeEventListener("wheel", onWheel);
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, [vtkUrl]);

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

      {stats && (
        <div className="absolute bottom-2 left-2 bg-gray-900/80 rounded-lg p-2 text-xs space-y-1 max-w-52">
          {/* Region legend — mock VTK (no mises) */}
          {!stats.misesRange &&
            REGION_COLORS.map((hex, i) => {
              const count = stats.regionCounts[i];
              if (count === 0) return null;
              return (
                <div key={i} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-sm flex-shrink-0"
                    style={{ backgroundColor: `#${hex.toString(16).padStart(6, "0")}` }}
                  />
                  <span className="text-gray-300">
                    {REGION_LABELS[i]}{" "}
                    <span className="text-gray-500">({count.toLocaleString()})</span>
                  </span>
                </div>
              );
            })}

          {/* Mises colorbar — real Abaqus VTK */}
          {stats.misesRange && (
            <>
              <div className="text-gray-400 font-medium">Von Mises (MPa)</div>
              <div className="flex items-center gap-1.5">
                <span className="text-blue-400 tabular-nums">
                  {stats.misesRange[0].toFixed(1)}
                </span>
                <div
                  className="flex-1 h-2.5 rounded"
                  style={{
                    background:
                      "linear-gradient(to right,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)",
                  }}
                />
                <span className="text-red-400 tabular-nums">
                  {stats.misesRange[1].toFixed(1)}
                </span>
              </div>
            </>
          )}

          <div className="text-gray-500 pt-0.5 border-t border-gray-700">
            {stats.totalCells.toLocaleString()} 요소
            {" "}({stats.isVolume ? "volumetric" : "surface"})
          </div>
        </div>
      )}

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
