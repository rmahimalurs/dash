import { useState, useEffect, useRef } from 'react'
import {
  UserX, Loader2, RefreshCw, AlertTriangle, Trash2, ShieldCheck, ChevronLeft, ChevronRight,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getControllerUsersSummary, startControllerUsersSweep, getControllerUsersSweepStatus,
  auditControllerUsers, deleteControllerUsers, apiErrorMessage,
  type ControllerUserEnv, type ControllerUsersSummary, type ControllerSweepRow,
  type ControllerUserAudit, type ControllerUser, type ControllerUserDeleteResult,
} from '../../api/client'

const ENVS: { key: ControllerUserEnv; label: string }[] = [
  { key: 'prod-east', label: 'Prod East' },
  { key: 'gc-prod-west', label: 'GovCloud Prod (West)' },
]

const STATUS_META: Record<string, { label: string; cls: string }> = {
  disabled:  { label: 'Deactivated', cls: 'bg-red-100 text-red-700 border-red-200' },
  active:    { label: 'Active',      cls: 'bg-green-100 text-green-700 border-green-200' },
  not_found: { label: 'Not in AD',   cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  unknown:   { label: 'Unknown',     cls: 'bg-gray-100 ds-u-color--muted border-gray-200' },
  system:    { label: 'System',      cls: 'bg-slate-100 text-slate-500 border-slate-200' },
}

function ago(ts: number | null): string {
  if (!ts) return 'never'
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

export default function ControllerUserAuditWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<UserX size={20} className="text-white" />}
        label="Controller User Audit"
        description="Find controllers with deactivated (left-the-org) users and clean them up"
        color="bg-rose-600"
        onClick={() => setOpen(true)}
      />
      <AuditModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function AuditModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<ControllerUserEnv>('prod-east')
  const [summary, setSummary] = useState<ControllerUsersSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedController, setSelectedController] = useState<string | null>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    if (open) loadSummary(env)
    return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadSummary(e: ControllerUserEnv) {
    setLoading(true); setError(''); setSelectedController(null)
    try {
      const s = await getControllerUsersSummary(e)
      setSummary(s)
      if (s.sweep?.running) startPolling(e)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Could not load controller summary.'))
    } finally {
      setLoading(false)
    }
  }

  function startPolling(e: ControllerUserEnv) {
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      try {
        const st = await getControllerUsersSweepStatus(e)
        setSummary(prev => prev ? { ...prev, sweep: st } : prev)
        if (!st.running) {
          window.clearInterval(pollRef.current!)
          pollRef.current = null
          loadSummary(e) // pull fresh cache
        }
      } catch { /* keep polling */ }
    }, 3000)
  }

  async function runSweep() {
    setError('')
    try {
      await startControllerUsersSweep(env)
      setSummary(prev => prev ? { ...prev, sweep: { ...prev.sweep, running: true, done: 0, total: 0 } } : prev)
      startPolling(env)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Could not start sweep.'))
    }
  }

  function handleClose() {
    if (pollRef.current) window.clearInterval(pollRef.current)
    setSummary(null); setSelectedController(null); setError(''); onClose()
  }

  const sweeping = !!summary?.sweep?.running

  return (
    <Modal open={open} onClose={handleClose} title="Controller User Audit & Cleanup">
      {selectedController ? (
        <ControllerDetail
          env={env}
          controller={selectedController}
          onBack={() => { setSelectedController(null); loadSummary(env) }}
        />
      ) : (
        <div className="space-y-4">
          {/* Env picker + sweep control */}
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-sm font-medium text-gray-700">Environment</label>
            <select
              value={env}
              onChange={e => { const v = e.target.value as ControllerUserEnv; setEnv(v); loadSummary(v) }}
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
            >
              {ENVS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <div className="ml-auto flex items-center gap-2 text-xs ds-u-color--muted">
              {summary?.swept_at != null && <span>scanned {ago(summary.swept_at)}</span>}
              <button
                onClick={runSweep}
                disabled={sweeping}
                className="inline-flex items-center gap-1 text-rose-700 hover:text-rose-800 disabled:opacity-50"
              >
                <RefreshCw size={12} className={sweeping ? 'animate-spin' : ''} />
                {sweeping ? 'Scanning…' : 'Scan controllers'}
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}

          {sweeping && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" />
              Scanning controllers… {summary?.sweep?.done ?? 0}/{summary?.sweep?.total || '?'}
            </div>
          )}

          {loading && !sweeping && (
            <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" /> Loading…
            </div>
          )}

          {!loading && summary && summary.swept_at == null && !sweeping && (
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm ds-u-color--muted">
              No scan yet for this environment. Click <strong>Scan controllers</strong> to find
              controllers with deactivated users.
            </div>
          )}

          {!loading && summary && summary.swept_at != null && (
            summary.controllers.length === 0 ? (
              <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-6 text-center text-sm text-green-700">
                No controllers with deactivated users. 🎉
              </div>
            ) : (
              <div className="rounded-lg border border-gray-200 divide-y divide-gray-50 max-h-96 overflow-y-auto">
                {summary.controllers.map(c => (
                  <ControllerRow key={c.controller} row={c}
                    onClick={() => setSelectedController(c.controller)} />
                ))}
              </div>
            )
          )}
        </div>
      )}
    </Modal>
  )
}

