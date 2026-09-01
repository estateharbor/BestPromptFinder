import { useId } from "react";

const PALETTES = [
  { a: "#241706", b: "#4a3411", glow: "#efc766", sub: "#c99a34" },
  { a: "#2a1717", b: "#4d322a", glow: "#f0b78c", sub: "#cf9070" },
  { a: "#0b0a26", b: "#1c1246", glow: "#8ea0ff", sub: "#e363ad" },
  { a: "#07171d", b: "#103139", glow: "#54cede", sub: "#2f93ab" },
  { a: "#2b1021", b: "#4e1b33", glow: "#ff9f72", sub: "#ea5b70" },
  { a: "#0f1317", b: "#222a31", glow: "#d0d8e0", sub: "#8a929b" },
];

/** Procedurally generated cinematic sample tile — self-contained, no external assets. */
export function ArtTile({ seed }: { seed: number }) {
  const uid = useId().replace(/[:]/g, "");
  const p = PALETTES[((seed % PALETTES.length) + PALETTES.length) % PALETTES.length];
  const fx = 30 + ((seed * 17) % 45);
  const fy = 32 + ((seed * 11) % 30);
  const rot = ((seed * 37) % 60) - 30;
  return (
    <svg viewBox="0 0 100 125" preserveAspectRatio="xMidYMid slice" aria-hidden style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
      <defs>
        <linearGradient id={`bg${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.b} /><stop offset="1" stopColor={p.a} />
        </linearGradient>
        <radialGradient id={`gl${uid}`} cx={`${fx}%`} cy={`${fy}%`} r="60%">
          <stop offset="0" stopColor={p.glow} stopOpacity="0.9" />
          <stop offset="45%" stopColor={p.sub} stopOpacity="0.35" />
          <stop offset="100%" stopColor={p.a} stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`vg${uid}`} cx="50%" cy="46%" r="75%">
          <stop offset="55%" stopColor="#000" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.55" />
        </radialGradient>
        <filter id={`gr${uid}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
      </defs>
      <rect width="100" height="125" fill={`url(#bg${uid})`} />
      <ellipse cx={fx} cy={fy} rx="46" ry="40" fill={`url(#gl${uid})`} />
      <g transform={`translate(${fx} ${fy + 18}) rotate(${rot})`} opacity="0.45">
        <rect x="-30" y="-4" width="60" height="8" rx="4" fill={p.sub} opacity="0.5" />
        <circle cx="0" cy="-14" r="15" fill={p.glow} opacity="0.28" />
      </g>
      <rect width="100" height="125" fill={`url(#vg${uid})`} />
      <rect width="100" height="125" filter={`url(#gr${uid})`} opacity="0.06" />
    </svg>
  );
}
