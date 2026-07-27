import type { ButtonHTMLAttributes } from "react";

const VARIANTS = {
  primary: "bg-pharma text-white shadow-sm hover:bg-pharma-deep disabled:bg-mute/40",
  ghost: "border border-line bg-card text-ink hover:border-pharma/50 hover:text-pharma-deep disabled:opacity-40",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:opacity-40",
} as const;

const SIZES = {
  md: "px-4 py-2 text-sm",
  sm: "px-3 py-1.5 text-xs",
} as const;

export function CapsuleButton({
  variant = "primary",
  size = "md",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
}) {
  return (
    <button
      type="button"
      {...rest}
      className={`rounded-full font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:active:scale-100 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    />
  );
}
