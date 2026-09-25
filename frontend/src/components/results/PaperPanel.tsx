import { useQueryState } from '@/state/QueryProvider'
import { Panel } from '@/components/ui/Panel'
import { Button } from '@/components/ui/Button'
import { DocumentIcon, DownloadIcon } from '@/components/ui/Icons'
import { ReferencesList } from './ReferencesList'
import { TablesSection } from './TablesSection'

/**
 * The research output: a paper-style report.
 *
 * Title, aims, data, methods, results, limitations, and reproducibility come
 * straight from the validated plan and execution record; only the abstract,
 * discussion, and conclusion are model-written (grounded, with markers).
 * Downloads as Markdown.
 */
export function PaperPanel() {
  const { run } = useQueryState().query
  const paper = run.paper

  if (!paper) return null

  function downloadMarkdown() {
    const blob = new Blob([paper?.markdown ?? ''], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'weis-report.md'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <Panel
      title="Research report"
      icon={<DocumentIcon size={14} />}
      className="shrink-0"
      actions={
        <>
          {paper.llm_grounded === false ? (
            <span className="text-[10px] text-ink-3" title="No model configured; prose sections are deterministic summaries">
              deterministic prose
            </span>
          ) : null}
          <Button
            size="sm"
            variant="default"
            icon={<DownloadIcon size={12} />}
            onClick={downloadMarkdown}
            disabled={!paper.markdown}
          >
            Markdown
          </Button>
        </>
      }
    >
      <article className="space-y-3">
        <h2 className="text-[15px] font-bold leading-snug tracking-[-0.01em] text-ink">
          {paper.title}
        </h2>

        {paper.abstract ? (
          <Section heading="Abstract">
            <p className="text-[12.5px] italic leading-relaxed text-ink-2">{paper.abstract}</p>
          </Section>
        ) : null}

        {paper.aims && paper.aims.length > 0 ? (
          <Section heading="Aims and objectives">
            <ol className="list-decimal space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.aims.map((aim, index) => (
                <li key={index}>{aim}</li>
              ))}
            </ol>
          </Section>
        ) : null}

        {paper.data && paper.data.length > 0 ? (
          <Section heading="Data">
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.data.map((entry, index) => (
                <li key={index}>{entry.dataset}</li>
              ))}
            </ul>
          </Section>
        ) : null}

        {paper.methods && paper.methods.length > 0 ? (
          <Section heading="Methods">
            <ol className="list-decimal space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.methods.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          </Section>
        ) : null}

        <Section heading="Results">
          {paper.results?.layers && paper.results.layers.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.results.layers.map((layer, index) => (
                <li key={index}>
                  {layer.title}: <strong className="text-ink">{layer.count}</strong> features
                  {layer.dataset ? ` (${layer.dataset})` : ''}
                </li>
              ))}
            </ul>
          ) : null}
          {paper.results?.tables && paper.results.tables.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.results.tables.map((table, index) => (
                <li key={index}>
                  {table.title}: <strong className="text-ink">{table.row_count}</strong> rows
                </li>
              ))}
            </ul>
          ) : null}
          {paper.results?.findings ? (
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.results.findings}
            </p>
          ) : null}
          <div className="mt-2">
            <TablesSection embedded />
          </div>
        </Section>

        {paper.discussion ? (
          <Section heading="Discussion">
            <p className="text-[12.5px] leading-relaxed text-ink-2">{paper.discussion}</p>
          </Section>
        ) : null}

        {paper.conclusion ? (
          <Section heading="Conclusion">
            <p className="text-[12.5px] leading-relaxed text-ink-2">{paper.conclusion}</p>
          </Section>
        ) : null}

        {paper.limitations && paper.limitations.length > 0 ? (
          <Section heading="Limitations">
            <ul className="list-disc space-y-0.5 pl-5 text-[12.5px] leading-relaxed text-ink-2">
              {paper.limitations.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </Section>
        ) : null}

        <ReferencesList references={paper.references} />

        {paper.reproducibility ? (
          <p className="font-mono text-[10px] leading-relaxed text-ink-3">
            Query {String(paper.reproducibility.query_id ?? '')} · tools:{' '}
            {Array.isArray(paper.reproducibility.selected_tools)
              ? paper.reproducibility.selected_tools.join(', ')
              : ''}
          </p>
        ) : null}
      </article>
    </Panel>
  )
}

function Section({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="border-b border-line pb-1 text-[11px] font-bold uppercase tracking-[0.07em] text-ink">
        {heading}
      </h3>
      <div className="mt-1.5">{children}</div>
    </section>
  )
}
