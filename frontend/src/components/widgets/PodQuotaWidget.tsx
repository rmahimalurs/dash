import { useState, useEffect } from 'react'
import {
  Boxes, Loader2, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight, ChevronDown,
  ArrowUpCircle, CheckCircle2, StopCircle,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getPodQuotaAudit, getRunningBuilds, increasePodQuota, abortRunningBuild, abortAllRunningBuilds,
  apiErrorMessage,
  type ControllerUserEnv, type PodQuotaAudit, type PodQuotaController,
  type RunningBuilds, type RunningBuild,
} from '../../api/client'

const ENVS: { key: ControllerUserEnv; label: string }[] = [
  { key: 'prod-east', label: 'Prod East' },
  { key: 'gc-prod-west', label: 'GovCloud Prod (West)' },
]

function dur(ms: number): string {
  const d = ms / 86400000
  if (d >= 1) return `${d.toFixed(1)}d`
  const h = ms / 3600000
  if (h >= 1) return `${h.toFixed(1)}h`
  return `${Math.round(ms / 60000)}m`
}

export default function PodQuotaWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<Boxes size={20} className="text-white" />}
        label="Pod Quota (fiftypods)"
        description="Audit the per-controller pod quota; free pods or raise the limit"
        color="bg-orange-600"
        onClick={() => setOpen(true)}
      />
      <QuotaModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function QuotaModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<ControllerUserEnv>('prod-east')
  const [audit, setAudit] = useState<PodQuotaAudit | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<PodQuotaController | null>(null)

  useEffect(() => { if (open) load(env) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  async function load(e: ControllerUserEnv) {
    setLoading(true); setError(''); setSelected(null)
    try { setAudit(await getPodQuotaAudit(e)) }
    catch (err: any) { setError(apiErrorMessage(err, 'Could not load quota audit.')) }
    finally { setLoading(false) }
  }

  function handleClose() { setAudit(null); setSelected(null); setError(''); onClose() }

  return (
    <Modal open={open} onClose={handleClose} title="CBJ Pod Quota — fiftypods">
      {selected ? (
        <ControllerDetail env={env} row={selected} capDefault={audit?.hard_cap ?? 100}
          onBack={() => { setSelected(null); load(env) }} />
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-sm font-medium text-gray-700">Environment</label>
            <div className="relative">
              <select className="border border-gray-300 rounded-lg pl-3 pr-8 py-1.5 text-sm appearance-none"
                value={env} onChange={e => { const v = e.target.value as ControllerUserEnv; setEnv(v); load(v) }}>
                {ENVS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
              </select>
              <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
            </div>
            <button onClick={() => load(env)} disabled={loading}
              className="ml-auto inline-flex items-center gap-1 text-xs ds-u-color--muted hover:text-gray-700">
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}
          {loading && (
            <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" /> Reading fiftypods quotas…
            </div>
          )}

          {audit && !loading && (
            <>
              <p className="text-xs ds-u-color--muted">
                {audit.controllers.length} controllers · <span className="text-red-700 font-medium">{audit.at_limit_count} at limit</span>. Sorted by least headroom.
              </p>
              <div className="rounded-lg border border-gray-200 divide-y divide-gray-50 max-h-96 overflow-y-auto">
                {audit.controllers.map(c => (
                  <QuotaRow key={c.controller} c={c} onClick={() => setSelected(c)} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

function QuotaRow({ c, onClick }: { c: PodQuotaController; onClick: () => void }) {
  const color = c.at_limit ? 'bg-red-500' : c.near_limit ? 'bg-amber-500' : 'bg-green-500'
  const badge = c.at_limit
    ? 'bg-red-100 text-red-700' : c.near_limit ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 ds-u-color--muted'
  return (
    <button onClick={onClick} className="w-full px-3 py-2.5 flex items-center gap-3 hover:bg-gray-50 text-left">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-800 truncate">{c.controller}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${badge}`}>{c.used}/{c.hard}</span>
        </div>
        <div className="h-1.5 mt-1 rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full ${color}`} style={{ width: `${Math.min(100, c.pct)}%` }} />
        </div>
      </div>
      <ChevronRight size={16} className="text-gray-300" />
    </button>
  )
}

function ControllerDetail({ env, row, capDefault, onBack }: {
  env: ControllerUserEnv; row: PodQuotaController; capDefault: number; onBack: () => void
}) {
  const [q, setQ] = useState<PodQuotaController>(row)
  const [builds, setBuilds] = useState<RunningBuilds | null>(null)
  const [loadingBuilds, setLoadingBuilds] = useState(false)
  const [newLimit, setNewLimit] = useState(Math.min(capDefault, row.hard + 10))
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => { loadBuilds() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadBuilds() {
    setLoadingBuilds(true); setError('')
    try { setBuilds(await getRunningBuilds(env, row.controller)) }
    catch (err: any) { setError(apiErrorMessage(err, 'Could not load running builds.')) }
    finally { setLoadingBuilds(false) }
  }

  async function doIncrease() {
    setBusy('increase'); setError(''); setMsg('')
    try {
      const r = await increasePodQuota(env, row.controller, newLimit)
      setQ({ ...q, hard: r.hard, used: r.used, at_limit: r.used >= r.hard })
      setMsg(`Quota raised ${r.previous_hard} → ${r.hard}.`)
    } catch (err: any) { setError(apiErrorMessage(err, 'Increase failed.')) }
    finally { setBusy('') }
  }

  async function doAbort(b: RunningBuild) {
    setBusy(`abort:${b.job}#${b.number}`); setError(''); setMsg('')
    try {
      const r = await abortRunningBuild(env, row.controller, b.job, b.number)
      if (r.aborted) {
        // Optimistically drop it — the build takes a moment to leave "building"
        // state, so an immediate re-list would still show it.
        setBuilds(prev => prev ? { ...prev, count: Math.max(0, prev.count - 1), builds: prev.builds.filter(x => !(x.job === b.job && x.number === b.number)) } : prev)
        setMsg(`Aborted ${decodeURIComponent(b.job)} #${b.number}.`)
      } else { setMsg(`Abort: ${r.result}`) }
    } catch (err: any) { setError(apiErrorMessage(err, 'Abort failed.')) }
    finally { setBusy('') }
  }

  async function doAbortAll(days: number) {
    const label = days === 0 ? 'ALL running builds' : `builds running longer than ${days} days`
    if (!window.confirm(`Abort ${label} on ${row.controller}? This cannot be undone.`)) return
    setBusy(`abortall:${days}`); setError(''); setMsg('')
    try {
      const r = await abortAllRunningBuilds(env, row.controller, days)
      setMsg(`Aborted ${r.aborted} build(s)${r.failed ? `, ${r.failed} failed` : ''}.`)
      setTimeout(loadBuilds, 1500)  // give Jenkins a moment to release the builds
    } catch (err: any) { setError(apiErrorMessage(err, 'Abort-all failed.')) }
    finally { setBusy('') }
  }

  const color = q.used >= q.hard ? 'bg-red-500' : q.used >= q.hard * 0.9 ? 'bg-amber-500' : 'bg-green-500'

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="inline-flex items-center gap-1 text-sm ds-u-color--muted hover:text-gray-700">
        <ChevronLeft size={15} /> All controllers
      </button>

      <div>
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-gray-800">{q.controller}</p>
          <span className="text-sm font-mono text-gray-600">{q.used}/{q.hard} pods</span>
        </div>
        <div className="h-2 mt-1 rounded-full bg-gray-100 overflow-hidden">
          <div className={`h-full ${color}`} style={{ width: `${Math.min(100, q.pct)}%` }} />
        </div>
      </div>

      {error && <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm"><AlertTriangle size={14} /> {error}</div>}
      {msg && <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 rounded-lg px-3 py-2 text-sm"><CheckCircle2 size={14} /> {msg}</div>}

      {/* Increase quota */}
      <div className="rounded-lg border border-gray-200 px-3 py-3">
        <p className="text-[11px] uppercase tracking-wide ds-u-color--muted font-semibold mb-2">Raise the limit</p>
        <div className="flex items-center gap-2">
          <input type="number" min={q.used + 1} max={capDefault} value={newLimit}
            onChange={e => setNewLimit(Number(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-24" />
          <button onClick={doIncrease} disabled={busy === 'increase' || newLimit <= q.hard || newLimit > capDefault}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-orange-600 text-white hover:bg-orange-700 disabled:opacity-50">
            {busy === 'increase' ? <Loader2 size={14} className="animate-spin" /> : <ArrowUpCircle size={14} />} Raise
          </button>
          <span className="text-[11px] ds-u-color--muted">max {capDefault}; must exceed current {q.hard}</span>
        </div>
      </div>

      {/* Running builds (kill candidates) */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <p className="text-[11px] uppercase tracking-wide ds-u-color--muted font-semibold">
            Running builds{builds ? ` (${builds.count})` : ''} — longest first
          </p>
          <button onClick={loadBuilds} disabled={loadingBuilds}
            className="inline-flex items-center gap-1 text-xs ds-u-color--muted hover:text-gray-700">
            <RefreshCw size={11} className={loadingBuilds ? 'animate-spin' : ''} /> Refresh
          </button>
        </div>
        <p className="text-[11px] ds-u-color--muted mb-2">Abort stuck builds to free agent pods and get back under quota.</p>
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-[11px] ds-u-color--muted mr-1">Bulk abort:</span>
          {[
            { label: 'All', days: 0 },
            { label: '> 30 days', days: 30 },
            { label: '> 20 days', days: 20 },
            { label: '> 10 days', days: 10 },
          ].map(o => (
            <button key={o.days} onClick={() => doAbortAll(o.days)} disabled={busy.startsWith('abortall')}
              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50">
              {busy === `abortall:${o.days}` ? <Loader2 size={11} className="animate-spin" /> : <StopCircle size={11} />}
              {o.label}
            </button>
          ))}
        </div>
        {loadingBuilds ? (
          <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted"><Loader2 size={15} className="animate-spin" /> Loading builds…</div>
        ) : (
          <div className="rounded-lg border border-gray-200 divide-y divide-gray-50 max-h-64 overflow-y-auto">
            {(builds?.builds ?? []).map(b => (
              <div key={`${b.job}#${b.number}`} className="px-3 py-2 flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <a href={b.url.startsWith('http') ? b.url : '#'} className="text-xs font-medium text-gray-800 truncate block" title={b.job}>
                    {decodeURIComponent(b.job)} <span className="ds-u-color--muted">#{b.number}</span>
                  </a>
                  <span className="text-[11px] ds-u-color--muted">running {dur(b.durationMs)}</span>
                </div>
                <button onClick={() => doAbort(b)} disabled={busy === `abort:${b.job}#${b.number}`}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-50 flex-shrink-0">
                  {busy === `abort:${b.job}#${b.number}` ? <Loader2 size={11} className="animate-spin" /> : <StopCircle size={11} />} Abort
                </button>
              </div>
            ))}
            {builds && builds.builds.length === 0 && <p className="px-3 py-3 text-sm ds-u-color--muted">No running builds.</p>}
          </div>
        )}
      </div>
    </div>
  )
}
