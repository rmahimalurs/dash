import { useState, useEffect, useRef } from 'react'
import {
  HardDrive, Loader2, AlertTriangle, ChevronLeft, Copy, Check, Trash2, Eye, RefreshCw,
  Mail, ExternalLink,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import EmailHistory from './EmailHistory'
import {
  getPvcControllers, getPvcUsage, startPvcPrune, getPvcPruneStatus, emailPvcAdo, completePvcPrune,
  type PvcController, type PvcControllerList, type PvcUsage, type PvcPruneStatus, type PvcEmailResult, apiErrorMessage } from '../../api/client'

function fmtBytes(n: number): string {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1)
  return `${(n / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${u[i]}`
}

const CATEGORY_LABELS: Record<string, string> = {
  tmp: 'Temp files (tmp/)',
  caches: 'Caches (caches/)',
  workspaces: 'Workspaces (workspace/)',
  builds: 'Old build history (keep last N per job)',
  logs: 'Logs (logs/)',
}

export default function PvcCleanupWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<HardDrive size={20} className="text-white" />}
        label="Controller PVC Cleanup"
        description="Reclaim disk on controllers over the PVC alert threshold"
        color="bg-rose-500"
        onClick={() => setOpen(true)}
      />
      <PvcCleanupModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function PvcCleanupModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [list, setList] = useState<PvcControllerList | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [selected, setSelected] = useState<PvcController | null>(null)

  useEffect(() => {
    if (open && !list) loadList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function loadList() {
    setLoadingList(true)
    setLoadError('')
    try {
      setList(await getPvcControllers())
    } catch (e: any) {
      // Surface the failure instead of falling through to an empty "None over 80%"
      // state, which looks identical to genuinely clear and hides real errors
      // (e.g. a transient backend blip during a redeploy).
      setLoadError(apiErrorMessage(e, 'Could not load controllers — try Refresh.'))
      setList(null)
    } finally {
      setLoadingList(false)
    }
  }

  function handleClose() {
    setSelected(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Controller PVC Cleanup — prod-east" wide>
      {selected ? (
        <ControllerDetail controller={selected} onBack={() => setSelected(null)} />
      ) : (
        <ControllerList
          list={list}
          loading={loadingList}
          loadError={loadError}
          onRefresh={loadList}
          onSelect={setSelected}
        />
      )}
    </Modal>
  )
}

function ControllerRow({ c, onSelect }: { c: PvcController; onSelect: (c: PvcController) => void }) {
  const dot = c.status === 'crit' ? 'bg-rose-500' : 'bg-amber-500'
  const label = c.status === 'crit' ? 'Over threshold' : 'Approaching'
  return (
    <button
      onClick={() => onSelect(c)}
      className="w-full text-left p-3 rounded-lg border border-gray-100 dark:border-gray-700 hover:border-cms-blue/40 hover:shadow-sm transition"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium text-sm text-gray-900 dark:text-gray-100 flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${dot}`} /> {c.controller}
        </span>
        <span className={`text-xs font-medium ${c.status === 'crit' ? 'text-rose-600' : 'text-amber-600'}`}>{label}</span>
      </div>
      <div className="text-xs ds-u-color--muted">
        <code>{c.namespace}</code> · click for live usage & breakdown
      </div>
    </button>
  )
}

function ControllerList({
  list, loading, loadError, onRefresh, onSelect,
}: {
  list: PvcControllerList | null
  loading: boolean
  loadError?: string
  onRefresh: () => void
  onSelect: (c: PvcController) => void
}) {
  if (loading && !list) {
    return <div className="py-10 flex justify-center"><Loader2 className="animate-spin ds-u-color--muted" /></div>
  }
  // A failed fetch (loadError) or a handled backend error (list.error) both render
  // as an error with a Retry — never as an empty "None over 80%" state.
  const err = loadError || list?.error
  if (err) {
    return (
      <div className="space-y-3">
        <div className="p-4 rounded-lg bg-amber-50 text-amber-800 text-sm flex gap-2">
          <AlertTriangle size={18} className="shrink-0" /> {err}
        </div>
        <button onClick={onRefresh} disabled={loading} className="btn-secondary flex items-center gap-1 text-sm">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Retry
        </button>
      </div>
    )
  }
  const over = list?.over ?? []
  const approaching = list?.approaching ?? []
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs ds-u-color--muted">
          Cluster <code>{list?.cluster}</code> · crit ≥ {Math.round((list?.thresholds?.crit ?? 0.8) * 100)}% ·
          warn ≥ {Math.round((list?.thresholds?.warn ?? 0.75) * 100)}%
        </p>
        <button onClick={onRefresh} className="text-xs ds-u-color--muted hover:text-cms-blue flex items-center gap-1">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div>
        <p className="text-xs font-semibold text-rose-600 uppercase tracking-wide mb-2">
          Over threshold ({over.length})
        </p>
        {over.length === 0
          ? <p className="text-sm ds-u-color--muted">None over {Math.round((list?.thresholds?.crit ?? 0.8) * 100)}%.</p>
          : <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{over.map(c => <ControllerRow key={c.namespace} c={c} onSelect={onSelect} />)}</div>}
      </div>

      <div>
        <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">
          Approaching ({approaching.length})
        </p>
        {approaching.length === 0
          ? <p className="text-sm ds-u-color--muted">None in the warn band.</p>
          : <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{approaching.map(c => <ControllerRow key={c.namespace} c={c} onSelect={onSelect} />)}</div>}
      </div>
    </div>
  )
}

function ControllerDetail({ controller, onBack }: { controller: PvcController; onBack: () => void }) {
  const [usage, setUsage] = useState<PvcUsage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [cats, setCats] = useState<Set<string>>(new Set())
  const [keepBuilds, setKeepBuilds] = useState(10)
  const [message, setMessage] = useState('')
  const [copied, setCopied] = useState(false)
  const [adoConfirmed, setAdoConfirmed] = useState(false)
  const [ado, setAdo] = useState('')
  const [status, setStatus] = useState<PvcPruneStatus | null>(null)
  const [runKind, setRunKind] = useState<'preview' | 'prune' | null>(null)
  const [busy, setBusy] = useState(false)
  const [emailing, setEmailing] = useState(false)
  const [emailResult, setEmailResult] = useState<PvcEmailResult | null>(null)
  const [cldspt, setCldspt] = useState<{ key: string; url: string; assignee?: string } | null>(null)
  const [cldsptError, setCldsptError] = useState('')
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cldsptRef = useRef<{ key: string; url: string; assignee?: string } | null>(null)
  const commentedRef = useRef(false)

  const emailAdmins = usage?.admins.filter(a => a.email) ?? []

  useEffect(() => {
    let alive = true
    setLoading(true); setError('')
    getPvcUsage(controller.controller)
      .then(u => {
        if (!alive) return
        setUsage(u)
        setMessage(u.ado_message || '')
        setCats(new Set(u.suggested_categories.filter(c => c.cleanable).map(c => c.category)))
        const firstAdo = u.admins.find(a => a.email)
        setAdo(firstAdo?.slack_name || firstAdo?.sid || '')
      })
      .catch(e => alive && setError(apiErrorMessage(e, 'Failed to load usage.')))
      .finally(() => alive && setLoading(false))
    return () => { alive = false; if (pollRef.current) clearTimeout(pollRef.current) }
  }, [controller.controller])

  // Poll the controller's prune-status marker until the run settles.
  function poll() {
    pollRef.current = setTimeout(async () => {
      try {
        const s = await getPvcPruneStatus(controller.controller)
        setStatus(s)
        if (s.state === 'running') { poll(); return }
        // On a real prune completing, record the freed space on its CLDSPT
        // ticket exactly once.
        if (s.state === 'done' && !s.dryRun && cldsptRef.current && !commentedRef.current) {
          commentedRef.current = true
          completePvcPrune(controller.controller, {
            ticket_key: cldsptRef.current.key,
            reclaimed_bytes: s.reclaimedBytes ?? s.total_bytes ?? 0,
            items: s.total_items ?? 0,
            report: s.report,
          }).catch(() => { /* comment is best-effort; ticket already exists */ })
        }
      } catch (e: any) {
        setError(apiErrorMessage(e, 'Status poll failed.'))
      }
      setBusy(false)  // done / error / idle
    }, 3000)
  }

  async function sendEmail() {
    setEmailing(true); setEmailResult(null)
    try {
      setEmailResult(await emailPvcAdo(controller.controller))
    } catch (e: any) {
      setEmailResult({ sent: false, error: apiErrorMessage(e, 'Email failed to send.') })
    } finally {
      setEmailing(false)
    }
  }

  async function launch(dryRun: boolean) {
    if (!dryRun && !adoConfirmed) return
    if (pollRef.current) clearTimeout(pollRef.current)
    setBusy(true); setError(''); setStatus(null); setRunKind(dryRun ? 'preview' : 'prune')
    if (!dryRun) { setCldspt(null); setCldsptError(''); cldsptRef.current = null; commentedRef.current = false }
    try {
      const start = await startPvcPrune(controller.controller, {
        categories: [...cats], ado_confirmed: true, ado: ado || null, keep_builds: keepBuilds, dry_run: dryRun,
        pct: usage?.pct,
      })
      if (!dryRun) {
        if (start.cldspt) { setCldspt(start.cldspt); cldsptRef.current = start.cldspt }
        if (start.cldspt_error) setCldsptError(start.cldspt_error)
        if (start.cldspt_assign_error) setCldsptError(start.cldspt_assign_error)
      }
      setStatus({ state: start.state === 'already_running' ? 'running' : 'running', progress: start.progress, error: null })
      poll()
    } catch (e: any) {
      setError(apiErrorMessage(e, (dryRun ? 'Preview failed.' : 'Prune failed.')))
      setBusy(false)
    }
  }

  function toggle(cat: string) {
    setCats(prev => {
      const n = new Set(prev)
      n.has(cat) ? n.delete(cat) : n.add(cat)
      return n
    })
  }

  async function copyMessage() {
    await navigator.clipboard.writeText(message)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin ds-u-color--muted" /></div>

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-xs ds-u-color--muted hover:text-cms-blue flex items-center gap-1">
        <ChevronLeft size={14} /> Back to controllers
      </button>

      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold text-gray-900 dark:text-gray-100">{controller.controller}</p>
          <p className="text-xs ds-u-color--muted"><code>{usage?.jenkins_home}</code></p>
        </div>
        <span className={`text-lg font-bold ${controller.status === 'crit' ? 'text-rose-600' : 'text-amber-600'}`}>
          {usage?.pct ?? '—'}%
        </span>
      </div>

      {usage?.disk_usage_source !== 'plugin' && (
        <div className="p-3 rounded-lg bg-amber-50 text-amber-800 text-xs flex gap-2">
          <AlertTriangle size={16} className="shrink-0" />
          Disk-usage breakdown unavailable ({usage?.disk_usage_source}). Install the
          <code className="mx-1">cloudbees-disk-usage-simple</code> plugin on this controller for a full breakdown.
          {usage?.disk_usage_error && <span className="block opacity-70">{usage.disk_usage_error}</span>}
        </div>
      )}

      {/* Disk breakdown */}
      {usage && usage.top_jobs.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide mb-2">Top consumers</p>
          <div className="space-y-1">
            {usage.top_jobs.slice(0, 8).map(j => (
              <div key={j.name} className="flex items-center justify-between text-xs">
                <span className="truncate mr-2 text-gray-700 dark:text-gray-300">{j.name}</span>
                <span className="ds-u-color--muted shrink-0">{fmtBytes(j.bytes)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Cleanup categories */}
      <div>
        <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide mb-2">What to clean</p>
        <div className="space-y-1">
          {['tmp', 'caches', 'workspaces', 'builds', 'logs'].map(cat => {
            const sug = usage?.suggested_categories.find(s => s.category === cat)
            return (
              <label key={cat} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={cats.has(cat)} onChange={() => toggle(cat)} />
                <span className="flex-1">{CATEGORY_LABELS[cat]}</span>
                {sug && <span className="text-xs ds-u-color--muted">{fmtBytes(sug.bytes)}</span>}
              </label>
            )
          })}
        </div>
        {cats.has('builds') && (
          <label className="flex items-center gap-2 text-xs text-gray-600 mt-2">
            Keep last
            <input
              type="number" min={1} value={keepBuilds}
              onChange={e => setKeepBuilds(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-16 border rounded px-1 py-0.5 dark:bg-gray-700"
            />
            builds per job
          </label>
        )}
      </div>

      {/* ADO notify */}
      <div className="border-t pt-3">
        <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide mb-2">
          1. Get ADO sign-off
        </p>
        {(() => {
          const slackAdmins = usage?.admins.filter(a => a.slack_handle) ?? []
          const emailAdmins = usage?.admins.filter(a => a.email) ?? []
          // Prefer admins we can reach on Slack; only fall back to emails when none resolve.
          if (slackAdmins.length > 0) {
            return (
              <div className="text-xs text-gray-600 dark:text-gray-300 mb-2 space-y-0.5">
                {slackAdmins.map(a => (
                  <div key={a.sid}>
                    <span className="font-medium">{a.slack_name || a.sid}</span>
                    <span className="text-cms-blue"> · @{a.slack_handle}</span>
                  </div>
                ))}
              </div>
            )
          }
          if (emailAdmins.length > 0) {
            return (
              <div className="text-xs text-gray-600 dark:text-gray-300 mb-2 space-y-0.5">
                <p className="text-amber-600 mb-1">No admins matched on Slack — contact the ADO by email:</p>
                {emailAdmins.map(a => (
                  <div key={a.sid}>{a.slack_name || a.sid} · <span className="ds-u-color--muted">{a.email}</span></div>
                ))}
              </div>
            )
          }
          return (
            <p className="text-xs text-amber-600 mb-2">
              {usage?.admin_discovery_error || 'No admins discovered — enter the ADO manually.'}
            </p>
          )
        })()}
        <textarea
          value={message} onChange={e => setMessage(e.target.value)} rows={6}
          className="w-full text-xs border rounded p-2 dark:bg-gray-700 font-mono"
        />
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <button onClick={copyMessage} className="btn-secondary flex items-center gap-1 text-sm">
            {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy message'}
          </button>
          <button
            onClick={sendEmail}
            disabled={emailing || emailAdmins.length === 0}
            title={emailAdmins.length === 0 ? 'No ADO email addresses resolved for this controller' : 'Email the analysis to the ADOs'}
            className="btn-secondary flex items-center gap-1 text-sm disabled:opacity-40"
          >
            {emailing ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
            Email ADOs{emailAdmins.length > 0 ? ` (${emailAdmins.length})` : ''}
          </button>
        </div>
        {emailResult && (
          emailResult.sent ? (
            <p className="text-xs text-green-700 mt-2 flex items-start gap-1">
              <Check size={13} className="shrink-0 mt-0.5" />
              Sent to {emailResult.to?.join(', ')}
              {emailResult.cc && emailResult.cc.length > 0 && <> · cc {emailResult.cc.join(', ')}</>}
              {emailResult.notice_ordinal != null && emailResult.notice_ordinal >= 2 && (
                <span className="font-medium text-amber-700"> · {emailResult.notice_ordinal === 2 ? 'Second Notice' : 'Final Notice'}</span>
              )}
            </p>
          ) : (
            <p className="text-xs text-rose-600 mt-2 flex items-start gap-1">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {emailResult.error}
            </p>
          )
        )}
        {emailResult?.excluded_deactivated && emailResult.excluded_deactivated.length > 0 && (
          <p className="text-[11px] ds-u-color--muted mt-1">
            Excluded {emailResult.excluded_deactivated.length} deactivated ADO:{' '}
            {emailResult.excluded_deactivated.map(e => e.name || e.sid).join(', ')}
          </p>
        )}
        <EmailHistory history={emailResult?.email_history ?? usage?.email_history} />
      </div>

      {/* Confirm + prune */}
      <div className="border-t pt-3">
        <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide mb-2">
          2. Confirm & prune
        </p>
        <div className="flex gap-2 mb-3">
          <button onClick={() => launch(true)} disabled={busy || cats.size === 0} className="btn-secondary flex items-center gap-1 text-sm">
            {busy && runKind === 'preview' ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />} Preview (dry run)
          </button>
        </div>

        <label className="flex items-start gap-2 text-sm mb-2">
          <input type="checkbox" checked={adoConfirmed} onChange={e => setAdoConfirmed(e.target.checked)} className="mt-1" />
          <span>I have sent the message above and the ADO
            <input
              value={ado} onChange={e => setAdo(e.target.value)} placeholder="ADO name"
              className="mx-1 border rounded px-1 py-0.5 text-xs dark:bg-gray-700 w-32"
            />
            has approved this cleanup.</span>
        </label>
        <button
          onClick={() => launch(false)}
          disabled={!adoConfirmed || busy || cats.size === 0}
          className="btn-danger w-full flex items-center justify-center gap-2 disabled:opacity-40"
        >
          {busy && runKind === 'prune' ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
          Prune {cats.size} categor{cats.size === 1 ? 'y' : 'ies'} on {controller.controller}
        </button>
        <p className="text-[11px] ds-u-color--muted mt-1">
          Preview is always safe (deletes nothing). Actual pruning also requires the server-side
          <code className="mx-1">PVC_PRUNE_ENABLED</code> flag; until an admin sets it, Prune returns a disabled notice.
        </p>
        {cldspt && (
          <p className="text-xs text-cms-blue mt-2 flex items-center gap-1">
            <ExternalLink size={13} className="shrink-0" />
            Documented in{' '}
            <a href={cldspt.url} target="_blank" rel="noreferrer" className="font-medium underline">{cldspt.key}</a>
            {cldspt.assignee && <span className="ds-u-color--muted">{' '}· assigned to {cldspt.assignee}</span>}
          </p>
        )}
        {cldsptError && (
          <p className="text-xs text-amber-600 mt-2 flex items-start gap-1">
            <AlertTriangle size={13} className="shrink-0 mt-0.5" /> {cldsptError}
          </p>
        )}
      </div>

      {/* Live run progress / result */}
      {status && <PruneStatusPanel status={status} runKind={runKind} />}

      {error && (
        <div className="p-3 rounded-lg bg-rose-50 text-rose-700 text-sm flex gap-2">
          <AlertTriangle size={16} className="shrink-0" /> {error}
        </div>
      )}
    </div>
  )
}

function PruneStatusPanel({ status, runKind }: { status: PvcPruneStatus; runKind: 'preview' | 'prune' | null }) {
  const p = status.progress
  const dry = status.dryRun ?? runKind === 'preview'
  if (status.state === 'running') {
    return (
      <div className="p-3 rounded-lg bg-blue-50 text-blue-800 text-sm">
        <p className="font-semibold flex items-center gap-2">
          <Loader2 size={14} className="animate-spin" /> {dry ? 'Scanning' : 'Pruning'}…
          {status.stale && <span className="text-amber-600 text-xs">(no update in 2 min — may be stalled)</span>}
        </p>
        {p && (
          <p className="text-xs mt-1">
            {p.totalJobs > 0 && <>jobs {p.jobsProcessed}/{p.totalJobs} · </>}
            {dry ? 'builds to remove' : 'builds removed'}: {p.buildsDeleted}
            {p.filesCleared > 0 && <> · files cleared: {p.filesCleared}</>}
          </p>
        )}
      </div>
    )
  }
  if (status.state === 'done') {
    const items = status.total_items ?? 0
    return (
      <div className="p-3 rounded-lg bg-green-50 text-green-800 text-sm">
        <p className="font-semibold">
          {dry
            ? `Dry run complete — ${items} item(s) would be removed`
            : `Prune complete — freed ${fmtBytes(status.total_bytes ?? 0)} (${items} item(s) removed)`}
        </p>
        {status.report && (
          <div className="text-xs mt-1 text-green-700">
            {Object.entries(status.report).map(([k, v]) => (
              <span key={k} className="mr-3">· {k}: {v.items ?? 0}</span>
            ))}
          </div>
        )}
        {!dry && status.freeAfter != null && (
          <p className="text-xs mt-1">Free space now: {fmtBytes(status.freeAfter)}</p>
        )}
      </div>
    )
  }
  if (status.state === 'error') {
    return (
      <div className="p-3 rounded-lg bg-rose-50 text-rose-700 text-sm flex gap-2">
        <AlertTriangle size={16} className="shrink-0" /> Run failed: {status.error}
      </div>
    )
  }
  return null
}
