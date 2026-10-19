import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, ExternalLink, Loader2, UserPlus } from 'lucide-react'
import {
  apiErrorMessage,
  assignCldsptToMe,
  getCldsptSelfServiceQueue,
  getCldsptTransitions,
  transitionCldsptTicket,
  type CldsptSelfServiceQueue,
  type CldsptTransition,
} from '../../api/client'

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString()
}

function TransitionMenu({ issueKey, onDone }: { issueKey: string; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [transitions, setTransitions] = useState<CldsptTransition[] | null>(null)
  const [applying, setApplying] = useState<string | null>(null)
  const [error, setError] = useState('')

  // Re-fetched every time the menu opens, never cached across opens: the
  // valid "next status" set depends on the ticket's *current* status, so a
  // menu left open from before a status change (or one that failed to load
  // last time) would otherwise keep showing a stale or permanently-errored
  // result instead of ever trying again.
  async function toggle() {
    const next = !open
    setOpen(next)
    if (!next) return
    setTransitions(null)
    setError('')
    setLoading(true)
    try {
      const t = await getCldsptTransitions(issueKey)
      if (t.error) setError(t.error)
      setTransitions(t.transitions)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read the available statuses.'))
    } finally {
      setLoading(false)
    }
  }

  async function apply(transitionId: string) {
    setApplying(transitionId)
    setError('')
    try {
      await transitionCldsptTicket(issueKey, transitionId)
      setOpen(false)
      onDone()
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not update the ticket.'))
    } finally {
      setApplying(null)
    }
  }

  return (
    <div className="relative inline-block">
      <button
        onClick={toggle}
        className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600 ds-u-color--muted hover:bg-gray-50 dark:hover:bg-gray-700"
      >
        Change status
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg py-1">
          {loading && (
            <p className="px-3 py-2 text-xs ds-u-color--muted flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin" /> Reading workflow…
            </p>
          )}
          {error && <p className="px-3 py-2 text-xs text-red-600">{error}</p>}
          {transitions && transitions.length === 0 && !error && (
            <p className="px-3 py-2 text-xs ds-u-color--muted">No transitions available from here.</p>
          )}
          {transitions?.map(t => (
            <button
              key={t.id}
              onClick={() => apply(t.id)}
              disabled={applying !== null}
              className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 flex items-center justify-between"
            >
              {t.name}
              {applying === t.id && <Loader2 size={11} className="animate-spin" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function GitHubSelfServiceQueue() {
  const [data, setData] = useState<CldsptSelfServiceQueue | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [assigning, setAssigning] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [onlyNeedsPickup, setOnlyNeedsPickup] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await getCldsptSelfServiceQueue())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read the ticket queue.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function assignToMe(issueKey: string) {
    setAssigning(issueKey)
    setNotice(null)
    try {
      await assignCldsptToMe(issueKey)
      setNotice({ kind: 'ok', text: `${issueKey} is now assigned to you.` })
      await load()
    } catch (err: unknown) {
      setNotice({ kind: 'err', text: apiErrorMessage(err, 'Could not assign the ticket.') })
    } finally {
      setAssigning(null)
    }
  }

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading the ticket queue…
      </div>
    )
  }

  if (error || data?.error) {
    return (
      <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        {error || data?.error}
      </div>
    )
  }

  if (!data) return null

  const rows = onlyNeedsPickup ? data.tickets.filter(t => t.needs_pickup) : data.tickets

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs ds-u-color--muted">
          {data.returned} of {data.total ?? data.returned} open developer-submitted GitHub requests,
          oldest first. <strong className="text-amber-700">{data.needs_pickup}</strong> still sit with the
          default assignee and need someone to pick them up.
        </p>
        <label className="flex items-center gap-1.5 text-xs ds-u-color--muted">
          <input type="checkbox" checked={onlyNeedsPickup} onChange={e => setOnlyNeedsPickup(e.target.checked)} />
          Needs pickup only
        </label>
      </div>

      <p className="text-[11px] ds-u-color--muted bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        Assigning and changing status here acts on the real Jira ticket immediately — this view runs
        locally, but the writes are not local.
      </p>

      {notice && (
        <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs border ${
          notice.kind === 'ok' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-800'
        }`}>
          {notice.kind === 'ok' ? <CheckCircle size={13} className="flex-shrink-0 mt-0.5" /> : <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />}
          <span>{notice.text}</span>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="text-sm ds-u-color--muted py-6 text-center">Nothing here right now.</p>
      ) : (
        <div className="rounded-lg border border-gray-100 dark:border-gray-700">
          {/* Rounding lives on the header's end cells, not on this wrapper,
              so it doesn't need overflow-hidden -- that would clip the
              per-row status-change dropdown below instead of just this
              table's corners. */}
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium rounded-tl-lg">Ticket</th>
                <th className="text-left px-3 py-2 font-medium">Type</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Assignee</th>
                <th className="text-left px-3 py-2 font-medium">Reporter</th>
                <th className="text-left px-3 py-2 font-medium">Created</th>
                <th className="text-right px-3 py-2 font-medium rounded-tr-lg">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={t.key} className={`${i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''} ${t.needs_pickup ? 'bg-amber-50/40' : ''}`}>
                  <td className={`px-3 py-2 text-xs ${i === rows.length - 1 ? 'rounded-bl-lg' : ''}`}>
                    <a href={t.url} target="_blank" rel="noopener noreferrer" className="font-medium text-cms-blue hover:underline inline-flex items-center gap-1">
                      {t.key} <ExternalLink size={10} />
                    </a>
                    <p className="text-[11px] ds-u-color--muted mt-0.5 max-w-xs truncate" title={t.summary}>{t.summary}</p>
                  </td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{t.issue_type}</td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{t.status}</td>
                  <td className="px-3 py-2 text-xs">
                    {t.needs_pickup ? (
                      <span className="text-amber-700 font-medium">needs pickup</span>
                    ) : (
                      <span className="ds-u-color--muted">{t.assignee_name || t.assignee || '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{t.reporter_name || t.reporter || '—'}</td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{when(t.created)}</td>
                  <td className={`px-3 py-2 ${i === rows.length - 1 ? 'rounded-br-lg' : ''}`}>
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => assignToMe(t.key)}
                        disabled={assigning !== null}
                        className="text-xs px-2 py-1 rounded border border-gray-200 dark:border-gray-600 ds-u-color--muted hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 inline-flex items-center gap-1"
                      >
                        {assigning === t.key ? <Loader2 size={11} className="animate-spin" /> : <UserPlus size={11} />}
                        Assign to me
                      </button>
                      <TransitionMenu issueKey={t.key} onDone={load} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
