import { useState, useEffect } from 'react'
import {
  MailWarning, Loader2, ChevronLeft, Copy, Check, Mail, RefreshCw, AlertTriangle, ChevronRight,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import EmailHistory from './EmailHistory'
import {
  getCbjWasteTeams, getCbjTeamAdos, emailCbjWasteAdo, apiErrorMessage,
  type CbjEnv, type CbjAnalysisTarget, type CbjWasteTeam, type CbjWasteTeamList,
  type CbjTeamAdos, type CbjWasteEmailResult,
} from '../../api/client'

const ENVS: { key: CbjEnv; label: string }[] = [
  { key: 'prod-east', label: 'Prod East' },
  { key: 'gc-prod-west', label: 'GovCloud Prod (West)' },
]
const TARGETS: { key: CbjAnalysisTarget; label: string }[] = [
  { key: 'agents', label: 'Build/Agent podTemplates' },
  { key: 'controllers', label: 'Controllers' },
]

function n(v: number | null, d = 2): string {
  return v == null ? '—' : v.toFixed(d)
}
function pct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

export default function CbjWasteEmailWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<MailWarning size={20} className="text-white" />}
        label="CBJ Resource-Waste Email"
        description="Email ADO teams whose podTemplates over-reserve CPU/memory"
        color="bg-amber-500"
        onClick={() => setOpen(true)}
      />
      <WasteModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function WasteModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<CbjEnv>('prod-east')
  const [target, setTarget] = useState<CbjAnalysisTarget>('agents')
  const [list, setList] = useState<CbjWasteTeamList | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [selected, setSelected] = useState<CbjWasteTeam | null>(null)

  async function loadList() {
    setLoading(true); setLoadError(''); setSelected(null)
    try {
      setList(await getCbjWasteTeams(env, target))
    } catch (e: any) {
      setLoadError(apiErrorMessage(e, 'Could not load waste data — try Refresh.'))
      setList(null)
    } finally {
      setLoading(false)
    }
  }

  // Reload whenever the modal opens or the env/target selection changes.
  useEffect(() => {
    if (open) loadList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, env, target])

  function handleClose() {
    setSelected(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="CBJ Resource-Waste Email" wide>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="flex items-center gap-2 text-sm">
          <span className="ds-u-color--muted">Environment</span>
          <select
            value={env}
            onChange={(e) => setEnv(e.target.value as CbjEnv)}
            className="border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-white text-gray-800 focus:outline-none focus:ring-2 focus:ring-cms-blue"
          >
            {ENVS.map((e) => <option key={e.key} value={e.key}>{e.label}</option>)}
          </select>
        </label>
        <div className="flex gap-1 border border-gray-200 rounded-md p-0.5">
          {TARGETS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTarget(t.key)}
              className={`px-3 py-1 text-xs font-medium rounded ${
                target === t.key ? 'bg-cms-blue text-white' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        {!selected && (
          <button onClick={loadList} disabled={loading} className="ml-auto text-xs ds-u-color--muted hover:text-cms-blue flex items-center gap-1">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
        )}
      </div>

      {selected ? (
        <TeamDetail env={env} target={target} team={selected} onBack={() => setSelected(null)} />
      ) : (
        <TeamList list={list} loading={loading} loadError={loadError} onSelect={setSelected} />
      )}
    </Modal>
  )
}

function TeamList({
  list, loading, loadError, onSelect,
}: {
  list: CbjWasteTeamList | null
  loading: boolean
  loadError: string
  onSelect: (t: CbjWasteTeam) => void
}) {
  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin ds-u-color--muted" /></div>
  if (loadError) return <div className="py-8 text-center text-sm text-red-600">{loadError}</div>
  const teams = list?.teams ?? []
  if (teams.length === 0) return <div className="py-8 text-center text-sm ds-u-color--muted">No over-provisioned teams found for this environment.</div>

  return (
    <div className="space-y-2">
      <p className="text-xs ds-u-color--muted mb-2">
        Teams reserving far more than they use, worst first. {!list?.resolvable_ados &&
          <span className="text-amber-600">ADO emails aren&apos;t auto-resolved for this environment — you&apos;ll enter recipients manually.</span>}
      </p>
      {teams.map((t) => (
        <button
          key={t.namespace}
          onClick={() => onSelect(t)}
          className="w-full flex items-center justify-between gap-3 px-4 py-3 border border-gray-100 rounded-lg hover:bg-gray-50 text-left transition-colors"
        >
          <div className="flex items-center gap-3 min-w-0">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${t.worst_status === 'critical' ? 'bg-red-500' : 'bg-amber-500'}`} />
            <div className="min-w-0">
              <div className="font-medium text-gray-800 truncate">{t.namespace}</div>
              <div className="text-xs ds-u-color--muted">
                {t.container_count} container{t.container_count === 1 ? '' : 's'} · ~{n(t.total_cpu_wasted_cores)} CPU cores + {n(t.total_mem_wasted_gb)} GB wasted
              </div>
            </div>
          </div>
          <ChevronRight size={16} className="ds-u-color--muted flex-shrink-0" />
        </button>
      ))}
    </div>
  )
}

