import { EmailNoticeEntry } from '../../api/client'

function fmtWhen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function noticeLabel(ordinal: number): string {
  return ordinal <= 1 ? 'First notice' : ordinal === 2 ? 'Second notice' : 'Final notice'
}

function noticeCls(ordinal: number): string {
  return ordinal >= 3
    ? 'text-red-700 dark:text-red-400'
    : ordinal === 2
    ? 'text-amber-700 dark:text-amber-400'
    : 'ds-u-color--muted'
}

/** Compact per-target email send log: when, to whom, which attempt, by whom.
 * Newest first. Renders nothing when there's no history. */
export default function EmailHistory({ history }: { history?: EmailNoticeEntry[] | null }) {
  if (!history || history.length === 0) return null
  return (
    <div className="mt-3 border-t border-gray-100 dark:border-gray-700 pt-2">
      <div className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">
        Email history ({history.length})
      </div>
      <ul className="space-y-1">
        {[...history].reverse().map((e, i) => (
          <li key={i} className="text-xs text-gray-600 flex flex-wrap items-baseline gap-x-1.5">
            <span className="ds-u-color--muted tabular-nums">{fmtWhen(e.sent_at)}</span>
            <span>· to {e.to.length ? e.to.join(', ') : '—'}</span>
            <span className={`font-medium ${noticeCls(e.ordinal)}`}>· {noticeLabel(e.ordinal)}</span>
            <span>· by {e.by || 'unknown'}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
