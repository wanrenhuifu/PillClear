export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="PillClear">
      <g transform="rotate(-30 16 16)">
        <rect x="3" y="10.5" width="26" height="11" rx="5.5" fill="#0e8a6a" />
        <path d="M16 10.5h7.5a5.5 5.5 0 0 1 0 11H16v-11z" fill="#e3f1ec" />
        <rect x="15" y="10.5" width="2" height="11" fill="#ffffff" />
      </g>
    </svg>
  );
}
