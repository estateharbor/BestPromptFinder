export function Toast({ message }: { message: string | null }) {
  return (
    <div
      className="fixed left-1/2 bottom-8 z-50 flex items-center gap-2.5 font-mono text-[13px] px-5 py-3 rounded-[11px] pointer-events-none transition-all"
      style={{
        transform: `translate(-50%, ${message ? 0 : 20}px)`,
        opacity: message ? 1 : 0,
        background: "var(--color-ink)",
        color: "var(--color-ground)",
        boxShadow: "var(--shadow-lg, 0 20px 50px -20px rgba(0,0,0,.4))",
      }}
    >
      <span style={{ color: "var(--color-good)", fontWeight: 700 }}>✓</span>
      {message}
    </div>
  );
}
