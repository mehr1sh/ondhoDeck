export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="2" fill="#2f6b4f" />
      <rect x="7" y="9" width="18" height="3" rx="1" fill="#faf8f4" />
      <rect x="7" y="15" width="18" height="3" rx="1" fill="#faf8f4" opacity="0.8" />
      <rect x="7" y="21" width="11" height="3" rx="1" fill="#faf8f4" opacity="0.6" />
    </svg>
  );
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <BrandMark className="h-7 w-7" />
      {!compact && (
        <span className="leading-tight">
          <span className="font-display block text-[17px] text-ink">OndhoDeck</span>
          <span className="block text-[11px] text-ink-3">Contract-aware liquidity analysis</span>
        </span>
      )}
    </span>
  );
}
