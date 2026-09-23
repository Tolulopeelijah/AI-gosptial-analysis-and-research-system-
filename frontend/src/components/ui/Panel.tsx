import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

interface PanelProps {
  title?: string
  /** Small leading glyph, sized 14px. */
  icon?: ReactNode
  /** Right-aligned header content: counts, actions. */
  actions?: ReactNode
  children: ReactNode
  className?: string
  /** Removes body padding — for panels whose content manages its own insets. */
  flush?: boolean
  /** Allows the body to scroll instead of growing. */
  scroll?: boolean
}

/**
 * A bordered surface with a hairline header.
 *
 * Panels are the only container in the interface: no nested cards, no shadows,
 * 3px corners. The map is the loud element; everything else stays quiet.
 */
export function Panel({
  title,
  icon,
  actions,
  children,
  className,
  flush = false,
  scroll = false,
}: PanelProps) {
  return (
    <section
      className={cn(
        'flex min-h-0 flex-col border border-line bg-panel',
        className,
      )}
    >
      {title ? (
        <header className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-line px-3">
          <div className="flex min-w-0 items-center gap-1.5">
            {icon ? <span className="text-ink-3">{icon}</span> : null}
            <h2 className="truncate text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-2">
              {title}
            </h2>
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn('min-h-0 flex-1', !flush && 'p-3', scroll && 'overflow-y-auto')}>
        {children}
      </div>
    </section>
  )
}

interface StatusBadgeProps {
  tone: 'neutral' | 'accent' | 'good' | 'warning' | 'critical'
  children: ReactNode
  /** Optional leading dot; status colour never carries meaning alone. */
  dot?: boolean
  className?: string
  /** Tooltip text explaining the state. */
  title?: string
}

const TONES: Record<StatusBadgeProps['tone'], { chip: string; dot: string }> = {
  neutral: { chip: 'border-line-strong bg-panel-muted text-ink-2', dot: 'bg-ink-3' },
  accent: { chip: 'border-accent/35 bg-accent-soft/45 text-accent-ink', dot: 'bg-accent' },
  good: { chip: 'border-good/35 bg-good/8 text-good-ink', dot: 'bg-good' },
  warning: { chip: 'border-warning/45 bg-warning/12 text-ink', dot: 'bg-warning' },
  critical: { chip: 'border-critical/35 bg-critical/8 text-critical', dot: 'bg-critical' },
}

export function StatusBadge({ tone, children, dot = false, className, title }: StatusBadgeProps) {
  const styles = TONES[tone]
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[3px] border px-1.5 py-0.5 text-[11px] font-medium',
        styles.chip,
        className,
      )}
    >
      {dot ? <span className={cn('size-1.5 shrink-0 rounded-full', styles.dot)} aria-hidden="true" /> : null}
      {children}
    </span>
  )
}

/** Label/value row used across the results and map panels. */
export function MetaRow({
  label,
  children,
  mono = false,
}: {
  label: string
  children: ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-[3px]">
      <dt className="shrink-0 text-[12px] text-ink-3">{label}</dt>
      <dd
        className={cn(
          'min-w-0 truncate text-right text-[12px] text-ink',
          mono && 'font-mono tabular-nums',
        )}
      >
        {children}
      </dd>
    </div>
  )
}
