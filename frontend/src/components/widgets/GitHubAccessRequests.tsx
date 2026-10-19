import { Fragment, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, ChevronDown, ChevronRight, Loader2, MessageSquare, RefreshCw, Send, Ticket } from 'lucide-react'
import {
  apiErrorMessage,
  getCldsptEngineer,
  getCldsptQueue,
  getCldsptSweepStatus,
  requestBoApproval,
  requestSecondStageApproval,
  sendCldsptSlackNudge,
  startCldsptSweep,
  CldsptEngineer,
  CldsptEngineerTickets,
  CldsptQueue,
  CldsptTicket,
} from '../../api/client'

// Buckets that still need someone to act, in the order they are shown.
const OPEN_ORDER = ['new', 'pending_approval', 'waiting_customer', 'needs_engineer', 'on_hold']
const DONE_ORDER = ['resolved', 'closed', 'canceled']

const TONES: Record<string, string> = {
  new: 'text-blue-700 bg-blue-50 border-blue-200',
  pending_approval: 'text-amber-800 bg-amber-50 border-amber-200',
  waiting_customer: 'text-purple-700 bg-purple-50 border-purple-200',
  needs_engineer: 'text-red-700 bg-red-50 border-red-200',
  on_hold: 'text-gray-600 bg-gray-50 border-gray-200',
  resolved: 'text-green-700 bg-green-50 border-green-200',
  closed: 'text-gray-600 bg-gray-50 border-gray-200',
  canceled: 'ds-u-color--muted bg-gray-50 border-gray-200',
  other: 'text-gray-600 bg-gray-50 border-gray-200',
}

const BO_TONES: Record<string, string> = {
  required: 'border-red-200 bg-red-50 text-red-800',
  requested: 'border-amber-200 bg-amber-50 text-amber-800',
  bo_approved: 'border-purple-200 bg-purple-50 text-purple-800',
  second_stage_requested: 'border-purple-200 bg-purple-50/60 text-purple-700',
  approved: 'border-green-200 bg-green-50 text-green-800',
  not_required: 'border-gray-200 bg-gray-50 ds-u-color--muted',
}
const BO_SHORT: Record<string, string> = {
  required: 'needs BO',
  requested: 'asked',
  bo_approved: 'needs Hung',
  second_stage_requested: 'Hung asked',
  approved: 'done',
  not_required: 'n/a',
}
const BO_HINTS: Record<string, string> = {
  required: 'No approval and no request on the ticket yet',
  requested: 'The approval request is on the ticket; waiting on the Business Owner',
  bo_approved: 'The Business Owner approved; the second-stage approver has not been asked yet',
  second_stage_requested: 'Waiting on the second-stage approver',
  approved: 'Both stages have signed off',
  not_required: 'Copilot seat requests do not need a Business Owner approval',
}



function pct(n: number, total: number): string {
  if (!total) return ''
  return `${Math.round((n / total) * 100)}%`
}

function when(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? 'unknown' : d.toLocaleString()
}

/** Reads as the state until hovered, when it becomes the action. Used for both
 *  approval stages: the Business Owner first, then the second-stage approver
 *  once the Business Owner has signed off. */
