import {
  Component,
  Suspense,
  useMemo,
  useRef,
  useEffect,
  useState,
} from "react";
import type { ReactNode } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Line, useTexture } from "@react-three/drei";
import * as THREE from "three";
import type { Replay } from "../lib/types";
import { CLASS_COLORS, framePair } from "../lib/model";

export interface GlobeProps {
  run: Replay;
  time: number;
  selected: number | null;
  onSelect: (id: number) => void;
  flow: number;
  links: boolean;
  orbits: boolean;
  rotate: boolean;
  presentation: boolean;
  placeStation?: (lat: number, lon: number) => void;
  flat?: boolean;
  reset: number;
  focusPath?: boolean;
}
const R = 6371;
const vector = (p: number[]) =>
  new THREE.Vector3(p[0] / R, p[2] / R, -p[1] / R);
class SceneBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? this.props.fallback : this.props.children;
  }
}
function Earth({ placeStation }: Pick<GlobeProps, "placeStation">) {
  const day = useTexture("/assets/earth-day.jpg"),
    night = useTexture("/assets/earth-night.png");
  day.colorSpace = THREE.SRGBColorSpace;
  night.colorSpace = THREE.SRGBColorSpace;
  return (
    <>
      <mesh
        onDoubleClick={(e) => {
          if (placeStation) {
            e.stopPropagation();
            const p = e.point.clone().normalize();
            placeStation(
              (Math.asin(p.y) * 180) / Math.PI,
              (Math.atan2(-p.z, p.x) * 180) / Math.PI,
            );
          }
        }}
      >
        <sphereGeometry args={[1, 64, 48]} />
        <meshPhongMaterial
          map={day}
          emissiveMap={night}
          emissive="#9ec8e5"
          emissiveIntensity={0.65}
          specular="#1b3a47"
          shininess={9}
          color="#a6bcc6"
        />
      </mesh>
      <mesh scale={1.015}>
        <sphereGeometry args={[1, 64, 48]} />
        <shaderMaterial
          transparent
          side={THREE.BackSide}
          depthWrite={false}
          uniforms={{ glow: { value: new THREE.Color("#3088b6") } }}
          vertexShader="varying vec3 vNormal; varying vec3 vView; void main(){ vec4 p=modelViewMatrix*vec4(position,1.0); vNormal=normalize(normalMatrix*normal);vView=normalize(-p.xyz);gl_Position=projectionMatrix*p;}"
          fragmentShader="uniform vec3 glow; varying vec3 vNormal; varying vec3 vView; void main(){float rim=pow(1.0-abs(dot(normalize(vNormal),normalize(vView))),3.0);gl_FragColor=vec4(glow,rim*0.8);}"
        />
      </mesh>
    </>
  );
}
function Satellites({ run, time, selected, onSelect }: GlobeProps) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const color = useMemo(() => new THREE.Color(), []);
  useFrame(() => {
    if (!mesh.current) return;
    const [a, b, t] = framePair(run, time);
    run.nodes.forEach((node, i) => {
      const p = a.positions[i];
      if (!p) return;
      const to = b.positions[i] ?? p;
      dummy.position.set(
        (p[0] + (to[0] - p[0]) * t) / R,
        (p[2] + (to[2] - p[2]) * t) / R,
        -(p[1] + (to[1] - p[1]) * t) / R,
      );
      dummy.scale.setScalar(
        node.id === selected ? 0.014 : node.kind === "ground" ? 0.009 : 0.0045,
      );
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(i, dummy.matrix);
      mesh.current!.setColorAt(
        i,
        color.set(
          node.id === selected
            ? "#ffffff"
            : node.kind === "ground"
              ? "#e6b970"
              : "#9cd9db",
        ),
      );
    });
    mesh.current.instanceMatrix.needsUpdate = true;
    if (mesh.current.instanceColor)
      mesh.current.instanceColor.needsUpdate = true;
  });
  return (
    <instancedMesh
      ref={mesh}
      args={[undefined, undefined, run.nodes.length]}
      onClick={(e) => {
        e.stopPropagation();
        if (e.instanceId !== undefined) onSelect(e.instanceId);
      }}
    >
      <icosahedronGeometry args={[1, 1]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}
function Network({ run, time, flow, selected, links, focusPath }: GlobeProps) {
  const [a, b, t] = framePair(run, time);
  const current = a.routes.find((r) => r.id === flow);
  const positions = a.positions.map((p, i) =>
    vector(p).lerp(vector(b.positions[i] ?? p), t),
  );
  const pathSet = new Set(current?.path ?? []);
  const chosen = pathSet;
  const data = useMemo(() => {
    const points: number[] = [];
    const colors: number[] = [];
    a.links.forEach((link) => {
      if (!positions[link.a] || !positions[link.b]) return;
      // In focusPath mode, only draw links that are on the active route path
      if (focusPath && !(pathSet.has(link.a) && pathSet.has(link.b))) return;
      const isGround =
        run.nodes[link.a]?.kind === "ground" ||
        run.nodes[link.b]?.kind === "ground";
      const relevant =
        selected !== null && (link.a === selected || link.b === selected);
      const c = new THREE.Color(
        relevant ? "#e4c08a" : isGround ? "#426b72" : "#28505b",
      );
      points.push(
        ...positions[link.a].toArray(),
        ...positions[link.b].toArray(),
      );
      colors.push(...c.toArray(), ...c.toArray());
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(points, 3),
    );
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    return geometry;
  }, [a, b, t, selected, run.nodes, focusPath]);
  useEffect(() => () => data.dispose(), [data]);
  return (
    <>
      {links && (
        <lineSegments geometry={data}>
          <lineBasicMaterial
            vertexColors
            transparent
            opacity={0.36}
            depthWrite={false}
          />
        </lineSegments>
      )}
      {a.routes.map((r) =>
        r.id === flow || r.path.length < 2 ? null : (
          <Line
            key={`route-${r.id}`}
            points={r.path.filter((i) => positions[i]).map((i) => positions[i])}
            color={CLASS_COLORS[r.flow_type]}
            lineWidth={0.8}
            transparent
            opacity={0.25}
          />
        ),
      )}
      {current && current.path.length > 1 && (
        <Line
          points={current.path
            .filter((i) => positions[i])
            .map((i) => positions[i])}
          color={CLASS_COLORS[current.flow_type]}
          lineWidth={2.2}
          transparent
          opacity={0.95}
        />
      )}{" "}
      {[...chosen]
        .filter((i) => positions[i])
        .map((i) => (
          <mesh key={i} position={positions[i]}>
            <sphereGeometry args={[0.007, 10, 8]} />
            <meshBasicMaterial color="#e4fff6" />
          </mesh>
        ))}
    </>
  );
}
function OrbitTraces({ run, time }: Pick<GlobeProps, "run" | "time">) {
  const [a] = framePair(run, time);
  const groups = new Map<string, THREE.Vector3[]>();
  run.nodes.forEach((n, i) => {
    if (n.kind !== "satellite" || !a.positions[i]) return;
    const plane = n.name.split("-")[1] ?? "0";
    if (!groups.has(plane)) groups.set(plane, []);
    groups.get(plane)!.push(vector(a.positions[i]));
  });
  return (
    <>
      {[...groups]
        .filter(([, points]) => points.length > 2)
        .map(([name, points]) => (
          <Line
            key={name}
            points={[...points, points[0]]}
            color="#397182"
            transparent
            opacity={0.1}
            lineWidth={0.6}
          />
        ))}
    </>
  );
}
function NodeLabel({ name, point }: { name: string; point: THREE.Vector3 }) {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 512;
    canvas.height = 96;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#0c1a23dd";
    ctx.fillRect(1, 1, 510, 94);
    ctx.strokeStyle = "#56867e";
    ctx.lineWidth = 3;
    ctx.strokeRect(2, 2, 508, 92);
    ctx.fillStyle = "#b8e9df";
    ctx.font = '36px "IBM Plex Mono",monospace';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(name, 256, 48);
    const t = new THREE.CanvasTexture(canvas);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [name]);
  useEffect(() => () => texture.dispose(), [texture]);
  return (
    <sprite
      position={point}
      scale={[0.58, 0.109, 1]}
      center={new THREE.Vector2(0.5, -0.25)}
    >
      <spriteMaterial map={texture} transparent depthWrite={false} />
    </sprite>
  );
}
function Selection({
  run,
  time,
  selected,
}: Pick<GlobeProps, "run" | "time" | "selected">) {
  if (selected === null) return null;
  const [a] = framePair(run, time);
  const p = a.positions[selected];
  if (!p) return null;
  return (
    <NodeLabel
      name={run.nodes[selected]?.name ?? "Selected node"}
      point={vector(p)}
    />
  );
}
function Stars() {
  const positions = useMemo(() => {
    let s = 710;
    const random = () => {
      s = (s * 16807) % 2147483647;
      return s / 2147483647;
    };
    const p = [];
    for (let i = 0; i < 1000; i++) {
      const a = random() * Math.PI * 2,
        z = random() * 2 - 1,
        r = 14;
      const f = Math.sqrt(1 - z * z);
      p.push(r * f * Math.cos(a), r * z, r * f * Math.sin(a));
    }
    return new Float32Array(p);
  }, []);
  return (
    <points>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.012}
        color="#9bb3c5"
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  );
}
function FlatMap({ run, time, selected, onSelect }: GlobeProps) {
  const [a] = framePair(run, time);
  const project = (p: number[]) => [
    180 + (Math.atan2(p[1], p[0]) * 180) / Math.PI,
    90 - (Math.asin(p[2] / Math.hypot(...p)) * 180) / Math.PI,
  ];
  return (
    <div className="flat-map">
      <span className="eyebrow">ORBITAL MAP · ECEF / 2D</span>
      <svg
        viewBox="0 0 360 180"
        role="img"
        aria-label="Two-dimensional satellite map"
      >
        {[30, 60, 90, 120, 150].map((y) => (
          <line key={y} x1="0" x2="360" y1={y} y2={y} stroke="#233641" />
        ))}
        {[60, 120, 180, 240, 300].map((x) => (
          <line key={x} x1={x} x2={x} y1="0" y2="180" stroke="#233641" />
        ))}
        {a.links.map((l) => {
          if (!a.positions[l.a] || !a.positions[l.b]) return null;
          const p = project(a.positions[l.a]),
            q = project(a.positions[l.b]);
          return Math.abs(p[0] - q[0]) < 180 ? (
            <line
              key={l.id}
              x1={p[0]}
              y1={p[1]}
              x2={q[0]}
              y2={q[1]}
              stroke="#2b535c"
              strokeWidth=".3"
            />
          ) : null;
        })}
        {run.nodes.map((n, i) => {
          if (!a.positions[i]) return null;
          const [x, y] = project(a.positions[i]);
          return (
            <circle
              key={n.id}
              cx={x}
              cy={y}
              r={n.kind === "ground" ? 2 : 1}
              fill={
                selected === n.id
                  ? "#fff"
                  : n.kind === "ground"
                    ? "#e0b678"
                    : "#9de5d6"
              }
              onClick={() => onSelect(n.id)}
            >
              <title>{n.name}</title>
            </circle>
          );
        })}
      </svg>
      <p>Browser-friendly map · physical state at {time.toFixed(2)} s</p>
    </div>
  );
}
export default function Globe(props: GlobeProps) {
  const [webgl] = useState(() => {
    try {
      const c = document.createElement("canvas");
      return Boolean(c.getContext("webgl2"));
    } catch {
      return false;
    }
  });
  const fallback = <FlatMap {...props} />;
  if (props.flat || !webgl) return fallback;
  if (!props.run.frames[0]?.positions.length)
    return (
      <div className="no-geometry">
        <p>
          {["queued", "preparing", "running"].includes(props.run.status)
            ? "Preparing orbital geometry…"
            : "Geometry unavailable for this historical run."}
        </p>
        <span>
          {["queued", "preparing", "running"].includes(props.run.status)
            ? "The isolated worker is building the physical network."
            : "Metrics and recorded routes remain inspectable."}
        </span>
      </div>
    );
  return (
    <SceneBoundary fallback={fallback}>
      <Canvas
        key={props.reset}
        camera={{ position: [3.2, 1.4, -3.0], fov: 38, near: 0.01, far: 50 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true }}
      >
        <ambientLight intensity={0.48} />
        <directionalLight
          position={[3, 3, -4]}
          intensity={2.1}
          color="#e9f5ff"
        />
        <directionalLight
          position={[-3, -1, -3]}
          intensity={0.16}
          color="#3e8cbb"
        />
        <Suspense fallback={null}>
          <Earth placeStation={props.placeStation} />
          <Stars />
          <Satellites {...props} />
          <Network {...props} />
          {props.orbits && <OrbitTraces run={props.run} time={props.time} />}
          <Selection
            run={props.run}
            time={props.time}
            selected={props.selected}
          />
        </Suspense>
        <OrbitControls
          makeDefault
          enablePan={false}
          minDistance={1.4}
          maxDistance={7}
          enableDamping
          dampingFactor={0.08}
          autoRotate={props.rotate}
          autoRotateSpeed={0.2}
        />
      </Canvas>
    </SceneBoundary>
  );
}
