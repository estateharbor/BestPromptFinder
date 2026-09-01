import { useEffect, useState } from "react";

export function band(v: number): "good" | "mid" | "accent" {
  return v >= 90 ? "good" : v >= 80 ? "mid" : "accent";
}
const COLOR = { good: "var(--color-good)", mid: "var(--color-mid)", accent: "var(--color-accent)" };

/** Animated count-up number, robust: always lands on the target value. */
export function CountUp({ value, suffix = "", className = "" }: { value: number; suffix?: string; className?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { setN(value); return; }
    let raf = 0; const start = performance.now(); const dur = 520;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      setN(Math.round(value * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    const fallback = setTimeout(() => setN(value), dur + 120);
    return () => { cancelAnimationFrame(raf); clearTimeout(fallback); };
  }, [value]);
  return <span className={`tnum ${className}`}>{n}{suffix}</span>;
}

export function Ring({ value, suffix = "", size = 86 }: { value: number; suffix?: string; size?: number }) {
  const r = 34, c = 2 * Math.PI * r;
  const off = c * (1 - value / 100);
  const col = COLOR[band(value)];
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 86 86" aria-hidden>
        <circle cx="43" cy="43" r={r} fill="none" stroke="var(--color-sunk)" strokeWidth="9" />
        <circle cx="43" cy="43" r={r} fill="none" stroke={col} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={off} transform="rotate(-90 43 43)"
          style={{ transition: "stroke-dashoffset .6s cubic-bezier(.3,0,.1,1)" }} />
      </svg>
      <div>
        <CountUp value={value} suffix={suffix} className="font-display font-black text-[30px] leading-none" />
      </div>
    </div>
  );
}

export function MiniScore({ label, value, suffix = "" }: { label: string; value: number; suffix?: string }) {
  const col = COLOR[band(value)];
  return (
    <div className="text-right min-w-[46px]">
      <div style={{ color: col }}>
        <CountUp value={value} suffix={suffix} className="font-display font-extrabold text-[18px] leading-none" />
      </div>
      <div className="font-mono text-[9px] uppercase tracking-wider mt-0.5" style={{ color: "var(--color-ink3)" }}>{label}</div>
    </div>
  );
}

export function Bar({ value, colorBand }: { value: number; colorBand?: "good" | "mid" | "accent" }) {
  const col = COLOR[colorBand ?? band(value)];
  return (
    <div className="h-[7px] rounded-md overflow-hidden" style={{ background: "var(--color-sunk)" }}>
      <div className="h-full rounded-md" style={{ width: `${value}%`, background: col, transition: "width .5s ease" }} />
    </div>
  );
}