function ApprovalButton({ stage, ticket, busy, done, onRequest }: {
  stage: 'bo' | 'second'
  ticket: CldsptTicket
  busy: boolean
  done?: string
  onRequest: () => void
}) {
  const [hover, setHover] = useState(false)
  const a = ticket.bo_approval

  if (done) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-green-200 bg-green-50 text-green-800">
        <CheckCircle size={11} /> {done}
      </span>
    )
  }

  const asked = stage === 'bo'
    ? a?.state === 'requested'
    : a?.state === 'second_stage_requested'
  const askedOn = stage === 'bo' ? a?.bo_requested_on : a?.second_stage_requested_on
  const who = stage === 'bo' ? 'BO' : a?.second_stage_approver ?? 'Hung Van'

  const idleLabel = asked
    ? `${who} asked${askedOn ? ` ${new Date(askedOn).toLocaleDateString()}` : ''}`
    : `${who} approval required`

  const tip = stage === 'bo'
    ? "Comments on the ticket asking the requester to get their Business Owner's approval"
    : `Comments on the ticket asking ${who} to sign off, now that the Business Owner has approved`

  return (
    <button
      onClick={(ev) => { ev.stopPropagation(); onRequest() }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      disabled={busy}
      title={tip}
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border transition-colors disabled:opacity-60 ${
        hover
          ? 'border-cms-blue bg-blue-50 text-cms-blue'
          : asked
            ? 'border-amber-200 bg-amber-50 text-amber-800'
            : stage === 'second'
              ? 'border-purple-200 bg-purple-50 text-purple-800'
              : 'border-red-200 bg-red-50 text-red-800'
      }`}
    >
      {busy
        ? <Loader2 size={11} className="animate-spin" />
        : hover ? <Send size={11} /> : <AlertTriangle size={11} />}
      {busy ? 'Posting…' : hover ? `Request ${who} approval` : idleLabel}
    </button>
  )
}

/** Application Name as a label on the ticket.
 *  Solid when the field is set, dashed when we worked it out ourselves, and
 *  explicitly unset when there is nothing to show, since a blank Application
 *  Name is why a ticket has no approver. */
function ApplicationLabel({ ticket }: { ticket: CldsptTicket }) {
  const set = ticket.application_name
  const guess = ticket.application_inferred

  if (set) {
    return (
      <span
        title="Application Name on the ticket"
        className="text-xs px-2 py-0.5 rounded-full border border-indigo-200 bg-indigo-50 text-indigo-800"
      >
        {set}
      </span>
    )
  }

  if (guess?.name) {
    const from = guess.source === 'ad_groups' ? "the requester's AD groups" : 'the justification text'
    const tip = guess.confirmed
      ? `Not set on the ticket. Matched "${guess.matched_on}" from ${from} against the application catalog.`
      : `Not set on the ticket. Best guess "${guess.name}" from ${from}, not found in the application catalog, so treat it as a lead.`
    return (
      <span
        title={tip}
        className={`text-xs px-2 py-0.5 rounded-full border border-dashed ${
          guess.confirmed
            ? 'border-indigo-300 bg-indigo-50/60 text-indigo-700'
            : 'border-gray-300 bg-gray-50 ds-u-color--muted'
        }`}
      >
        {guess.name}
        {guess.confirmed ? ' (inferred)' : '?'}
      </span>
    )
  }

  return (
    <span
      title="No Application Name on the ticket, and neither the justification nor the requester's AD groups named one. Jira cascades the approvers off this field, so it has nobody to approve it."
      className="text-xs px-2 py-0.5 rounded-full border border-dashed border-red-200 bg-red-50 text-red-700"
    >
      App not set
    </span>
  )
}

export default function GitHubAccessRequests() {
  const [queue, setQueue] = useState<CldsptQueue | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sweeping, setSweeping] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [detail, setDetail] = useState<Record<string, CldsptEngineerTickets>>({})
  const [detailLoading, setDetailLoading] = useState<string | null>(null)
  const [boBusy, setBoBusy] = useState<string | null>(null)
  const [boDone, setBoDone] = useState<Record<string, string>>({})
  const [boFilter, setBoFilter] = useState<string | null>(null)
  const [slackBusy, setSlackBusy] = useState<string | null>(null)
  const [slackDone, setSlackDone] = useState<Record<string, string>>({})
  const [slackArmed, setSlackArmed] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setQueue(await getCldsptQueue())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not load the access request queue.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function refresh() {
    setSweeping(true)
    setError('')
    try {
      await startCldsptSweep()
      // The sweep runs in the background; poll until it clears, then reload.
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 3000))
        const s = await getCldsptSweepStatus()
        if (!s.running) {
          if (s.last_error) setError(s.last_error)
          break
        }
      }
      await load()
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not refresh the queue.'))
    } finally {
      setSweeping(false)
    }
  }

  async function toggle(username: string) {
    if (open === username) { setOpen(null); return }
    setOpen(username)
    if (detail[username]) return
    setDetailLoading(username)
    try {
      const d = await getCldsptEngineer(username)
      setDetail((prev) => ({ ...prev, [username]: d }))
    } catch (err: unknown) {
      setError(apiErrorMessage(err, `Could not load tickets for ${username}.`))
    } finally {
      setDetailLoading(null)
    }
  }

  async function askBoApproval(issueKey: string) {
    setBoBusy(issueKey)
    setError('')
    try {
      const res = await requestBoApproval(issueKey)
      setBoDone((prev) => ({ ...prev, [issueKey]: `Requested from [~${res.mentioned}]` }))
    } catch (err: unknown) {
      setError(apiErrorMessage(err, `Could not post the approval request on ${issueKey}.`))
    } finally {
      setBoBusy(null)
    }
  }

  async function askSecondStage(issueKey: string) {
    setBoBusy(issueKey)
    setError('')
    try {
      const res = await requestSecondStageApproval(issueKey)
      setBoDone((prev) => ({ ...prev, [issueKey]: `Asked ${res.approver ?? 'the approver'}` }))
    } catch (err: unknown) {
      setError(apiErrorMessage(err, `Could not ask for approval on ${issueKey}.`))
    } finally {
      setBoBusy(null)
    }
  }

  function toggleBo(st: string) {
    setBoFilter((cur) => (cur === st ? null : st))
  }

  // Posts when the dashboard has a Slack bot token; otherwise the message
  // comes back and goes on the clipboard, since Slack has no supported link
  // that prefills a channel composer.
  async function slackNudge(username: string) {
    // A nudge already went out, so the first click only arms a second one
    // instead of quietly messaging Hung twice.
    if (alreadyNudged(username) && slackArmed !== username) {
      setSlackArmed(username)
      return
    }
    setSlackArmed(null)
    setSlackBusy(username)
    setError('')
    try {
      const res = await sendCldsptSlackNudge(username)
      if (res.posted) {
        setSlackDone((p) => ({ ...p, [username]: `Posted to #${res.channel}` }))
      } else {
        try { await navigator.clipboard.writeText(res.message) } catch { /* clipboard blocked */ }
        setSlackDone((p) => ({ ...p, [username]: 'Copied, paste in Slack' }))
        window.open(res.channel_url, '_blank', 'noopener')
      }
    } catch (err: unknown) {
      setError(apiErrorMessage(err, `Could not build the Slack nudge for ${username}.`))
    } finally {
      setSlackBusy(null)
    }
  }

  /** Has Hung already been nudged for this engineer, by anyone, in the last week? */
  function alreadyNudged(username: string): boolean {
    return Boolean(queue?.last_nudged?.[username.toUpperCase()]) || username in slackDone
  }

  function nudgedWhen(username: string): string {
    const at = queue?.last_nudged?.[username.toUpperCase()]?.at
    if (!at) return 'in this session'
    const when = new Date(at)
    return Number.isNaN(when.getTime()) ? 'earlier' : when.toLocaleString()
  }

  function toggleStatus(b: string) {
    setStatusFilter((cur) => (cur === b ? null : b))
  }

  function toggleCategory(c: string) {
    setCategoryFilter((cur) => (cur === c ? null : c))
  }

  if (loading) {
    return (
      <div className="py-10 flex justify-center">
        <Loader2 className="animate-spin ds-u-color--muted" />
      </div>
    )
  }

  // Exact under any combination: the cross-tab carries category|bucket counts,
  // which marginal totals alone cannot answer when both filters are on.
  function countFor(e: CldsptEngineer): number {
    // The sweep records status and request type crossed, but not the approval
    // state, so a BO filter is counted off the live tickets when we have them
    // and off the sweep's own totals when we do not.
    if (boFilter) {
      const live = detail[e.username]?.tickets
      if (live) {
        return live.filter((t) => t.bo_approval?.state === boFilter
          && (!statusFilter || t.bucket === statusFilter)
          && (!categoryFilter || t.category === categoryFilter)).length
      }
      if (statusFilter || categoryFilter) return e.bo_approval?.[boFilter] ?? 0
      return e.bo_approval?.[boFilter] ?? 0
    }
    if (statusFilter && categoryFilter) return e.cross?.[`${categoryFilter}|${statusFilter}`] ?? 0
    if (statusFilter) return e.buckets?.[statusFilter] ?? 0
    if (categoryFilter) return e.categories?.[categoryFilter] ?? 0
    return e.open
  }

  const filtering = !!(statusFilter || categoryFilter || boFilter)
  const labels = queue?.bucket_labels ?? {}
  const byBucket = queue?.by_bucket ?? {}
  const allTime = queue?.all_time_total ?? 0
  const openTotal = queue?.open_total ?? 0
  const tp = queue?.throughput
  const count = (n?: number) => (n === undefined || n < 0 ? '—' : n)

  return (
    <section className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100 flex items-center gap-2">
            <Ticket size={16} /> GitHub access requests
          </h2>
          <p className="text-xs ds-u-color--muted mt-0.5">
            Every CLDSPT request in every status. Counts last swept {when(queue?.generated_at)}.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={sweeping}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          <RefreshCw size={13} className={sweeping ? 'animate-spin' : ''} />
          {sweeping ? 'Sweeping...' : 'Re-sweep'}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {queue?.error && !error && (
        <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          {queue.error} Use Re-sweep to build it.
        </div>
      )}

      {/* Statuses are read from Jira at sweep time, so a gap here means a count
          failed rather than a status being unknown. */}
      {!!queue?.unaccounted && (
        <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {queue.unaccounted} request{queue.unaccounted === 1 ? '' : 's'} could not be counted, so
          the breakdown below does not add up to {allTime}.
        </div>
      )}

      {/* The realistic case: a status new to the workflow is counted correctly
          but has no label here yet. */}
      {!!queue?.unmapped_statuses?.length && (
        <div className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Counted, but new to this page: {queue.unmapped_statuses.join(', ')}. The totals are
          right; these group under "Other" until they are given a label.
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
          <p className="text-xs ds-u-color--muted">All time</p>
          <p className="text-2xl font-semibold mt-1 text-gray-900 dark:text-gray-100">{allTime || '—'}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
          <p className="text-xs ds-u-color--muted">Still open</p>
          <p className="text-2xl font-semibold mt-1 text-amber-700">{openTotal || '—'}</p>
          <p className="text-xs ds-u-color--muted mt-0.5">{pct(openTotal, allTime)} of all time</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
          <p className="text-xs ds-u-color--muted">Waiting for approval</p>
          <p className="text-2xl font-semibold mt-1 text-amber-800">{byBucket.pending_approval ?? '—'}</p>
          <p className="text-xs ds-u-color--muted mt-0.5">
            {pct(byBucket.pending_approval ?? 0, openTotal)} of what is open
          </p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
          <p className="text-xs ds-u-color--muted">BO approval required</p>
          <p className="text-2xl font-semibold mt-1 text-red-700">
            {queue?.bo_approval_totals?.required ?? '—'}
          </p>
          <p className="text-xs ds-u-color--muted mt-0.5">
            nobody asked yet; {queue?.bo_approval_totals?.requested ?? 0} asked and waiting,{' '}
            {queue?.bo_approval_totals?.approved ?? 0} approved
            {!!queue?.bo_approval_totals?.not_required && (
              <>. {queue.bo_approval_totals.not_required} Copilot seat requests need no BO approval</>
            )}
            {!!queue?.application_blank && (
              <>
                . {queue.application_blank} have no Application Name
                {!!queue.application_inferred_confirmed && (
                  <> ({queue.application_inferred_confirmed} worked out from the ticket)</>
                )}
              </>
            )}
          </p>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
        <div className="flex items-center justify-between gap-3 mb-2.5">
          <p className="text-xs font-medium text-gray-700 dark:text-gray-200">
            By status{' '}
            <span className="font-normal ds-u-color--muted">
              (click to filter; finished statuses are not filterable)
            </span>
          </p>
          {filtering && (
            <button
              onClick={() => { setStatusFilter(null); setCategoryFilter(null); setBoFilter(null) }}
              className="text-xs text-cms-blue hover:underline"
            >
              Clear filters
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {[...OPEN_ORDER, ...DONE_ORDER]
            .filter((b) => byBucket[b])
            .map((b) => {
              // Status is point-in-time, so a status either holds open work or
              // it is a finished state. Only the former can filter a table that
              // carries open tickets.
              const filterable = ((queue?.by_bucket_open ?? {})[b] ?? 0) > 0
              const active = statusFilter === b
              return (
                <button
                  key={b}
                  onClick={() => filterable && toggleStatus(b)}
                  disabled={!filterable}
                  title={filterable ? `Filter to ${labels[b] ?? b}` : 'Nothing open in this status to filter by'}
                  className={`text-xs px-2.5 py-1 rounded-full border transition ${TONES[b] ?? TONES.other} ${
                    active ? 'ring-2 ring-offset-1 ring-cms-blue font-semibold' : ''
                  } ${filterable ? 'cursor-pointer hover:brightness-95' : 'cursor-default opacity-70'}`}
                >
                  {labels[b] ?? b}: <span className="font-semibold">{byBucket[b]}</span>
                </button>
              )
            })}
        </div>
      </div>

      {filtering && (
        <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300">
          <span>Showing only</span>
          {statusFilter && (
            <span className={`px-2 py-0.5 rounded-full border ${TONES[statusFilter] ?? TONES.other}`}>
              {labels[statusFilter] ?? statusFilter}
            </span>
          )}
          {categoryFilter && (
            <span className="px-2 py-0.5 rounded-full border border-gray-200 dark:border-gray-600">
              {(queue?.category_labels ?? {})[categoryFilter] ?? categoryFilter}
            </span>
          )}
          <button
            onClick={() => { setStatusFilter(null); setCategoryFilter(null); setBoFilter(null) }}
            className="text-cms-blue hover:underline"
          >
            Clear
          </button>
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 overflow-hidden">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-900/40">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted">Engineer</th>
              <th className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted">{filtering ? 'Matching' : 'Open'}</th>
              <th className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted">All time</th>
              <th
                className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted"
                title="Resolved or closed since the start of yesterday. Cancellations are not counted."
              >
                Completed
              </th>
              <th className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted">Open breakdown</th>
              <th className="px-3 py-2 text-left text-xs font-medium ds-u-color--muted">BO approval</th>
            </tr>
          </thead>
          <tbody>
            {(queue?.engineers ?? []).filter((e) => !filtering || countFor(e) > 0).map((e) => (
              <Fragment key={e.username}>
                <tr
                  onClick={() => toggle(e.username)}
                  className="border-t border-gray-100 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40"
                >
                  <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-100">
                    <span className="flex items-center gap-1.5">
                      {open === e.username ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      {e.name}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs font-semibold text-gray-900 dark:text-gray-100">{countFor(e)}</td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{e.all_time}</td>
                  <td className="px-3 py-2 text-xs font-semibold">
                    {e.completed_since_yesterday === undefined
                      ? <span className="ds-u-color--muted" title="Re-sweep to populate">—</span>
                      : e.completed_since_yesterday > 0
                        ? <span className="text-green-700">{e.completed_since_yesterday}</span>
                        : <span className="ds-u-color--muted">0</span>}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {OPEN_ORDER.filter((b) => e.buckets[b]).map((b) => (
                        <button
                          key={b}
                          onClick={(ev) => { ev.stopPropagation(); toggleStatus(b) }}
                          title={`Filter to ${labels[b] ?? b}`}
                          className={`text-xs px-2 py-0.5 rounded-full border transition hover:brightness-95 ${TONES[b] ?? TONES.other} ${
                            statusFilter === b ? 'ring-2 ring-offset-1 ring-cms-blue font-semibold' : ''
                          }`}
                        >
                          {labels[b] ?? b} {e.buckets[b]}
                        </button>
                      ))}
                      {!e.open && <span className="text-xs ds-u-color--muted">nothing open</span>}
                    </span>
                  </td>


                  <td className="px-3 py-2" onClick={(ev) => ev.stopPropagation()}>
                    <span className="flex flex-wrap items-center gap-1.5">
                      {(() => {
                        // Once the row is expanded we hold the engineer's live
                        // tickets, so count from those. The sweep runs daily and
                        // an approval landing since then would otherwise leave
                        // the chip claiming work that is already done.
                        const live = detail[e.username]?.tickets
                        const counts: Record<string, number> = live
                          ? live.reduce((acc: Record<string, number>, t) => {
                              const st = t.bo_approval?.state
                              if (st) acc[st] = (acc[st] ?? 0) + 1
                              return acc
                            }, {})
                          : (e.bo_approval ?? {})
                        const states = ['required', 'requested', 'bo_approved',
                                        'second_stage_requested', 'approved', 'not_required'] as const
                        const shown = states.filter((st) => counts[st])
                        if (shown.length === 0) {
                          return <span className="text-xs ds-u-color--muted">—</span>
                        }
                        return shown.map((st) => (
                          <button
                            key={st}
                            onClick={() => toggleBo(st)}
                            title={`${BO_HINTS[st]}. Click to filter.`}
                            className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                              boFilter === st ? 'ring-2 ring-cms-blue ' : ''}${BO_TONES[st]}`}
                          >
                            {BO_SHORT[st]} {counts[st]}
                          </button>
                        ))
                      })()}
                      {(e.bo_approval?.bo_approved || e.bo_approval?.second_stage_requested) && (
                        (() => {
                          const sent = alreadyNudged(e.username)
                          const armed = slackArmed === e.username
                          return (
                            <button
                              onClick={() => slackNudge(e.username)}
                              disabled={slackBusy === e.username}
                              title={armed
                                ? 'Click again to send Hung a second nudge'
                                : sent
                                  ? `Hung was already nudged for ${e.name} ${nudgedWhen(e.username)}. Click if you need to send another.`
                                  : `Nudge Hung Van on #github-access-approvals-internal with only ${e.name}'s tickets that the Business Owner has already approved`}
                              className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border disabled:opacity-50 ${
                                armed
                                  ? 'border-amber-400 bg-amber-50 text-amber-800 hover:bg-amber-100'
                                  : sent
                                    ? 'border-green-300 bg-green-50 text-green-800 hover:bg-green-100'
                                    : 'border-purple-300 bg-white text-purple-800 hover:bg-purple-50'}`}
                            >
                              {slackBusy === e.username
                                ? <Loader2 size={11} className="animate-spin" />
                                : sent && !armed
                                  ? <CheckCircle size={11} />
                                  : <MessageSquare size={11} />}
                              {armed ? 'Slack again?' : sent ? 'Hung slacked!' : 'Slack Hung'}
                            </button>
                          )
                        })()
                      )}
                      {slackDone[e.username] && (
                        <span className="text-xs text-green-700">{slackDone[e.username]}</span>
                      )}
                    </span>
                  </td>
                </tr>

                {open === e.username && (
                  <tr className="bg-gray-50 dark:bg-gray-900/30">
                    <td colSpan={6} className="px-3 py-3">
                      {detailLoading === e.username ? (
                        <span className="flex items-center gap-2 text-xs ds-u-color--muted">
                          <Loader2 size={13} className="animate-spin" /> Loading tickets...
                        </span>
                      ) : (detail[e.username]?.tickets ?? []).filter(
                            (t) => (!statusFilter || t.bucket === statusFilter)
                                && (!categoryFilter || t.category === categoryFilter)
                                && (!boFilter || t.bo_approval?.state === boFilter),
                          ).length === 0 ? (
                        <p className="text-xs ds-u-color--muted">
                          {filtering ? 'No requests match the current filter.' : 'No open requests.'}
                        </p>
                      ) : (
                        <div className="space-y-2">
                          {!!Object.keys(e.categories ?? {}).length && (
                            <div className="flex flex-wrap items-center gap-1.5 pb-1">
                              <span className="text-xs ds-u-color--muted mr-0.5">Request types:</span>
                              {Object.entries(e.categories)
                                .sort((a, b) => b[1] - a[1])
                                .map(([c, n]) => (
                                  <button
                                    key={c}
                                    onClick={() => toggleCategory(c)}
                                    title={`Filter to ${(queue?.category_labels ?? {})[c] ?? c}`}
                                    className={`text-xs px-2 py-0.5 rounded-full border transition hover:brightness-95 border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300 ${
                                      categoryFilter === c ? 'ring-2 ring-offset-1 ring-cms-blue font-semibold' : ''
                                    }`}
                                  >
                                    {(queue?.category_labels ?? {})[c] ?? c} {n}
                                  </button>
                                ))}
                            </div>
                          )}
                          {(detail[e.username]?.tickets ?? [])
                            .filter((t) => (!statusFilter || t.bucket === statusFilter)
                                        && (!categoryFilter || t.category === categoryFilter)
                                        && (!boFilter || t.bo_approval?.state === boFilter))
                            .map((t) => (
                            <div key={t.key} className="border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 bg-white dark:bg-gray-800">
                              <div className="flex items-start justify-between gap-3">
                                <a
                                  href={t.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  onClick={(ev) => ev.stopPropagation()}
                                  className="text-xs font-medium text-cms-blue hover:underline whitespace-nowrap"
                                >
                                  {t.key}
                                </a>
                                <span className="flex flex-wrap items-center justify-end gap-1.5">
                                  <ApplicationLabel ticket={t} />
                                  <span className="text-xs px-2 py-0.5 rounded-full border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300">
                                    {(queue?.category_labels ?? {})[t.category] ?? t.category}
                                  </span>
                                  <span className={`text-xs px-2 py-0.5 rounded-full border ${TONES[t.bucket] ?? TONES.other}`}>
                                    {t.status}
                                  </span>
                                </span>
                              </div>
                              <p className="text-xs text-gray-700 dark:text-gray-200 mt-1">{t.summary}</p>
                              <div className="flex flex-wrap items-center gap-2 mt-1.5">
                                {t.bo_approval?.state === 'not_required' ? (
                                  <span className="text-xs ds-u-color--muted">
                                    No BO approval needed for a Copilot seat
                                  </span>
                                ) : t.bo_approval?.state === 'approved' ? (
                                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-green-200 bg-green-50 text-green-800">
                                    <CheckCircle size={11} />
                                    Fully approved
                                    {t.bo_approval.second_stage_approved_by
                                      ? ` — ${t.bo_approval.second_stage_approved_by}`
                                      : ''}
                                    {t.bo_approval.second_stage_approved_on
                                      && ` on ${new Date(t.bo_approval.second_stage_approved_on).toLocaleDateString()}`}
                                  </span>
                                ) : (
                                  <>
                                    {/* The Business Owner signs off first. Only once that is
                                        on the ticket does the second stage become askable. */}
                                    {(t.bo_approval?.state === 'required'
                                      || t.bo_approval?.state === 'requested') && (
                                      <ApprovalButton
                                        stage="bo"
                                        ticket={t}
                                        busy={boBusy === t.key}
                                        done={boDone[t.key]}
                                        onRequest={() => askBoApproval(t.key)}
                                      />
                                    )}
                                    {(t.bo_approval?.state === 'bo_approved'
                                      || t.bo_approval?.state === 'second_stage_requested') && (
                                      <>
                                        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-green-200 bg-green-50 text-green-800">
                                          <CheckCircle size={11} />
                                          BO approved
                                          {t.bo_approval.approved_by && ` — ${t.bo_approval.approved_by}`}
                                        </span>
                                        <ApprovalButton
                                          stage="second"
                                          ticket={t}
                                          busy={boBusy === t.key}
                                          done={boDone[t.key]}
                                          onRequest={() => askSecondStage(t.key)}
                                        />
                                      </>
                                    )}
                                  </>
                                )}
                                {t.bo_approval?.state !== 'not_required' && (
                                  <span className="text-xs ds-u-color--muted">
                                    BO: {t.business_owner ?? 'not set'}
                                  </span>
                                )}
                              </div>
                              {t.latest_comment ? (
                                <p className="text-xs ds-u-color--muted mt-1.5">
                                  <span className="font-medium">
                                    {t.latest_comment.author ?? 'unknown'}
                                  </span>{' '}
                                  ({t.latest_comment.count} comment{t.latest_comment.count === 1 ? '' : 's'}):{' '}
                                  {t.latest_comment.body}
                                  {t.latest_comment.truncated && <span className="ds-u-color--muted"> [truncated]</span>}
                                </p>
                              ) : (
                                <p className="text-xs ds-u-color--muted mt-1.5">No comments yet.</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {tp && (
          <p className="px-3 py-2 text-[11px] ds-u-color--muted border-t border-gray-100 dark:border-gray-700">
            {count(tp.since_yesterday)} completed across the project since the start of yesterday
            {tp.today ? `, ${tp.today} of them today` : ', none yet today'}
            {!!tp.canceled_since_yesterday && <>. {tp.canceled_since_yesterday} canceled, not counted</>}
            . Per-engineer rows cover the team only, so they can add up to less.
          </p>
        )}
      </div>
    </section>
  )
}
