import type { ComponentPropsWithRef, ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * The interface's button.
 *
 * Three variants only: `primary` for the one action a panel is about,
 * `default` for secondary actions, `ghost` for controls that live on the map.
 * Rectangular with a hairline border — this is an instrument panel, not a
 * marketing page.
 */
export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

interface ButtonProps extends ComponentPropsWithRef<'button'> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Leading icon element. */
  icon?: ReactNode
  /** Trailing icon element. */
  trailingIcon?: ReactNode
  /** Swaps the leading icon for a spinner and disables the button. */
  loading?: boolean
  fullWidth?: boolean
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-white border-accent hover:bg-accent-ink hover:border-accent-ink disabled:bg-accent/50 disabled:border-accent/40',
  default:
    'bg-panel text-ink border-line-strong hover:bg-panel-muted disabled:text-ink-3 disabled:bg-panel-muted',
  ghost:
    'bg-panel/95 text-ink-2 border-line-strong hover:text-ink hover:bg-panel disabled:text-ink-3 disabled:bg-panel/70',
  danger: 'bg-panel text-critical border-critical/50 hover:bg-critical/8',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-7 px-2.5 text-[12px] gap-1.5',
  md: 'h-9 px-3.5 text-[13px] gap-2',
}

export function Button({
  variant = 'default',
  size = 'md',
  icon,
  trailingIcon,
  loading = false,
  fullWidth = false,
  className,
  children,
  disabled,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center rounded-[3px] border font-medium transition-colors',
        'disabled:cursor-not-allowed',
        VARIANTS[variant],
        SIZES[size],
        fullWidth && 'w-full',
        className,
      )}
      {...props}
    >
      {loading ? <Spinner /> : icon}
      {children}
      {trailingIcon}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block size-3.5 shrink-0 animate-spin rounded-full border-[1.5px] border-current border-t-transparent',
        className,
      )}
      aria-hidden="true"
    />
  )
}

interface IconButtonProps extends ComponentPropsWithRef<'button'> {
  label: string
  active?: boolean
  variant?: ButtonVariant
}

export function IconButton({
  label,
  active = false,
  variant = 'ghost',
  className,
  children,
  ...props
}: IconButtonProps) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active || undefined}
      className={cn(
        'inline-flex size-7 items-center justify-center rounded-[3px] border transition-colors',
        variant === 'ghost' ? 'border-transparent' : 'border-line-strong',
        active ? 'bg-accent-soft/70 text-accent-ink' : 'text-ink-2',
        'hover:bg-panel-muted hover:text-ink disabled:cursor-not-allowed disabled:text-ink-3 disabled:hover:bg-transparent',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}
