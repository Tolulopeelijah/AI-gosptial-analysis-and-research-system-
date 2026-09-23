import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useQueryState } from '@/state/QueryProvider'
import { useMapState } from '@/state/MapProvider'
import { describeGeometry, toFeatures } from '@/lib/geo'
import { formatCompact, formatDuration, truncate } from '@/lib/format'
import { Panel, StatusBadge } from '@/components/ui/Panel'
import { StatTile } from '@/components/ui/StatTile'
import { Button } from '@/components/ui/Button'
import { TableIcon, LineIcon, LayersIcon, TargetIcon } from '@/components/ui/Icons'
import { ErrorNotice } from './ErrorNotice'
import { AttributeTable } from './AttributeTable'
import { AttributeDistribution } from './AttributeDistribution'
import { LayerList } from './LayerList'
import type { GeographicResult } from '@/types/geospatial'

type Tab = 'attributes' | 'distribution' | 'layers'

const TABS: Array<{ id: Tab; label: string; icon: ReactNode }> = [
  { id: 'attributes', label: 'Attributes', icon: <TableIcon size={12} /> },
  { id: 'distribution', label: 'Distribution', icon: <LineIcon size={12} /> },
  { id: 'layers', label: 'Layers', icon: <LayersIcon size={12} /> },
]

/**
 * The results dock.
 *
 * Answers, in order: did it work, what came back, and what does it look like as
 * data. The figures come first as stat tiles, then the backend's own
 * explanation, then the attribute table — which is the part that makes this an
 * analysis tool rather than a picture of one.
 */
