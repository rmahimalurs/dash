import { useState, FormEvent, useRef, useEffect } from 'react'
import {
  ShieldCheck, Loader2, AlertTriangle, ChevronDown, Info, Search, RefreshCw,
  CheckCircle2, XCircle,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getCloudBeesUserAccess, startCloudBeesAccessSweep, getCloudBeesAccessSweepStatus,
  type CloudBeesUserAccess, type ControllerUserEnv, apiErrorMessage,
} from '../../api/client'

const ENVS: { key: ControllerUserEnv; label: string }[] = [
  { key: 'prod-east', label: 'Prod East' },
  { key: 'gc-prod-west', label: 'GovCloud Prod (West)' },
]

const AD_META: Record<string, { label: string; cls: string }> = {
  disabled: { label: 'Deactivated', cls: 'bg-red-100 text-red-700' },
  active: { label: 'Active', cls: 'bg-green-100 text-green-700' },
  not_found: { label: 'Not in AD', cls: 'bg-amber-100 text-amber-700' },
  unknown: { label: 'AD unknown', cls: 'bg-gray-100 ds-u-color--muted' },
}

function ago(ts: number | null | undefined) {
  if (!ts) return 'never'
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export default function CloudBeesAccessWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<ShieldCheck size={20} className="text-white" />}
        label="Check User Access"
        description="Confirm a user's CloudBees access — controllers, groups, and roles"
        color="bg-sky-600"
        onClick={() => setOpen(true)}
      />
      <CloudBeesAccessModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function CloudBeesAccessModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<ControllerUserEnv>('prod-east')
  const [username, setUsername] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<CloudBeesUserAccess | null>(null)
  const [error, setError] = useState('')
  const [sweeping, setSweeping] = useState(false)
  const [sweepMsg, setSweepMsg] = useState('')
  const pollRef = useRef<number | null>(null)

  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  function handleClose() {
    if (pollRef.current) window.clearInterval(pollRef.current)
    setUsername(''); setSubmitting(false); setResult(null); setError(''); setSweeping(false); setSweepMsg('')
    onClose()
  }

  async function lookup(value: string) {
    const v = value.trim()
    setError(''); setResult(null)
    if (!v) { setError('Enter an EUA.'); return }
    setSubmitting(true)
    try {
      setResult(await getCloudBeesUserAccess(env, v))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Access lookup failed.'))
    } finally {
      setSubmitting(false)
    }
  }
  function handleSubmit(e: FormEvent) { e.preventDefault(); lookup(username) }

  async function runSweep() {
    setError('')
    try {
      await startCloudBeesAccessSweep(env)
      setSweeping(true); setSweepMsg('Scanning controllers…')
      if (pollRef.current) window.clearInterval(pollRef.current)
      pollRef.current = window.setInterval(async () => {
        try {
          const st = await getCloudBeesAccessSweepStatus(env)
          setSweepMsg(`Scanning controllers… ${st.done}/${st.total || '?'}`)
          if (!st.running) {
            window.clearInterval(pollRef.current!); pollRef.current = null
            setSweeping(false); setSweepMsg('Scan complete — search again for fresh results.')
            if (username.trim()) lookup(username)
          }
        } catch { /* keep polling */ }
      }, 3000)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Could not start scan.'))
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="CloudBees User Access">
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="label">Environment</label>
          <div className="relative">
            <select className="input-field pr-8 appearance-none" value={env}
              onChange={e => { setEnv(e.target.value as ControllerUserEnv); setResult(null) }}>
              {ENVS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div>
          <label className="label">Search by EUA</label>
          <div className="flex gap-2">
            <input type="text" className="input-field font-mono" value={username}
              onChange={e => { setUsername(e.target.value); setResult(null) }}
              placeholder="raax" autoComplete="off" autoFocus required />
            <button type="submit" disabled={submitting || !username.trim()}
              className="btn-primary flex items-center justify-center gap-2 px-4 whitespace-nowrap">
              {submitting ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
              {submitting ? 'Checking…' : 'Check'}
            </button>
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2">
          <Info size={13} className="flex-shrink-0 mt-0.5" />
          <span>Read-only. CloudBees access is granted by RBAC groups per controller; this lists every controller the user has a role on. Data is from a daily 5&nbsp;AM scan — use <em>Re-scan</em> for fresh results.</span>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <AlertTriangle size={14} className="flex-shrink-0" /> {error}
          </div>
        )}

        {result && <ResultView r={result} />}

        <div className="flex items-center justify-between text-xs ds-u-color--muted pt-1 border-t border-gray-100 dark:border-gray-700">
          <span>{result?.swept_at ? `scan: ${ago(result.swept_at)}` : ''} {sweepMsg}</span>
          <button type="button" onClick={runSweep} disabled={sweeping}
            className="inline-flex items-center gap-1 text-sky-700 hover:text-sky-800 disabled:opacity-50">
            <RefreshCw size={12} className={sweeping ? 'animate-spin' : ''} /> {sweeping ? 'Scanning…' : 'Re-scan'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function ResultView({ r }: { r: CloudBeesUserAccess }) {
  if (r.no_scan) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-800">
        {r.message} Click <strong>Re-scan</strong> below.
      </div>
    )
  }
  const ad = AD_META[r.ad_status || 'unknown'] ?? AD_META.unknown
  if (!r.found) {
    return (
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 flex items-start gap-3">
        <XCircle size={18} className="ds-u-color--muted flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm text-gray-700 dark:text-gray-300">{r.message}</p>
          <span className={`inline-block mt-1 text-[10px] px-1.5 py-0.5 rounded ${ad.cls}`}>{ad.label}</span>
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-900/20 p-3 flex items-start gap-2.5">
        <CheckCircle2 size={18} className="text-green-600 flex-shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">
            {r.eua}
            {r.global_admin && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">GLOBAL ADMIN</span>}
            <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded ${ad.cls}`}>{ad.label}</span>
          </p>
          <p className="text-xs ds-u-color--muted mt-0.5">{r.message}</p>
        </div>
      </div>

      {r.cjoc && (
        <div className={`rounded-lg border px-3 py-2 ${r.global_admin ? 'border-purple-200 bg-purple-50 dark:bg-purple-900/20' : 'border-gray-200 dark:border-gray-700'}`}>
          <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{r.cjoc.controller}</p>
          <div className="flex flex-wrap gap-1 mt-1">
            {r.cjoc.roles.map(role => (
              <span key={role} className="text-[11px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">{role}</span>
            ))}
            {r.cjoc.groups.map(g => (
              <span key={g} className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 ds-u-color--muted dark:bg-gray-700 dark:text-gray-300">{g}</span>
            ))}
          </div>
          {r.global_admin && <p className="text-[11px] text-purple-700 dark:text-purple-300 mt-1">Inherited by every controller in this environment.</p>}
        </div>
      )}

      {(r.controllers ?? []).length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide ds-u-color--muted font-semibold mb-1">
            Controllers ({r.controller_count})
          </p>
          <div className="rounded-lg border border-gray-200 dark:border-gray-700 max-h-64 overflow-y-auto divide-y divide-gray-50 dark:divide-gray-700">
            {(r.controllers ?? []).map(c => (
              <div key={c.controller} className="px-3 py-2">
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{c.controller}</p>
                <div className="flex flex-wrap gap-1 mt-1">
                  {c.roles.map(role => (
                    <span key={role} className="text-[11px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">{role}</span>
                  ))}
                  {c.groups.map(g => (
                    <span key={g} className="text-[11px] px-1.5 py-0.5 rounded bg-gray-100 ds-u-color--muted dark:bg-gray-700 dark:text-gray-300">{g}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
