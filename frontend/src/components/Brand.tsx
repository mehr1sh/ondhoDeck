export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="7" fill="#1e293b" />
      <path d="M5 11 L13 11 L19 21 L27 21" stroke="#a3e635" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <BrandMark className="h-7 w-7" />
      {!compact && (
        <span className="leading-tight">
          <span className="block text-base font-semibold text-slate-900">SlipSlopes</span>
          <span className="block text-[11px] text-slate-500">Contractual Liquidity Intelligence</span>
        </span>
      )}
    </span>
  );
}
