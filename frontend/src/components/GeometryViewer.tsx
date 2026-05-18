import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { GeometryParams } from "../types/job";

interface Props {
  jobId: string;
  geometryParams: GeometryParams | null;
  cutPlanes?: Array<{ axis: string; offset: number }>;
  highlightCut?: boolean;
}

function parseBinarySTL(buffer: ArrayBuffer): THREE.BufferGeometry {
  const view = new DataView(buffer);
  const numTriangles = view.getUint32(80, true);
  const positions = new Float32Array(numTriangles * 9);
  const normals = new Float32Array(numTriangles * 9);
  let offset = 84;
  for (let i = 0; i < numTriangles; i++) {
    const nx = view.getFloat32(offset, true);
    const ny = view.getFloat32(offset + 4, true);
    const nz = view.getFloat32(offset + 8, true);
    offset += 12;
    for (let v = 0; v < 3; v++) {
      const base = i * 9 + v * 3;
      positions[base]     = view.getFloat32(offset,      true);
      positions[base + 1] = view.getFloat32(offset + 4,  true);
      positions[base + 2] = view.getFloat32(offset + 8,  true);
      normals[base]     = nx; normals[base + 1] = ny; normals[base + 2] = nz;
      offset += 12;
    }
    offset += 2;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("normal",   new THREE.BufferAttribute(normals,   3));
  return geo;
}

export default function GeometryViewer({ jobId, geometryParams, cutPlanes = [], highlightCut = false }: Props) {
  const mountRef    = useRef<HTMLDivElement>(null);
  // Persistent Three.js state — never torn down unless jobId changes
  const sceneRef    = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef   = useRef<THREE.PerspectiveCamera | null>(null);
  const pipeGroupRef = useRef<THREE.Group | null>(null);   // geometry mesh group
  const cutGroupRef  = useRef<THREE.Group | null>(null);   // cut planes group
  const animRef      = useRef<number>(0);
  const loadedJobRef = useRef<string>("");                  // which jobId is currently rendered

  // ── Init Three.js once per mount ────────────────────────────────────────
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;
    const w = el.clientWidth || 600;
    const h = el.clientHeight || 400;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(0x111827);
    el.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, w / h, 1, 100000);
    camera.position.set(3000, 2000, 4000);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.0);
    dir1.position.set(1, 2, 3);
    scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0x8899ff, 0.4);
    dir2.position.set(-2, -1, -1);
    scene.add(dir2);

    const pipeGroup = new THREE.Group();
    const cutGroup  = new THREE.Group();
    scene.add(pipeGroup);
    scene.add(cutGroup);
    pipeGroupRef.current = pipeGroup;
    cutGroupRef.current  = cutGroup;

    // Orbit
    let dragging = false, prevX = 0, prevY = 0;
    let theta = 0.4, phi = 1.1, radius = 5000;
    const updateCamera = () => {
      camera.position.set(
        radius * Math.sin(phi) * Math.sin(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.cos(theta),
      );
      camera.lookAt(0, 0, 0);
    };
    updateCamera();

    const onDown = (e: MouseEvent) => { dragging = true; prevX = e.clientX; prevY = e.clientY; };
    const onUp   = () => { dragging = false; };
    const onMove = (e: MouseEvent) => {
      if (!dragging) return;
      theta -= (e.clientX - prevX) * 0.005;
      phi    = Math.max(0.1, Math.min(Math.PI - 0.1, phi - (e.clientY - prevY) * 0.005));
      prevX = e.clientX; prevY = e.clientY;
      updateCamera();
    };
    const onWheel = (e: WheelEvent) => {
      radius = Math.max(100, radius * (1 + e.deltaY * 0.001));
      updateCamera();
    };
    el.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("mousemove", onMove);
    el.addEventListener("wheel", onWheel, { passive: true });

    const animate = () => {
      animRef.current = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(animRef.current);
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("mousemove", onMove);
      el.removeEventListener("wheel", onWheel);
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
      sceneRef.current = null;
      rendererRef.current = null;
      loadedJobRef.current = "";
    };
  }, []); // ← only on mount/unmount

  // ── Load STL when jobId changes ─────────────────────────────────────────
  useEffect(() => {
    const pipeGroup = pipeGroupRef.current;
    const camera    = cameraRef.current;
    if (!pipeGroup || !camera || !geometryParams) return;
    if (loadedJobRef.current === jobId) return;   // already loaded this job
    loadedJobRef.current = jobId;

    // Clear previous geometry
    pipeGroup.clear();

    const pipeMat = new THREE.MeshPhongMaterial({
      color: 0x4488cc, specular: 0x224466, shininess: 60, side: THREE.DoubleSide,
    });

    fetch(`/api/jobs/${jobId}/surface`)
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        const geo  = parseBinarySTL(buf);
        const mesh = new THREE.Mesh(geo, pipeMat);
        pipeGroup.add(mesh);

        const box    = new THREE.Box3().setFromObject(pipeGroup);
        const center = box.getCenter(new THREE.Vector3());
        const size   = box.getSize(new THREE.Vector3()).length();
        pipeGroup.position.sub(center);

        camera.near = size * 0.001;
        camera.far  = size * 10;
        // Reposition camera to fit geometry
        const newRadius = size * 0.9;
        camera.position.normalize().multiplyScalar(newRadius);
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
      })
      .catch(() => {
        // Fallback: build primitives from params
        _addFallbackPrimitives(pipeGroup, geometryParams, pipeMat);
        const box    = new THREE.Box3().setFromObject(pipeGroup);
        const center = box.getCenter(new THREE.Vector3());
        pipeGroup.position.sub(center);
      });
  }, [jobId, geometryParams]);

  // ── Update cut planes without reloading STL ──────────────────────────────
  useEffect(() => {
    const cutGroup  = cutGroupRef.current;
    const pipeGroup = pipeGroupRef.current;
    if (!cutGroup) return;

    cutGroup.clear();
    if (!highlightCut || cutPlanes.length === 0) return;

    // Compute pipe size from pipeGroup bounding box for plane sizing
    const box = new THREE.Box3().setFromObject(pipeGroup ?? new THREE.Object3D());
    const size = box.getSize(new THREE.Vector3());
    const planeSize = Math.max(size.x, size.y, size.z, 1500) * 0.8;

    const planeMat = new THREE.MeshBasicMaterial({
      color: 0x2255ff, side: THREE.DoubleSide, transparent: true, opacity: 0.35,
    });
    const edgeMat = new THREE.LineBasicMaterial({ color: 0x4488ff });

    // pipeGroup is shifted by -center, so offset cut planes by same amount
    const groupShift = pipeGroup?.position ?? new THREE.Vector3();

    cutPlanes.forEach((cp, i) => {
      // Branch planes get a distinct orange color
      const isBranch = cp.axis === "branch";
      const color = isBranch ? 0xff6600 : 0x2255ff;
      const mat = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.35 });
      const edgeMat2 = new THREE.LineBasicMaterial({ color: isBranch ? 0xff8833 : 0x4488ff });

      const planeGeo  = new THREE.PlaneGeometry(planeSize, planeSize);
      const planeMesh = new THREE.Mesh(planeGeo, mat);

      if (cp.axis === "branch" && cp.normal && cp.point) {
        // Oblique plane: rotate from default normal (0,0,1) to branch normal
        const target = new THREE.Vector3(...cp.normal).normalize();
        const quat = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1),
          target,
        );
        planeMesh.applyQuaternion(quat);
        planeMesh.position.set(
          cp.point[0] + groupShift.x,
          cp.point[1] + groupShift.y,
          cp.point[2] + groupShift.z,
        );
      } else if (cp.axis === "X") {
        planeMesh.rotation.y = Math.PI / 2;
        planeMesh.position.set(cp.offset + groupShift.x, 0, 0);
      } else if (cp.axis === "Y") {
        planeMesh.rotation.x = Math.PI / 2;
        planeMesh.position.set(0, cp.offset + groupShift.y, 0);
      } else {
        planeMesh.position.set(0, 0, cp.offset + groupShift.z);
      }

      planeMesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(planeGeo), edgeMat2));
      cutGroup.add(planeMesh);
    });
  }, [cutPlanes, highlightCut]);

  if (!geometryParams) {
    return <div className="flex items-center justify-center h-full text-gray-500 text-sm">형상 파싱 중...</div>;
  }

  return <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />;
}

function _addFallbackPrimitives(group: THREE.Group, geo: GeometryParams, mat: THREE.Material) {
  const headerR  = geo.header_pipe.outer_radius * 1000;
  const headerLen = geo.header_pipe.length * 1000;
  const branchR  = geo.branch_pipe.outer_radius * 1000;
  const angleRad = (geo.branch_pipe.angle_deg * Math.PI) / 180;
  const branchLen = branchR * 6;

  const header = new THREE.Mesh(new THREE.CylinderGeometry(headerR, headerR, headerLen, 32), mat);
  header.rotation.z = Math.PI / 2;
  group.add(header);

  const branch = new THREE.Mesh(new THREE.CylinderGeometry(branchR, branchR, branchLen, 32), mat);
  branch.position.set(0, branchLen / 2 * Math.cos(angleRad), branchLen / 2 * Math.sin(angleRad));
  branch.rotation.x = -angleRad;
  group.add(branch);
}
