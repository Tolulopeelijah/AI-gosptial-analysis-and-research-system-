import { Fragment } from 'react'
import type { ReactNode } from 'react'
import type { KnowledgeReference } from '@/types/geospatial'

/**
 * Backend prose, rendered as HTML.
 *
 * The agent writes `**bold**` emphasis and `[S#]`/`[T#]` citation markers as
 * plain text. This renders both without `dangerouslySetInnerHTML`: bold runs
 * become `<strong>`, and markers for a listed reference become links — to the
 * reference URL when one exists, otherwise to the matching ReferencesList
 * entry (`#{idPrefix}-ref-{marker}`) rendered with the same prefix.
 * Markers with no matching entry render as plain text.
 */
const TOKEN_RE = /(\*\*[^*\n]+\*\*|\[[ST]\d+\])/g

export function RichText({
  text,
  references,
  idPrefix = 'refs',
  className,
}: {
  text: string
  references?: KnowledgeReference[]
  /** Must match the `idPrefix` of the ReferencesList shown with this text. */
  idPrefix?: string
  className?: string
}) {
  return <span className={className}>{renderRichText(text, references, idPrefix)}</span>
}

function renderRichText(
  text: string,
  references: KnowledgeReference[] | undefined,
  idPrefix: string,
): ReactNode[] {
  return text.split(TOKEN_RE).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>
    }
    const marker = /^\[([ST]\d+)\]$/.exec(part)?.[1]
    if (marker) {
      const reference = references?.find((entry) => entry.ref === marker)
      if (!reference) return <Fragment key={index}>{part}</Fragment>
      const href = reference.url ?? `#${idPrefix}-ref-${marker}`
      const external = !href.startsWith('#')
      return (
        <a
          key={index}
          href={href}
          {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
          title={reference.title ?? reference.identifier ?? reference.ref}
          className="font-mono text-accent-ink underline decoration-accent/50 underline-offset-2 hover:decoration-accent"
        >
          {part}
        </a>
      )
    }
    return <Fragment key={index}>{part}</Fragment>
  })
}