function TeamDetail({
  env, target, team, onBack,
}: {
  env: CbjEnv
  target: CbjAnalysisTarget
  team: CbjWasteTeam
  onBack: () => void
}) {
  const [data, setData] = useState<CbjTeamAdos | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [extraEmails, setExtraEmails] = useState('')
  const [emailing, setEmailing] = useState(false)
  const [result, setResult] = useState<CbjWasteEmailResult | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true); setError(''); setResult(null)
    getCbjTeamAdos(env, team.namespace, target)
      .then((d) => { if (!cancelled) { setData(d); setExtraEmails('') } })
      .catch((e: any) => { if (!cancelled) setError(apiErrorMessage(e, 'Could not resolve ADOs.')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [env, target, team.namespace])

  const resolvedEmails = (data?.admins ?? []).filter((a) => a.email)
  const manualList = extraEmails.split(',').map((s) => s.trim()).filter(Boolean)
  const canSend = resolvedEmails.length > 0 || manualList.length > 0

  async function copyMessage() {
    if (!data) return
    await navigator.clipboard.writeText(data.ado_message)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  async function sendEmail() {
    setEmailing(true); setResult(null)
    try {
      setResult(await emailCbjWasteAdo(env, team.namespace, target, manualList))
    } catch (e: any) {
      setResult({ sent: false, error: apiErrorMessage(e, 'Email failed to send.') })
    } finally {
      setEmailing(false)
    }
  }

  if (loading) return <div className="py-10 flex justify-center"><Loader2 className="animate-spin ds-u-color--muted" /></div>

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="text-xs ds-u-color--muted hover:text-cms-blue flex items-center gap-1">
        <ChevronLeft size={14} /> Back to teams
      </button>

      <div>
        <h3 className="font-semibold text-gray-800">{team.namespace}</h3>
        <p className="text-xs ds-u-color--muted">Controller <span className="font-mono">{data?.controller}</span> · {env}</p>
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}

      {/* Wasteful containers */}
      <div className="overflow-x-auto border border-gray-100 rounded-lg">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-xs ds-u-color--muted">
              <th className="px-3 py-2 text-left font-medium">Container</th>
              <th className="px-3 py-2 text-right font-medium">CPU res</th>
              <th className="px-3 py-2 text-right font-medium">CPU peak</th>
              <th className="px-3 py-2 text-right font-medium">CPU wasted</th>
              <th className="px-3 py-2 text-right font-medium">Mem res/used</th>
              <th className="px-3 py-2 text-right font-medium">Disk req/limit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {(data?.rows ?? []).map((r) => (
              <tr key={r.container}>
                <td className="px-3 py-2 font-mono text-xs text-gray-800">{r.container}</td>
                <td className="px-3 py-2 text-right text-gray-600">{n(r.cpu_reserved_cores)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{n(r.cpu_used_at_peak_cores)} ({pct(r.cpu_pct_used)})</td>
                <td className={`px-3 py-2 text-right font-semibold ${r.status === 'critical' ? 'text-red-700' : 'text-yellow-700'}`}>{n(r.cpu_wasted_cores)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{n(r.mem_reserved_gb)} / {n(r.mem_used_at_peak_gb)} GB</td>
                <td className="px-3 py-2 text-right text-gray-600">{r.disk_request ?? '—'} / {r.disk_limit ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Resolved ADOs */}
      <div>
        <div className="text-xs font-medium text-gray-600 mb-1">Recipients (ADO admins)</div>
        {data?.note && <div className="text-xs text-amber-600 flex items-center gap-1 mb-1"><AlertTriangle size={12} /> {data.note}</div>}
        {resolvedEmails.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {resolvedEmails.map((a) => (
              <span key={a.sid} className="inline-flex items-center px-2 py-0.5 rounded bg-gray-100 text-xs text-gray-700">
                {a.slack_name || a.sid} &lt;{a.email}&gt;
              </span>
            ))}
          </div>
        ) : (
          <div className="text-xs ds-u-color--muted">
            {data?.admin_discovery_error ? `No ADOs auto-resolved (${data.admin_discovery_error}).` : 'No ADO emails auto-resolved.'}
          </div>
        )}
        <input
          type="text"
          value={extraEmails}
          onChange={(e) => setExtraEmails(e.target.value)}
          placeholder={resolvedEmails.length ? 'Add more recipients (comma-separated, optional)' : 'Enter recipient email(s), comma-separated'}
          className="mt-2 w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-cms-blue"
        />
      </div>

      {/* Drafted Slack/copy message */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-gray-600">Message to copy (Slack / manual)</span>
          <button onClick={copyMessage} className="text-xs ds-u-color--muted hover:text-cms-blue flex items-center gap-1">
            {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
          </button>
        </div>
        <textarea
          readOnly
          value={data?.ado_message ?? ''}
          rows={7}
          className="w-full border border-gray-200 rounded-md px-3 py-2 text-xs font-mono text-gray-700 bg-gray-50 resize-y"
        />
      </div>

      {/* Send */}
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={sendEmail}
          disabled={emailing || !canSend}
          className="btn-primary flex items-center gap-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {emailing ? <Loader2 size={15} className="animate-spin" /> : <Mail size={15} />}
          Email ADOs{canSend ? ` (${resolvedEmails.length + manualList.length})` : ''}
        </button>
        <span className="text-xs ds-u-color--muted">cc: CMS Cloud DevOps distro. A formatted HTML analysis is sent.</span>
      </div>

      {result && (
        <div className={`text-sm rounded-md px-3 py-2 ${result.sent ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>
          {result.sent ? (
            <>
              Sent to {(result.to ?? []).join(', ')}{result.cc?.length ? ` (cc ${result.cc.join(', ')})` : ''}.
              {result.notice_ordinal != null && result.notice_ordinal >= 2 && (
                <span className="font-medium text-amber-700"> · {result.notice_ordinal === 2 ? 'Second Notice' : 'Final Notice'}</span>
              )}
            </>
          ) : (
            result.error || 'Email failed to send.'
          )}
          {result.excluded_deactivated && result.excluded_deactivated.length > 0 && (
            <div className="mt-1 text-[11px] ds-u-color--muted">
              Excluded {result.excluded_deactivated.length} deactivated ADO:{' '}
              {result.excluded_deactivated.map(e => e.name || e.sid).join(', ')}
            </div>
          )}
        </div>
      )}
      <EmailHistory history={result?.email_history ?? data?.email_history} />
    </div>
  )
}
