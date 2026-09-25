import { useQueryState } from '@/state/QueryProvider'
import { Panel } from '@/components/ui/Panel'
import { TargetIcon } from '@/components/ui/Icons'

/**
 * Research aims and objectives.
 *
 * Shown in research mode above the composer. One aim per line; the backend
 * structures the paper around them (Aims section) and uses them to focus the
 * abstract and discussion.
 */
export function ResearchBrief() {
  const { aims, setAims } = useQueryState()

  return (
    <Panel title="Aims & objectives" icon={<TargetIcon size={14} />} className="shrink-0">
      <label className="sr-only" htmlFor="weis-aims">
        Research aims and objectives, one per line
      </label>
      <textarea
        id="weis-aims"
        value={aims}
        onChange={(event) => setAims(event.target.value.slice(0, 1000))}
        rows={3}
        spellCheck={false}
        placeholder={'1. Map septic-system exposure to flooding\n2. Prioritise sites for inspection'}
        className="block w-full resize-none border border-line-strong bg-panel px-2.5 py-2 text-[12px] leading-relaxed text-ink outline-none placeholder:text-ink-3 focus:border-accent"
      />
      <p className="mt-1 text-[10px] leading-snug text-ink-3">
        One aim per line — the paper is structured around them.
      </p>
    </Panel>
  )
}
