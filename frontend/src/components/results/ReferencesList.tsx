import type { KnowledgeReference } from '@/types/geospatial'

/**
 * Numbered knowledge references with links.
 *
 * Each `[S#]` ref matches an inline marker in the explanation; markers without
 * a matching entry are stripped by the backend and never reach this list.
 */
export function ReferencesList({ references }: { references?: KnowledgeReference[] }) {
  if (!references || references.length === 0) return null
  return (
    <div className="border border-line px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
        References
      </div>
      <ol className="mt-1 space-y-1">
        {references.map((reference) => (
          <li
            key={reference.ref}
            className="flex items-baseline gap-1.5 text-[12px] leading-snug"
          >
            <span className="shrink-0 font-mono text-[11px] text-ink-3">
              [{reference.ref}]
            </span>
            <span className="min-w-0 text-ink-2">
              {reference.title ?? reference.identifier ?? reference.source}
              {reference.url ? (
                <>
                  {' '}
                  <a
                    href={reference.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent-ink underline decoration-accent/50 underline-offset-2 hover:decoration-accent"
                    title={reference.identifier ?? reference.url}
                  >
                    {reference.identifier && reference.identifier.startsWith('doi:')
                      ? 'DOI'
                      : 'link'}
                  </a>
                </>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