export function ResultsPanel() {
  const { run, isRunning } = useQueryState().query
  const { fitResults, hasResults } = useMapState()
  const [tab, setTab] = useState<Tab>('attributes')
  const [activeLayerId, setActiveLayerId] = useState<string | null>(null)

  const primaryLayers = useMemo(
    () => run.results.filter((result) => result.metadata?.role !== 'context'),
    [run.results],
  )

  // A new run resets the dock to its default view.
  useEffect(() => {
    setActiveLayerId(null)
    setTab('attributes')
  }, [run.queryId])

  const activeLayer =
    primaryLayers.find((result) => result.id === activeLayerId) ?? primaryLayers[0] ?? null

  const duration = run.startedAt != null ? (run.finishedAt ?? Date.now()) - run.startedAt : undefined

  if (run.status === 'failed' && run.error) {
    return (
      <Panel title="Results" icon={<TargetIcon size={14} />} className="shrink-0">
        <ErrorNotice error={run.error} query={run.query} />
      </Panel>
    )
  }

  if (run.status === 'idle') {
    return (
      <Panel
        title="Results"
        icon={<TargetIcon size={14} />}
        className="shrink-0"
        actions={<span className="text-[10px] text-ink-3">waiting for a query</span>}
      >
        <p className="text-[12px] leading-relaxed text-ink-3">
          Figures, the agent's explanation, and the attribute table for the returned features
          appear here. Nothing is computed until a query runs.
        </p>
      </Panel>
    )
  }

  if (isRunning && run.results.length === 0) {
    return (
      <Panel
        title="Results"
        icon={<TargetIcon size={14} />}
        className="shrink-0"
        actions={<StatusBadge tone="accent" dot>running</StatusBadge>}
      >
        <p className="text-[12px] leading-relaxed text-ink-3">
          {truncate(run.query, 90)} — results are drawn as each layer arrives.
        </p>
      </Panel>
    )
  }

  if (run.results.length === 0) {
    return (
      <Panel
        title="Results"
        icon={<TargetIcon size={14} />}
        className="shrink-0"
        actions={<StatusBadge tone="warning">0 features</StatusBadge>}
      >
        <div className="border border-warning/45 bg-warning/8 px-3 py-2.5">
          <h3 className="text-[13px] font-semibold text-ink">The query ran, but matched nothing</h3>
          <p className="mt-1 text-[12px] leading-relaxed text-ink-2">
            {run.explanation ??
              'Every condition was applied to the dataset and no feature satisfied all of them. This is a result, not a failure — the query was valid.'}
          </p>
          <p className="mt-1.5 text-[12px] text-ink-2">
            <span className="font-medium text-ink">Next: </span>
            loosen a threshold, drop a condition, or widen the geographic extent.
          </p>
        </div>
      </Panel>
    )
  }

  const featureTotal = primaryLayers.reduce(
    (sum, result) => sum + (result.metadata?.count ?? toFeatures(result.data).length),
    0,
  )
  const contextLayers = run.results.length - primaryLayers.length
  const geometry = activeLayer ? describeGeometry(toFeatures(activeLayer.data)) : '—'

  return (
    <Panel
      title="Results"
      icon={<TargetIcon size={14} />}
      className="shrink-0"
      actions={
        <>
          <StatusBadge tone="good">complete</StatusBadge>
          <Button
            size="sm"
            variant="ghost"
            icon={<TargetIcon size={12} />}
            onClick={fitResults}
            disabled={!hasResults()}
          >
            Fit
          </Button>
        </>
      }
    >
      <div className="space-y-2.5">
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-5">
          <StatTile
            label="Features"
            value={formatCompact(featureTotal)}
            note={`${primaryLayers.length} ${primaryLayers.length === 1 ? 'layer' : 'layers'}`}
            title="Features across the primary result layers"
          />
          <StatTile
            label="Geometry"
            value={geometry.split(' × ')[0]}
            note={geometry.includes(' × ') ? `${geometry.split(' × ')[1]} parts` : undefined}
          />
          <StatTile
            label="Runtime"
            value={formatDuration(duration)}
            note={run.steps.length > 0 ? `${run.steps.length} steps` : undefined}
          />
          <StatTile
            label="Dataset"
            value={run.dataset ? truncate(run.dataset, 22) : '—'}
            title={run.dataset}
          />
          <StatTile
            label="Context layers"
            value={String(contextLayers)}
            note={contextLayers > 0 ? 'buffer · reference' : 'none'}
            title="Supporting geometry the query implied, not part of the answer"
          />
        </div>

        {run.explanation ? (
          <div className="border-l-2 border-accent/50 bg-accent-soft/22 px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
              Agent's explanation
            </div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{run.explanation}</p>
          </div>
        ) : null}

        {run.references && run.references.length > 0 ? (
          <div className="border border-line px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.07em] text-ink-3">
              References
            </div>
            <ol className="mt-1 space-y-1">
              {run.references.map((reference) => (
                <li key={reference.ref} className="flex items-baseline gap-1.5 text-[12px] leading-snug">
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
        ) : null}

        {primaryLayers.length > 1 ? (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] uppercase tracking-[0.06em] text-ink-3">Layer</span>
            {primaryLayers.map((layer) => (
              <button
                key={layer.id}
                type="button"
                onClick={() => setActiveLayerId(layer.id)}
                aria-pressed={activeLayer?.id === layer.id}
                className={cn(
                  'rounded-[2px] border px-1.5 py-0.5 text-[11px]',
                  activeLayer?.id === layer.id
                    ? 'border-accent/50 bg-accent-soft/50 text-accent-ink'
                    : 'border-line text-ink-2 hover:bg-panel-muted',
                )}
              >
                {layer.metadata?.title ?? layer.id}
              </button>
            ))}
          </div>
        ) : null}

        <div className="flex items-center gap-0.5 border-b border-line">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              aria-pressed={tab === entry.id}
              className={cn(
                '-mb-px inline-flex items-center gap-1.5 border-b-2 px-2.5 py-1.5 text-[12px]',
                tab === entry.id
                  ? 'border-accent font-medium text-ink'
                  : 'border-transparent text-ink-2 hover:text-ink',
              )}
            >
              <span className="text-ink-3">{entry.icon}</span>
              {entry.label}
              {entry.id === 'layers' ? (
                <span className="font-mono text-[10px] text-ink-3">{run.results.length}</span>
              ) : null}
            </button>
          ))}
        </div>

        <div>
          {tab === 'attributes' ? (
            activeLayer ? (
              <AttributeTable result={activeLayer} />
            ) : (
              <EmptyTabNote>
                No primary layer to tabulate — this response contains only context geometry.
              </EmptyTabNote>
            )
          ) : null}

          {tab === 'distribution' ? (
            activeLayer ? (
              <AttributeDistributionResult result={activeLayer} />
            ) : (
              <EmptyTabNote>No primary layer to summarise.</EmptyTabNote>
            )
          ) : null}

          {tab === 'layers' ? <LayerList results={run.results} /> : null}
        </div>
      </div>
    </Panel>
  )
}

/** Falls back to a plain count summary when there is no numeric attribute. */
function AttributeDistributionResult({ result }: { result: GeographicResult }) {
  const fields = result.metadata?.attributes ?? []
  const hasNumeric = fields.some((field) => field.type === 'number' && field.role !== 'id')
  if (!hasNumeric && fields.length > 0) {
    return (
      <EmptyTabNote>
        This layer declares no numeric attribute, so there is no distribution to plot. The
        attributes tab lists its {fields.length} fields.
      </EmptyTabNote>
    )
  }
  return <AttributeDistribution result={result} />
}

function EmptyTabNote({ children }: { children: ReactNode }) {
  return <p className="text-[11px] leading-relaxed text-ink-3">{children}</p>
}