function ControllerRow({ row, onClick }: { row: ControllerSweepRow; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className="w-full px-3 py-2.5 flex items-center gap-3 hover:bg-gray-50 text-left">
      <span className="inline-flex items-center justify-center min-w-[2rem] h-6 px-1.5 rounded-full bg-red-100 text-red-700 text-xs font-semibold">
        {row.deactivated}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-800 truncate">{row.controller}</p>
        <p className="text-[11px] ds-u-color--muted">
          {row.deactivated} deactivated of {row.total} users
          {row.error ? ' · scan error' : ''}
        </p>
      </div>
      <ChevronRight size={16} className="text-gray-300" />
    </button>
  )
}

function ControllerDetail({ env, controller, onBack }: {
  env: ControllerUserEnv; controller: string; onBack: () => void
}) {
  const [audit, setAudit] = useState<ControllerUserAudit | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirm, setConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [result, setResult] = useState<ControllerUserDeleteResult | null>(null)

  useEffect(() => { runAudit() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function runAudit() {
    setLoading(true); setError(''); setResult(null); setConfirm(false)
    try {
      const a = await auditControllerUsers(env, controller)
      setAudit(a)
      setSelected(new Set(a.users.filter(u => u.deactivated).map(u => u.id)))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Audit failed.'))
    } finally {
      setLoading(false)
    }
  }

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function handleDelete() {
    setDeleting(true); setError('')
    try {
      const res = await deleteControllerUsers(env, controller, [...selected])
      setResult(res)
      setConfirm(false)
      runAudit()
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Delete failed.'))
    } finally {
      setDeleting(false)
    }
  }

  const deactivatedSelected = audit
    ? audit.users.filter(u => u.deactivated && selected.has(u.id)).length : 0

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="inline-flex items-center gap-1 text-sm ds-u-color--muted hover:text-gray-700">
        <ChevronLeft size={15} /> All controllers
      </button>
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-800">{controller}</p>
        <button onClick={runAudit} disabled={loading}
          className="inline-flex items-center gap-1 text-xs ds-u-color--muted hover:text-gray-700">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Re-scan
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
          <AlertTriangle size={14} className="flex-shrink-0" /> {error}
        </div>
      )}
      {loading && (
        <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
          <Loader2 size={15} className="animate-spin" /> Listing users and checking AD…
        </div>
      )}
      {result && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Deleted {result.deleted.length} user{result.deleted.length === 1 ? '' : 's'}
          {result.refused && result.refused.length > 0 && <> · refused {result.refused.length} (not deactivated)</>}
          {result.failed.length > 0 && <> · {result.failed.length} failed</>}
        </div>
      )}

      {audit && !loading && (
        <>
          <div className="flex items-center gap-3 text-xs">
            <span className="text-gray-600"><strong>{audit.counts.total}</strong> users</span>
            <span className="text-red-700"><strong>{audit.counts.deactivated}</strong> deactivated</span>
            {audit.counts.unknown > 0 && <span className="ds-u-color--muted">{audit.counts.unknown} unknown (AD)</span>}
          </div>

          <div className="rounded-lg border border-gray-200 max-h-72 overflow-y-auto divide-y divide-gray-50">
            {audit.users.map(u => (
              <UserRow key={u.id} u={u} checked={selected.has(u.id)} onToggle={() => toggle(u.id)} />
            ))}
          </div>

          {!confirm ? (
            <button onClick={() => setConfirm(true)} disabled={deactivatedSelected === 0}
              className="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50">
              <Trash2 size={15} />
              Delete {deactivatedSelected} deactivated user{deactivatedSelected === 1 ? '' : 's'}
            </button>
          ) : (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 space-y-2">
              <p className="text-sm text-rose-800 flex items-center gap-1.5">
                <AlertTriangle size={15} /> Permanently delete {deactivatedSelected} user
                {deactivatedSelected === 1 ? '' : 's'} from <strong>{controller}</strong>?
              </p>
              <p className="text-[11px] text-rose-600">
                Only AD-deactivated accounts are removed; any active/unknown selection is refused server-side.
              </p>
              <div className="flex gap-2">
                <button onClick={() => setConfirm(false)} className="btn-secondary flex-1 flex items-center justify-center gap-1">
                  <ChevronLeft size={14} /> Cancel
                </button>
                <button onClick={handleDelete} disabled={deleting}
                  className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50">
                  {deleting ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                  Confirm delete
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function UserRow({ u, checked, onToggle }: { u: ControllerUser; checked: boolean; onToggle: () => void }) {
  const meta = STATUS_META[u.ad_status] ?? STATUS_META.unknown
  return (
    <label className={`px-3 py-2 flex items-center gap-2.5 ${u.deactivated ? 'bg-red-50/40' : ''} ${u.is_system ? 'opacity-60' : 'cursor-pointer'}`}>
      <input type="checkbox" checked={checked} disabled={!u.deactivated} onChange={onToggle}
        title={u.deactivated ? '' : 'Only deactivated users can be deleted'} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-800 truncate">{u.full_name}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${meta.cls}`}>{meta.label}</span>
        </div>
        <span className="text-[11px] ds-u-color--muted font-mono">{u.id}</span>
      </div>
    </label>
  )
}
