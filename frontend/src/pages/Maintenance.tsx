import { useState, useEffect, useRef, FormEvent } from 'react'
import {
  MAINT_START_TIME,
  MAINT_DOWNTIME_END_TIME,
  MAINT_DOWNTIME_WINDOW_LABEL,
  nextMaintenanceDate,
} from '../utils/maintenanceWindow'
import ActionCard from '../components/ui/ActionCard'
import Modal from '../components/ui/Modal'
import { useSearchParams } from 'react-router-dom'
import { Alert, Badge } from '@cmsgov/design-system'
import {
  GitBranch,
  Clock,
  Bell,
  X,
  Loader2,
  CheckCircle,
  ExternalLink,
  Wrench,
  AlertTriangle,
} from 'lucide-react'
import {
  cutMaintenanceBranch,
  getBranchDefaults,
  createDatadogDowntime,
  getActiveDatadogDowntime,
  getMaintenanceWindow,
  type MaintenanceWindow,
  extendDatadogDowntime,
  cancelDatadogDowntime,
  getXocEocPreview,
  getSonarQubeParams,
  getSonarQubeVersions,
  getSonarQubeReleaseNotes,
  triggerSonarQubeMaintenance,
  getJFrogDevParams,
  applyJFrogDevChanges,
  getJFrogProdParams,
  applyJFrogProdChanges,
  getCloudBeesDevParams,
  applyCloudBeesDevChanges,
  getCloudBeesProdParams,
  applyCloudBeesProdChanges,
  XocEocPreview,
  SonarQubeJobParam,
  DatadogDowntime,
  JFrogDevParams,
  JFrogChartRow,
  CloudBeesDevParams,
  CloudBeesProdParams,
  CloudBeesReleaseNotes,
  SonarQubeReleaseNotes,
  apiErrorMessage,
  getBaseChartsParams,
  applyBaseChartsChanges,
  type BaseChartsParams,
  getEksUpgradeParams,
  getEksUpgradePreview,
  applyEksUpgrade,
  type EksUpgradeParams,
  type EksUpgradePreview,
  type EksUpgradeApplyResult,
  type K8sReleaseNotes,
  type PlutoReport,
} from '../api/client'



function defaultBranchName(): string {
  const months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec']
  const now = new Date()
  return `${months[now.getMonth()]}${String(now.getFullYear()).slice(2)}-maint`
}

// ─── Modal ─────────────────────────────────────────────────────────────────── (imported from components/ui/Modal)

// ─── Toast ────────────────────────────────────────────────────────────────────

interface ToastProps {
  message: string
  type: 'success' | 'error'
  onClose: () => void
}

function Toast({ message, type, onClose }: ToastProps) {
  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg max-w-sm ${
        type === 'success' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
      }`}
    >
      {type === 'success' ? (
        <CheckCircle size={18} className="text-green-600 flex-shrink-0 mt-0.5" />
      ) : (
        <AlertTriangle size={18} className="text-red-600 flex-shrink-0 mt-0.5" />
      )}
      <p className={`text-sm flex-1 ${type === 'success' ? 'text-green-800' : 'text-red-800'}`}>
        {message}
      </p>
      <button onClick={onClose} className="ds-u-color--muted hover:text-gray-600">
        <X size={14} />
      </button>
    </div>
  )
}

// ─── Action Card ─────────────────────────────────────────────────────────────── (imported from components/ui/ActionCard)

// ─── Cut Maintenance Branch Modal ─────────────────────────────────────────────

function BranchModal({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: (msg: string) => void }) {
  const generated = defaultBranchName()
  const [repo, setRepo] = useState('')
  const [branchName, setBranchName] = useState(generated)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ url: string; already_existed: boolean } | null>(null)

  useEffect(() => {
    if (!open) return
    getBranchDefaults()
      .then(d => { if (d.default_repo) setRepo(d.default_repo) })
      .catch(() => {})
  }, [open])

  function handleClose() {
    setRepo('')
    setBranchName(generated)
    setError('')
    setResult(null)
    onClose()
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await cutMaintenanceBranch({ repo, branch_name: branchName, base_branch: 'main' })
      setResult({ url: res.url, already_existed: res.already_existed })
      onSuccess(res.already_existed ? `Branch ${branchName} already exists` : `Branch ${branchName} created!`)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Failed to cut maintenance branch. Check that the repo exists.'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Cut Maintenance Branch">
      {result ? (
        <div className="text-center space-y-4 py-4">
          <div className={`w-14 h-14 ${result.already_existed ? 'bg-amber-100' : 'bg-green-100'} rounded-full flex items-center justify-center mx-auto`}>
            {result.already_existed
              ? <GitBranch size={28} className="text-amber-600" />
              : <CheckCircle size={28} className="text-green-600" />}
          </div>
          <p className="font-semibold text-gray-900">
            {result.already_existed ? 'Branch already exists' : 'Branch created!'}
          </p>
          <p className="text-sm ds-u-color--muted font-mono">{branchName}</p>
          <a
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline"
          >
            View on GitHub <ExternalLink size={13} />
          </a>
          <div className="pt-2">
            <button onClick={handleClose} className="btn-secondary w-full">Close</button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}
          <div>
            <label className="label">Repository</label>
            <input
              className="input-field font-mono text-sm"
              value={repo}
              onChange={e => setRepo(e.target.value)}
              placeholder="CMSgov/cms-cloud-platform"
              required
            />
            <p className="text-xs ds-u-color--muted mt-1">Org-qualified (CMSgov/repo) or just the repo name</p>
          </div>
          <div>
            <label className="label">Branch Name</label>
            <input
              className="input-field font-mono text-sm"
              value={branchName}
              onChange={e => setBranchName(e.target.value)}
              required
            />
            <p className="text-xs ds-u-color--muted mt-1">
              Auto-generated from current month — override if needed
            </p>
          </div>
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" disabled={loading} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {loading && <Loader2 size={15} className="animate-spin" />}
              Cut Branch
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

// ─── Datadog Downtime Modal ───────────────────────────────────────────────────

const DD_DEFAULT_SCOPE = '*'
const DD_DEFAULT_MONITOR_TAGS = 'team:devops'
const DD_NOTIFY_EMAIL = 'CMS_Cloud_DevOps@cms.hhs.gov'

function ddDefaultMessage(): string {
  const month = new Date().toLocaleString('en-US', { month: 'long', year: 'numeric' })
  return `DevOps Monthly Maintenance for ${month} @${DD_NOTIFY_EMAIL}`
}

function fmtTs(ts: number | null): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  })
}

// ── Maintenance-window defaults ───────────────────────────────────────────────
// Window times and the third-Saturday math live in utils/maintenanceWindow so
// the Datadog modal, the ITC/MGGD forms and the help copy cannot drift apart.

// Pre-filled create form: the downtime brackets the outage by an hour so
// monitors stay silenced through verification. Engineer can override.
//
// `win` comes from the server and already has the admin override applied.
// Without it this fell back to the third-Saturday math in the browser, which
// cannot see the override, so an override month pre-filled a date the tickets
// would not use. The local math stays only as the offline fallback.
function ddInitialForm(win?: MaintenanceWindow | null) {
  const date = win?.date ?? nextMaintenanceDate()
  const start = win?.start_time ?? MAINT_START_TIME
  const end = win?.downtime_end_time ?? MAINT_DOWNTIME_END_TIME
  return {
    scope: DD_DEFAULT_SCOPE,
    start: `${date}T${start}`,
    end: `${date}T${end}`,
    message: ddDefaultMessage(),
    monitor_tags: DD_DEFAULT_MONITOR_TAGS,
  }
}

function DatadogModal({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: (msg: string) => void }) {
  const [active, setActive] = useState<DatadogDowntime | null | undefined>(undefined) // undefined=loading
  const [win, setWin] = useState<MaintenanceWindow | null>(null)
  const [form, setForm] = useState(() => ddInitialForm())
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setActive(undefined)
    setError('')
    // Re-seed the create form each time the modal opens so the maintenance date
    // and window times are fresh (and any prior edits are cleared).
    setForm(ddInitialForm(win))
    getActiveDatadogDowntime()
      .then(r => setActive(r.downtime))
      .catch(() => setActive(null))
    getMaintenanceWindow()
      .then(w => { setWin(w); setForm(ddInitialForm(w)) })
      .catch(() => { /* keep the locally computed fallback */ })
  }, [open])

  function handleClose() {
    setActive(undefined)
    setForm(ddInitialForm(win))
    setError('')
    onClose()
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await createDatadogDowntime({
        scope: form.scope,
        start: Math.floor(new Date(form.start).getTime() / 1000),
        end: Math.floor(new Date(form.end).getTime() / 1000),
        message: form.message,
        monitor_tags: form.monitor_tags.split(',').map(t => t.trim()).filter(Boolean),
      })
      // Set active directly from response — keeps modal open so extend/cancel are immediately visible
      setActive({ id: res.downtime_id, scope: res.scope, message: res.message, start: res.start, end: res.end, status: 'scheduled' })
      onSuccess('Downtime created!')
    } catch (err: unknown) {
      const msg = apiErrorMessage(err, '')
      setError(msg ? `Datadog API error: ${msg}` : 'Failed to create Datadog downtime.')
    } finally {
      setLoading(false)
    }
  }

  async function handleExtend() {
    if (!active) return
    setError('')
    setLoading(true)
    try {
      const res = await extendDatadogDowntime(active.id)
      setActive(prev => prev ? { ...prev, end: res.end } : prev)
      onSuccess('Downtime extended by 2 hours!')
    } catch {
      setError('Failed to extend downtime.')
    } finally {
      setLoading(false)
    }
  }

  async function handleCancel() {
    if (!active) return
    setError('')
    setLoading(true)
    try {
      await cancelDatadogDowntime(active.id)
      setActive(null)
      onSuccess('Downtime ended.')
    } catch {
      setError('Failed to end downtime.')
    } finally {
      setLoading(false)
    }
  }

  const isChecking = active === undefined

  return (
    <Modal open={open} onClose={handleClose} title="Datadog Downtime">
      <div className="space-y-4">
        {isChecking && (
          <div className="flex items-center gap-2 py-2 text-sm ds-u-color--muted">
            <Loader2 size={14} className="animate-spin" /> Checking for active downtime…
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <AlertTriangle size={14} className="flex-shrink-0" />{error}
          </div>
        )}

        {/* ── Active downtime panel ── */}
        {!isChecking && active && (
          <div className="space-y-3">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 space-y-1.5">
              <p className="text-sm font-semibold text-yellow-800">
                {active.status === 'scheduled' ? 'Scheduled downtime' : 'Active downtime'} #{active.id.slice(0, 8)}…
              </p>
              <p className="text-xs text-yellow-700">{active.message}</p>
              <p className="text-xs text-yellow-700">
                {fmtTs(active.start)} → {fmtTs(active.end)}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={handleExtend}
                disabled={loading}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 text-sm font-medium transition-colors disabled:opacity-50"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Clock size={14} />}
                Extend 2 hrs
              </button>
              <button
                onClick={handleCancel}
                disabled={loading}
                className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-red-50 text-red-700 hover:bg-red-100 text-sm font-medium transition-colors disabled:opacity-50"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
                End Downtime
              </button>
            </div>
            <p className="text-xs ds-u-color--muted text-center">— or create a new downtime below —</p>
          </div>
        )}

        {/* ── Create form ── */}
        {!isChecking && (
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="label">Scope</label>
              <input className="input-field font-mono" value={form.scope}
                onChange={e => setForm(f => ({ ...f, scope: e.target.value }))}
                placeholder="*" required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Start</label>
                <input type="datetime-local" className="input-field" value={form.start}
                  onChange={e => setForm(f => ({ ...f, start: e.target.value }))} required />
              </div>
              <div>
                <label className="label">End</label>
                <input type="datetime-local" className="input-field" value={form.end}
                  onChange={e => setForm(f => ({ ...f, end: e.target.value }))} required />
              </div>
            </div>
            <p className="text-xs ds-u-color--muted -mt-2">
              Pre-filled to the next maintenance window ({MAINT_DOWNTIME_WINDOW_LABEL}). Override if needed.
            </p>
            <div>
              <label className="label">Monitor Tags</label>
              <input className="input-field" value={form.monitor_tags}
                onChange={e => setForm(f => ({ ...f, monitor_tags: e.target.value }))} />
            </div>
            <div>
              <label className="label">Message</label>
              <textarea className="input-field min-h-[60px] resize-y" value={form.message}
                onChange={e => setForm(f => ({ ...f, message: e.target.value }))} required />
            </div>
            <div className="flex gap-3 pt-1">
              <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
              <button type="submit" disabled={loading} className="btn-primary flex-1 flex items-center justify-center gap-2">
                {loading && <Loader2 size={15} className="animate-spin" />}
                Create Downtime
              </button>
            </div>
          </form>
        )}
      </div>
    </Modal>
  )
}

// ─── XOC/EOC Modal ────────────────────────────────────────────────────────────

function timeGreeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function CopyBox({ label, text, slackUrl }: { label: string; text: string; slackUrl?: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="label mb-0">{label}</span>
        <div className="flex items-center gap-2">
          {slackUrl && (
            <a
              href={slackUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost-link"
            >
              <ExternalLink size={11} />
              Open in Slack
            </a>
          )}
          <button
            onClick={copy}
            className="btn-copy"
          >
            {copied ? <CheckCircle size={12} className="text-green-600" /> : null}
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
      <textarea
        readOnly
        value={text}
        className="w-full input-field font-mono text-xs min-h-[60px] resize-none bg-gray-50 cursor-text"
      />
    </div>
  )
}

function XocEocModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [preview, setPreview] = useState<XocEocPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError('')
    setPreview(null)
    getXocEocPreview()
      .then(setPreview)
      .catch(() => setError('Could not fetch this month\'s maintenance tickets.'))
      .finally(() => setLoading(false))
  }, [open])

  const greeting = timeGreeting()

  const eocMsg = preview?.itc
    ? `${greeting} EOC, we are starting work on this month's DevOps maintenance. ITC ticket: ${preview.itc.url}`
    : `${greeting} EOC, we are starting work on this month's DevOps maintenance. (ITC ticket not found — please paste link manually)`

  const xocMsg = preview?.mggd
    ? `${greeting} XOC, we are starting work on this month's DevOps maintenance. MGGD ticket: ${preview.mggd.url}`
    : `${greeting} XOC, we are starting work on this month's DevOps maintenance. (MGGD ticket not found — please paste link manually)`

  return (
    <Modal open={open} onClose={onClose} title="Notify XOC / EOC">
      <div className="space-y-5">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm ds-u-color--muted">
            <Loader2 size={16} className="animate-spin" />
            Fetching this month's tickets…
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <AlertTriangle size={14} className="flex-shrink-0" />
            {error}
          </div>
        )}
        {!loading && (
          <>
            <p className="text-xs ds-u-color--muted">
              Copy each message and paste into the appropriate Slack channel.
            </p>
            <CopyBox label="#eoc" text={eocMsg} slackUrl="https://app.slack.com/client/E06EP6PNBV5/C049USQ946P" />
            <CopyBox label="#xoc" text={xocMsg} slackUrl="https://app.slack.com/client/E06EP6PNBV5/CHDF2SGSC" />
          </>
        )}
        <div className="pt-1">
          <button onClick={onClose} className="btn-secondary w-full">Close</button>
        </div>
      </div>
    </Modal>
  )
}

// ─── SonarQube Maintenance Modal ──────────────────────────────────────────────

function SonarQubeModal({ open, onClose, targetEnv = 'dev' }: {
  open: boolean; onClose: () => void; targetEnv?: 'dev' | 'prod'
}) {
  const isProd = targetEnv === 'prod'
  const [jobParams, setJobParams] = useState<SonarQubeJobParam[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [versions, setVersions] = useState<string[]>([])
  const [selectedVersion, setSelectedVersion] = useState('')
  const [fetching, setFetching] = useState(false)
  const [deploying, setDeploying] = useState(false)
  const [error, setError] = useState('')
  const [buildUrl, setBuildUrl] = useState('')
  const [prodConfirmed, setProdConfirmed] = useState(false)
  const [releaseNotes, setReleaseNotes] = useState<SonarQubeReleaseNotes | null>(null)
  const [rnLoading, setRnLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    setFetching(true)
    setError('')
    setBuildUrl('')
    setProdConfirmed(false)
    setVersions([])
    setSelectedVersion('')
    Promise.all([getSonarQubeParams(), getSonarQubeVersions()])
      .then(([res, vers]) => {
        setJobParams(res.params)
        const defaults: Record<string, string> = {}
        res.params.forEach(p => { defaults[p.name] = String(p.default ?? '') })
        defaults['ENV'] = targetEnv
        setValues(defaults)
        setVersions(vers)
        if (vers.length > 0) setSelectedVersion(vers[0])
      })
      .catch(() => setError('Could not fetch job parameters from Jenkins.'))
      .finally(() => setFetching(false))
  }, [open])

  // Load the selected version's release notes (best-effort, never blocks deploy).
  useEffect(() => {
    if (!open || !selectedVersion) { setReleaseNotes(null); return }
    let alive = true
    setRnLoading(true)
    getSonarQubeReleaseNotes(selectedVersion)
      .then(rn => { if (alive) setReleaseNotes(rn) })
      .catch(e => { if (alive) setReleaseNotes({ available: false, error: apiErrorMessage(e, 'Failed to load release notes.') }) })
      .finally(() => { if (alive) setRnLoading(false) })
    return () => { alive = false }
  }, [open, selectedVersion])

  function handleClose() {
    setJobParams([])
    setValues({})
    setVersions([])
    setSelectedVersion('')
    setError('')
    setBuildUrl('')
    setProdConfirmed(false)
    setReleaseNotes(null)
    onClose()
  }

  async function handleDeploy(e: FormEvent) {
    e.preventDefault()
    setError('')
    setDeploying(true)
    try {
      const res = await triggerSonarQubeMaintenance({ ...values, SONARQUBE_VERSION: selectedVersion })
      setBuildUrl(res.build_url)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to trigger job.'))
    } finally {
      setDeploying(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title={`SonarQube — Deploy (${targetEnv})`}>
      {buildUrl ? (
        <div className="space-y-4 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Job triggered!</p>
              <p className="text-sm text-green-700 mt-0.5">Build is queued in Jenkins.</p>
            </div>
          </div>
          <div>
            <p className="label">Build URL</p>
            <a
              href={buildUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-cms-blue hover:underline break-all"
            >
              {buildUrl} <ExternalLink size={13} className="flex-shrink-0" />
            </a>
          </div>
          <button onClick={handleClose} className="btn-secondary w-full mt-2">Close</button>
        </div>
      ) : (
        <form onSubmit={handleDeploy} className="space-y-4">
          {fetching && (
            <div className="flex items-center gap-2 py-4 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" />
              Loading job parameters…
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}
          {!fetching && jobParams.length > 0 && (
            <>
              <p className="text-xs ds-u-color--muted">
                Review parameters before deploying. Defaults are pre-filled from Jenkins.
              </p>
              <div>
                <label className="label">
                  SONARQUBE_VERSION
                  <span className="ds-u-color--muted font-normal ml-1.5">— SonarQube datacenter version to deploy</span>
                </label>
                {versions.length > 0 ? (
                  <select
                    className="input-field font-mono text-sm"
                    value={selectedVersion}
                    onChange={e => setSelectedVersion(e.target.value)}
                  >
                    {versions.map(v => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <input
                    className="input-field font-mono text-sm"
                    value={selectedVersion}
                    onChange={e => setSelectedVersion(e.target.value)}
                    placeholder="e.g. 2026.2.0.121184"
                    required
                  />
                )}
                <SonarReleaseNotesPanel rn={releaseNotes} loading={rnLoading} />
              </div>
              {jobParams.filter(p => p.name !== 'SONARQUBE_VERSION').map(p => (
                <div key={p.name}>
                  <label className="label">
                    {p.name}
                    {p.description && (
                      <span className="ds-u-color--muted font-normal ml-1.5">— {p.description}</span>
                    )}
                  </label>
                  {p.name === 'ENV' ? (
                    <input
                      className="input-field font-mono text-sm bg-gray-50 cursor-not-allowed"
                      value={targetEnv}
                      readOnly
                    />
                  ) : p.type === 'choice' && p.choices.length > 0 ? (
                    <select
                      className="input-field"
                      value={values[p.name] ?? String(p.default ?? '')}
                      onChange={e => setValues(v => ({ ...v, [p.name]: e.target.value }))}
                    >
                      {p.choices.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                  ) : p.type === 'boolean' ? (
                    <label className="flex items-center gap-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        className="accent-cms-blue"
                        checked={(values[p.name] ?? String(p.default ?? '')) === 'true'}
                        onChange={e => setValues(v => ({ ...v, [p.name]: e.target.checked ? 'true' : 'false' }))}
                      />
                      <span className="text-sm text-gray-600">
                        {(values[p.name] ?? String(p.default ?? '')) === 'true' ? 'Enabled' : 'Disabled'}
                      </span>
                    </label>
                  ) : (
                    <input
                      className="input-field font-mono text-sm"
                      value={values[p.name] ?? String(p.default ?? '')}
                      onChange={e => setValues(v => ({ ...v, [p.name]: e.target.value }))}
                      required
                    />
                  )}
                </div>
              ))}
            </>
          )}
          {isProd && jobParams.length > 0 && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-3 py-3">
              <input
                type="checkbox"
                id="prod-confirm"
                className="mt-0.5 flex-shrink-0 accent-red-600"
                checked={prodConfirmed}
                onChange={e => setProdConfirmed(e.target.checked)}
              />
              <label htmlFor="prod-confirm" className="text-sm text-red-800 cursor-pointer">
                I confirm this is the <strong>prod environment</strong> and I have reviewed all changes above.
              </label>
            </div>
          )}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button
              type="submit"
              disabled={fetching || deploying || jobParams.length === 0 || !selectedVersion || (isProd && !prodConfirmed)}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
            >
              {deploying && <Loader2 size={15} className="animate-spin" />}
              Deploy
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

// ─── JFrog Dev Maintenance Modal ──────────────────────────────────────────────

function versionBadge(row: JFrogChartRow) {
  if (row.floating) {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded bg-blue-100 text-blue-700"
            title={`Floats at ${row.current_version} — Flux auto-tracks the latest (currently ${row.latest_version || '?'})`}>
        tracks latest
      </span>
    )
  }
  if (!row.has_update) {
    return <span className="text-xs ds-u-color--muted">up to date</span>
  }
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
      row.is_breaking ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'
    }`}>
      {row.is_breaking && <AlertTriangle size={10} />}
      {row.latest_version}
    </span>
  )
}

function SonarReleaseNotesPanel({ rn, loading }: { rn: SonarQubeReleaseNotes | null; loading: boolean }) {
  if (loading) {
    return (
      <p className="text-xs ds-u-color--muted flex items-center gap-1 mt-2">
        <Loader2 size={11} className="animate-spin" /> Loading release notes…
      </p>
    )
  }
  if (!rn) return null
  if (!rn.available) {
    return (
      <p className="text-xs ds-u-color--muted italic mt-2">
        {rn.error ? `Release notes unavailable: ${rn.error}` : 'No release notes available for this version.'}
        {rn.source_url && (
          <a href={rn.source_url} target="_blank" rel="noopener noreferrer"
             className="ml-2 text-cms-blue hover:underline not-italic">
            View on SonarSource <ExternalLink size={10} className="inline" />
          </a>
        )}
      </p>
    )
  }
  return (
    <div className="mt-2 rounded-lg border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/40 p-3 space-y-2">
      <p className="text-xs font-semibold text-gray-700 dark:text-gray-200">
        What’s new in {rn.version}
        <span className="font-normal ds-u-color--muted ml-1.5">
          ({rn.count} {rn.count === 1 ? 'fix' : 'fixes'})
        </span>
      </p>
      {rn.entries && rn.entries.length > 0 ? (
        <ul className="space-y-1">
          {rn.entries.map(e => (
            <li key={e.key} className="text-xs text-gray-600 dark:text-gray-300 flex gap-1.5">
              <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
              <span>
                <a href={e.url} target="_blank" rel="noopener noreferrer"
                   className="font-mono text-cms-blue hover:underline">{e.key}</a>
                {e.type && <span className="ds-u-color--muted"> [{e.type}]</span>} {e.summary}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs ds-u-color--muted italic">No non-maintenance issues listed for this version.</p>
      )}
      {rn.source_url && (
        <a href={rn.source_url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline">
          Full release notes <ExternalLink size={10} />
        </a>
      )}
    </div>
  )
}

function ReleaseNotesPanel({ rn, sourceUrl }: { rn: import('../api/client').JFrogReleaseNotes; sourceUrl: string }) {
  if (!rn.available) {
    return (
      <div className="text-xs ds-u-color--muted italic py-1">
        {rn.error ? `Release notes unavailable: ${rn.error}` : 'No release notes available for this version.'}
        {rn.upgrade_guide_url && (
          <a href={rn.upgrade_guide_url} target="_blank" rel="noopener noreferrer"
             className="ml-2 text-cms-blue hover:underline not-italic">
            Upgrade guide <ExternalLink size={10} className="inline" />
          </a>
        )}
      </div>
    )
  }

  if (rn.type === 'changelog' && rn.entries) {
    return (
      <div className="space-y-3 py-1">
        {rn.entries.length === 0 ? (
          <p className="text-xs ds-u-color--muted italic">No entries found between these versions.</p>
        ) : (
          rn.entries.map(entry => (
            <div key={entry.version}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-semibold text-gray-700">{entry.version}</span>
                {entry.date && <span className="text-xs ds-u-color--muted">{entry.date}</span>}
                {entry.has_important && (
                  <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-medium">
                    Important
                  </span>
                )}
              </div>
              <ul className="space-y-0.5 ml-2">
                {entry.notes.map((note, i) => (
                  <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                    <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
                    <span dangerouslySetInnerHTML={{ __html: note.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>') }} />
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline">
          Full CHANGELOG <ExternalLink size={10} />
        </a>
      </div>
    )
  }

  if (rn.type === 'github_release' && rn.sections) {
    return (
      <div className="space-y-3 py-1">
        {rn.sections.length === 0 ? (
          <p className="text-xs ds-u-color--muted italic">No notable changes found in release notes.</p>
        ) : (
          rn.sections.map((sec, si) => (
            <div key={si}>
              <p className={`text-xs font-semibold mb-1 ${sec.is_breaking ? 'text-orange-700' : 'text-gray-700'}`}>
                {sec.is_breaking && <AlertTriangle size={10} className="inline mr-1" />}
                {sec.heading}
              </p>
              <ul className="space-y-0.5 ml-2">
                {sec.items.map((item, i) => (
                  <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                    <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
        <div className="flex items-center gap-3 pt-1">
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline">
            Full release notes <ExternalLink size={10} />
          </a>
          {rn.upgrade_guide_url && (
            <a href={rn.upgrade_guide_url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-xs text-orange-600 hover:underline font-medium">
              <AlertTriangle size={10} /> Upgrade guide
            </a>
          )}
        </div>
      </div>
    )
  }

  return null
}

function ChartTable({
  rows,
  expandedKey,
  onToggle,
  skipped,
  onToggleSkip,
}: {
  rows: JFrogChartRow[]
  expandedKey: string | null
  onToggle: (key: string) => void
  skipped: Set<string>
  onToggleSkip: (key: string) => void
}) {
  return (
    <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
      <table className="w-full">
        <thead>
          <tr className="bg-gray-50 text-xs ds-u-color--muted">
            <th className="text-left px-3 py-2 font-medium">Component</th>
            <th className="text-left px-3 py-2 font-medium">Current</th>
            <th className="text-left px-3 py-2 font-medium">Latest</th>
            <th className="px-3 py-2 w-8"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <>
              <tr
                key={row.key}
                className={`${i > 0 ? 'border-t border-gray-100' : ''} ${
                  row.has_update ? 'cursor-pointer hover:bg-gray-50' : ''
                }`}
                onClick={() => row.has_update && onToggle(row.key)}
              >
                <td className="px-3 py-2">
                  <div className="text-xs font-medium text-gray-800">{row.label}</div>
                  {row.app_version && (
                    <div className="text-xs ds-u-color--muted">App: {row.app_version}</div>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-xs ds-u-color--muted">{row.current_version || '—'}</td>
                <td className="px-3 py-2">
                  {row.has_update ? (
                    <div className="flex flex-col gap-1">
                      <div className={skipped.has(row.key) ? 'opacity-40 line-through' : ''}>
                        {versionBadge(row)}
                      </div>
                      <label
                        className="flex items-center gap-1 text-[11px] ds-u-color--muted cursor-pointer select-none"
                        onClick={e => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={skipped.has(row.key)}
                          onChange={() => onToggleSkip(row.key)}
                          className="rounded border-gray-300 h-3 w-3"
                        />
                        Skip (stay on {row.current_version || 'current'})
                      </label>
                    </div>
                  ) : (
                    versionBadge(row)
                  )}
                </td>
                <td className="px-3 py-2 ds-u-color--muted">
                  {row.has_update && (
                    <span className="text-xs">{expandedKey === row.key ? '▲' : '▼'}</span>
                  )}
                </td>
              </tr>
              {row.has_update && expandedKey === row.key && (
                <tr key={`${row.key}-notes`} className="border-t border-gray-100 bg-gray-50">
                  <td colSpan={4} className="px-4 py-3">
                    {row.release_notes ? (
                      <ReleaseNotesPanel
                        rn={row.release_notes}
                        sourceUrl={row.release_notes.source_url ?? row.changelog_url}
                      />
                    ) : (
                      <div className="flex items-center gap-2 text-xs ds-u-color--muted">
                        <Loader2 size={11} className="animate-spin" /> Loading release notes…
                      </div>
                    )}
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── CloudBees CI Dev Maintenance Modal ───────────────────────────────────────

function CBReleaseNotesPanel({ rn }: { rn: CloudBeesReleaseNotes }) {
  if (!rn.available) {
    return (
      <p className="text-xs ds-u-color--muted italic">
        {rn.error ? `Release notes unavailable: ${rn.error}` : 'No release notes available.'}
        {rn.source_url && (
          <a href={rn.source_url} target="_blank" rel="noopener noreferrer"
             className="ml-2 text-cms-blue hover:underline not-italic">
            View docs <ExternalLink size={10} className="inline" />
          </a>
        )}
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {rn.entries?.map((entry) => (
        <div key={entry.version}>
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs font-semibold text-gray-700">{entry.version}</span>
            {entry.date && <span className="text-xs ds-u-color--muted">{entry.date}</span>}
            {entry.has_important && (
              <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-medium">
                Upgrade Notes
              </span>
            )}
          </div>
          <div className="space-y-2">
            {entry.sections.map((sec, si) => (
              <div key={si}>
                <p className={`text-xs font-medium mb-0.5 ${sec.is_breaking ? 'text-orange-700' : 'text-gray-600'}`}>
                  {sec.is_breaking ? '⚠ ' : ''}{sec.heading}
                </p>
                <ul className="space-y-0.5 ml-2">
                  {sec.items.map((item, ii) => (
                    <li key={ii} className="text-xs text-gray-600 flex gap-1.5">
                      <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ))}
      {rn.source_url && (
        <a href={rn.source_url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline">
          Full release notes <ExternalLink size={10} />
        </a>
      )}
    </div>
  )
}

function CBAmiRow({ label, current, latest, latestName, hasUpdate, error, drift }: {
  label: string
  current: string | null
  latest: string | null
  latestName: string | null
  hasUpdate: boolean
  error: string | null
  drift?: boolean
}) {
  return (
    <tr className="border-t border-gray-100">
      <td className="px-3 py-2 text-xs ds-u-color--muted">
        {label}
        {drift && (
          <span className="ml-1 text-[10px] text-amber-600" title="tfvars eks_ami does not match the controller nodeclass AMI; Apply will reconcile both">
            (tfvars drift)
          </span>
        )}
      </td>
      <td className="px-3 py-2 font-mono text-xs text-gray-700">{current || '—'}</td>
      <td className="px-3 py-2">
        {error ? (
          <span className="text-xs text-amber-600 flex items-center gap-1">
            <AlertTriangle size={11} /> {error.includes('gov') || error.includes('gov-west') ? 'Requires GovCloud creds' : 'Fetch failed'}
          </span>
        ) : hasUpdate ? (
          <div>
            <span className="font-mono text-xs text-green-700 font-medium">{latest}</span>
            {latestName && <p className="text-xs ds-u-color--muted font-mono mt-0.5">{latestName}</p>}
          </div>
        ) : latest ? (
          <span className="text-xs ds-u-color--muted">up to date</span>
        ) : (
          <span className="text-xs text-gray-300">—</span>
        )}
      </td>
    </tr>
  )
}

function CloudBeesDevModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<CloudBeesDevParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ committed_files: string[]; branch_url: string } | null>(null)
  const [chartExpanded, setChartExpanded] = useState(false)
  const [skipChart, setSkipChart] = useState(false)
  const [ociExpandedKey, setOciExpandedKey] = useState<string | null>(null)
  const [ociSkipped, setOciSkipped] = useState<Set<string>>(new Set())
  const toggleOciSkip = (key: string) =>
    setOciSkipped(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  const toggleOciExpand = (key: string) => setOciExpandedKey(k => (k === key ? null : key))

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setChartExpanded(false)
    setOciExpandedKey(null)
    setOciSkipped(new Set())
    setLoading(true)
    getCloudBeesDevParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to fetch CloudBees dev state.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setParams(null); setError(''); setResult(null); onClose()
  }

  async function handleApply() {
    if (!params) return
    setError('')
    setApplying(true)
    try {
      const de = params.envs['dev-east']
      const gc = params.envs['gc-dev-west']
      // Send the controller TARGET AMI (drives both tfvars eks_ami + controller nodeclass).
      const deCtrlAmi = de.controller_has_update ? de.controller_target_ami! : ''
      const gcCtrlAmi = gc.controller_has_update ? gc.controller_target_ami! : ''
      const gcAgentAmi = gc.agent_has_update ? gc.latest_agent_ami! : ''

      const res = await applyCloudBeesDevChanges({
        branch: params.branch,
        new_chart_version: params.chart.has_update && !skipChart ? params.chart.latest_version ?? undefined : undefined,
        new_chart_tag: params.chart.has_update && !skipChart ? params.chart.latest_tag ?? undefined : undefined,
        dev_east_controller_ami: deCtrlAmi || undefined,
        dev_east_controller_ami_name: de.latest_controller_ami_name ?? undefined,
        dev_east_agent_ami: de.agent_has_update ? de.latest_agent_ami ?? undefined : undefined,
        dev_east_agent_ami_name: de.latest_agent_ami_name ?? undefined,
        gc_dev_west_controller_ami: gcCtrlAmi || undefined,
        gc_dev_west_controller_ami_name: gc.latest_controller_ami_name ?? undefined,
        gc_dev_west_agent_ami: gcAgentAmi || undefined,
        gc_dev_west_agent_ami_name: gc.latest_agent_ami_name ?? undefined,
        karpenter_version: kar?.has_update && !ociSkipped.has('karpenter') ? kar.latest_version ?? undefined : undefined,
        karpenter_crd_version: crd?.has_update && !ociSkipped.has('karpenter-crd') ? crd.latest_version ?? undefined : undefined,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply changes.'))
    } finally {
      setApplying(false)
    }
  }

  const de = params?.envs['dev-east']
  const gc = params?.envs['gc-dev-west']
  const kar = params?.oci_repos.find(r => r.key === 'karpenter')
  const crd = params?.oci_repos.find(r => r.key === 'karpenter-crd')
  const totalUpdates = params ? (
    (params.chart.has_update && !skipChart ? 1 : 0) +
    (de?.controller_has_update ? 1 : 0) +
    (de?.agent_has_update ? 1 : 0) +
    (gc?.controller_has_update ? 1 : 0) +
    (gc?.agent_has_update ? 1 : 0) +
    params.oci_repos.filter(r => r.has_update && !ociSkipped.has(r.key)).length
  ) : 0

  return (
    <Modal open={open} onClose={handleClose} title="CloudBees CI — Dev Maintenance" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Changes committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {result.committed_files.length} file{result.committed_files.length !== 1 ? 's' : ''} updated on{' '}
                <span className="font-mono">{params?.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          <p className="text-xs ds-u-color--muted">
            FluxCD will reconcile and apply the updated chart automatically after the branch is merged to main.
          </p>
          <a href={result.branch_url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium">
            View branch on GitHub <ExternalLink size={13} />
          </a>
          <button onClick={handleClose} className="btn-secondary w-full mt-2">Close</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-4 justify-center">
              <Loader2 size={16} className="animate-spin" /> Fetching current state...
            </div>
          )}
          {error && !loading && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
          )}
          {params && (
            <>
              {/* Branch */}
              <div className="flex items-center justify-between">
                <div className="text-xs ds-u-color--muted">
                  Branch: <span className="font-mono text-gray-800">{params.branch}</span>
                  {params.branch_created && <span className="ml-2 text-green-600">(just created)</span>}
                </div>
                <a href={params.branch_url} target="_blank" rel="noopener noreferrer"
                   className="flex items-center gap-1 text-xs text-cms-blue hover:underline">
                  GitHub <ExternalLink size={10} />
                </a>
              </div>

              {/* Commercial Dev AMIs */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  {de?.label} — AMIs
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Node</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                      </tr>
                    </thead>
                    <tbody>
                      <CBAmiRow
                        label="Controller (gold image)"
                        current={de?.current_controller_ami ?? null}
                        latest={de?.controller_target_ami ?? null}
                        latestName={de?.latest_controller_ami_name ?? null}
                        hasUpdate={de?.controller_has_update ?? false}
                        error={de?.controller_error ?? null}
                        drift={de?.controller_drift ?? false}
                      />
                      <CBAmiRow
                        label="Agent (gold image)"
                        current={de?.current_agent_ami ?? null}
                        latest={de?.latest_agent_ami ?? null}
                        latestName={de?.latest_agent_ami_name ?? null}
                        hasUpdate={de?.agent_has_update ?? false}
                        error={de?.agent_error ?? null}
                      />
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Gov Cloud Dev AMIs */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  {gc?.label} — AMIs
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Node</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                      </tr>
                    </thead>
                    <tbody>
                      <CBAmiRow
                        label="Controller (gold image)"
                        current={gc?.current_controller_ami ?? null}
                        latest={gc?.controller_target_ami ?? null}
                        latestName={gc?.latest_controller_ami_name ?? null}
                        hasUpdate={gc?.controller_has_update ?? false}
                        error={gc?.controller_error ?? null}
                        drift={gc?.controller_drift ?? false}
                      />
                      <CBAmiRow
                        label="Agent (gold image)"
                        current={gc?.current_agent_ami ?? null}
                        latest={gc?.latest_agent_ami ?? null}
                        latestName={gc?.latest_agent_ami_name ?? null}
                        hasUpdate={gc?.agent_has_update ?? false}
                        error={gc?.agent_error ?? null}
                      />
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Chart version — click row to expand release notes */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  CloudBees Core Chart
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Component</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                        <th className="px-3 py-2 w-8"></th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        className={`border-t border-gray-100 ${params.chart.has_update ? 'cursor-pointer hover:bg-gray-50' : ''}`}
                        onClick={() => params.chart.has_update && setChartExpanded(e => !e)}
                      >
                        <td className="px-3 py-2">
                          <div className="text-xs font-medium text-gray-800">CloudBees Core</div>
                          <div className="text-xs ds-u-color--muted font-mono">
                            tag: {params.chart.current_tag || '—'}
                          </div>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs ds-u-color--muted">
                          {params.chart.current_version || '—'}
                        </td>
                        <td className="px-3 py-2">
                          {params.chart.has_update ? (
                            <div className="flex flex-col gap-1">
                              <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
                                params.chart.release_notes?.has_breaking
                                  ? 'bg-orange-100 text-orange-700'
                                  : 'bg-green-100 text-green-700'
                              } ${skipChart ? 'opacity-40 line-through' : ''}`}>
                                {params.chart.release_notes?.has_breaking && <AlertTriangle size={10} />}
                                {params.chart.latest_version}
                              </span>
                              <label
                                className="flex items-center gap-1 text-[11px] ds-u-color--muted cursor-pointer select-none"
                                onClick={e => e.stopPropagation()}
                              >
                                <input
                                  type="checkbox"
                                  checked={skipChart}
                                  onChange={() => setSkipChart(v => !v)}
                                  className="rounded border-gray-300 h-3 w-3"
                                />
                                Skip (stay on {params.chart.current_version || 'current'})
                              </label>
                            </div>
                          ) : (
                            <span className="text-xs ds-u-color--muted">up to date</span>
                          )}
                        </td>
                        <td className="px-3 py-2 ds-u-color--muted text-xs">
                          {params.chart.has_update && (chartExpanded ? '▲' : '▼')}
                        </td>
                      </tr>
                      {params.chart.has_update && chartExpanded && (
                        <tr className="border-t border-gray-100 bg-gray-50">
                          <td colSpan={4} className="px-4 py-3">
                            {params.chart.release_notes ? (
                              <CBReleaseNotesPanel rn={params.chart.release_notes} />
                            ) : (
                              <div className="flex items-center gap-2 text-xs ds-u-color--muted">
                                <Loader2 size={11} className="animate-spin" /> Loading release notes…
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  <div className="px-3 py-1.5 border-t border-gray-100 text-xs ds-u-color--muted font-mono">
                    {params.chart.file}
                  </div>
                </div>
              </div>

              {/* Karpenter OCI repositories (shared base for all clusters) */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  OCI Repositories (tag-based) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.oci_repos}
                  expandedKey={ociExpandedKey}
                  onToggle={toggleOciExpand}
                  skipped={ociSkipped}
                  onToggleSkip={toggleOciSkip}
                />
                <p className="text-xs ds-u-color--muted mt-1.5">
                  Shared across all CBJ clusters (base overlay). Karpenter and Karpenter CRD must always be updated to the same tag.
                </p>
              </div>

              {/* Post-merge manual steps reminder */}
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1">
                <p className="font-semibold">Pull the <span className="font-mono">{params.branch}</span> branch locally:</p>
                <ol className="list-decimal list-inside space-y-0.5 text-blue-700">
                  <li>Run <span className="font-mono">terraform plan</span> + <span className="font-mono">apply</span></li>
                  <li>Run the Kubernetes apply: <span className="font-mono">kubectl apply -k .</span></li>
                  <li>Wait for Karpenter nodes to cycle</li>
                  <li>Login to the Jenkins instance</li>
                  <li>Run <span className="font-mono">Cluster Ops → plugins-upgrade</span> pipeline in CJOC</li>
                  <li>Run <span className="font-mono">Cluster Ops → managed-master-update</span> pipeline in CJOC</li>
                  <li>Drain the node CJOC is running on and wait for Karpenter to replace it and CJOC to come back up</li>
                </ol>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
              )}

              <p className="text-xs ds-u-color--muted">
                <span className="font-mono">main</span> is merged into the maintenance branch
                before anything is written, so a commit cannot land on a stale base.
              </p>

              <div className="flex gap-3 pt-1">
                <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={applying || totalUpdates === 0}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying ? <><Loader2 size={15} className="animate-spin" /> Committing...</> : `Apply ${totalUpdates} update${totalUpdates !== 1 ? 's' : ''}`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

// ─── CloudBees CI Prod Maintenance Modal ──────────────────────────────────────

function CloudBeesProdModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<CloudBeesProdParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ committed_files: string[]; branch_url: string } | null>(null)
  const [chartExpanded, setChartExpanded] = useState(false)
  const [skipChart, setSkipChart] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [ociExpandedKey, setOciExpandedKey] = useState<string | null>(null)
  const [ociSkipped, setOciSkipped] = useState<Set<string>>(new Set())
  const toggleOciSkip = (key: string) =>
    setOciSkipped(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n })
  const toggleOciExpand = (key: string) => setOciExpandedKey(k => (k === key ? null : key))

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setChartExpanded(false)
    setConfirmed(false)
    setOciExpandedKey(null)
    setOciSkipped(new Set())
    setLoading(true)
    getCloudBeesProdParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to fetch CloudBees prod state.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setParams(null); setError(''); setResult(null); setConfirmed(false); onClose()
  }

  async function handleApply() {
    if (!params) return
    setError('')
    setApplying(true)
    try {
      const pe = params.envs['prod-east']
      const gc = params.envs['gc-prod-west']
      // Send the controller TARGET AMI (drives both tfvars eks_ami + controller nodeclass).
      const peCtrlAmi  = pe.controller_has_update ? pe.controller_target_ami! : ''
      const gcCtrlAmi  = gc.controller_has_update ? gc.controller_target_ami! : ''
      const gcAgentAmi = gc.agent_has_update ? gc.latest_agent_ami! : ''

      const res = await applyCloudBeesProdChanges({
        branch: params.branch,
        new_chart_version: params.chart.has_update && !skipChart ? params.chart.latest_version ?? undefined : undefined,
        new_chart_tag:     params.chart.has_update && !skipChart ? params.chart.latest_tag ?? undefined     : undefined,
        prod_east_controller_ami:      peCtrlAmi || undefined,
        prod_east_controller_ami_name: pe.latest_controller_ami_name ?? undefined,
        prod_east_agent_ami:           pe.agent_has_update      ? pe.latest_agent_ami ?? undefined       : undefined,
        prod_east_agent_ami_name:      pe.latest_agent_ami_name ?? undefined,
        gc_prod_west_controller_ami:      gcCtrlAmi  || undefined,
        gc_prod_west_controller_ami_name: gc.latest_controller_ami_name ?? undefined,
        gc_prod_west_agent_ami:           gcAgentAmi || undefined,
        gc_prod_west_agent_ami_name:      gc.latest_agent_ami_name ?? undefined,
        karpenter_version: kar?.has_update && !ociSkipped.has('karpenter') ? kar.latest_version ?? undefined : undefined,
        karpenter_crd_version: crd?.has_update && !ociSkipped.has('karpenter-crd') ? crd.latest_version ?? undefined : undefined,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply changes.'))
    } finally {
      setApplying(false)
    }
  }

  const pe = params?.envs['prod-east']
  const gc = params?.envs['gc-prod-west']
  const kar = params?.oci_repos.find(r => r.key === 'karpenter')
  const crd = params?.oci_repos.find(r => r.key === 'karpenter-crd')
  const totalUpdates = params ? (
    (params.chart.has_update && !skipChart ? 1 : 0) +
    (pe?.controller_has_update ? 1 : 0) +
    (pe?.agent_has_update ? 1 : 0) +
    (gc?.controller_has_update ? 1 : 0) +
    (gc?.agent_has_update ? 1 : 0) +
    params.oci_repos.filter(r => r.has_update && !ociSkipped.has(r.key)).length
  ) : 0

  return (
    <Modal open={open} onClose={handleClose} title="CloudBees CI — Prod Maintenance" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Changes committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {result.committed_files.length} file{result.committed_files.length !== 1 ? 's' : ''} updated on{' '}
                <span className="font-mono">{params?.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          <p className="text-xs ds-u-color--muted">
            FluxCD will reconcile and apply the updated chart automatically after the branch is merged to main.
          </p>
          <a href={result.branch_url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium">
            View branch on GitHub <ExternalLink size={13} />
          </a>
          <button onClick={handleClose} className="btn-secondary w-full mt-2">Close</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-4 justify-center">
              <Loader2 size={16} className="animate-spin" /> Fetching current state...
            </div>
          )}
          {error && !loading && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
          )}
          {params && (
            <>
              {/* Branch */}
              <div className="flex items-center justify-between">
                <div className="text-xs ds-u-color--muted">
                  Branch: <span className="font-mono text-gray-800">{params.branch}</span>
                  {params.branch_created && <span className="ml-2 text-green-600">(just created)</span>}
                </div>
                <a href={params.branch_url} target="_blank" rel="noopener noreferrer"
                   className="flex items-center gap-1 text-xs text-cms-blue hover:underline">
                  GitHub <ExternalLink size={10} />
                </a>
              </div>

              {/* Commercial Prod AMIs */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  {pe?.label} — AMIs
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Node</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                      </tr>
                    </thead>
                    <tbody>
                      <CBAmiRow label="Controller (gold image)" current={pe?.current_controller_ami ?? null} latest={pe?.controller_target_ami ?? null} latestName={pe?.latest_controller_ami_name ?? null} hasUpdate={pe?.controller_has_update ?? false} error={pe?.controller_error ?? null} drift={pe?.controller_drift ?? false} />
                      <CBAmiRow label="Agent (gold image)"      current={pe?.current_agent_ami ?? null}       latest={pe?.latest_agent_ami ?? null}       latestName={pe?.latest_agent_ami_name ?? null}       hasUpdate={pe?.agent_has_update ?? false}       error={pe?.agent_error ?? null} />
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Gov Cloud Prod AMIs */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  {gc?.label} — AMIs
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Node</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                      </tr>
                    </thead>
                    <tbody>
                      <CBAmiRow label="Controller (gold image)" current={gc?.current_controller_ami ?? null} latest={gc?.controller_target_ami ?? null} latestName={gc?.latest_controller_ami_name ?? null} hasUpdate={gc?.controller_has_update ?? false} error={gc?.controller_error ?? null} drift={gc?.controller_drift ?? false} />
                      <CBAmiRow label="Agent (gold image)"      current={gc?.current_agent_ami ?? null}       latest={gc?.latest_agent_ami ?? null}       latestName={gc?.latest_agent_ami_name ?? null}       hasUpdate={gc?.agent_has_update ?? false}       error={gc?.agent_error ?? null} />
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Chart version */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  CloudBees Core Chart
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Component</th>
                        <th className="text-left px-3 py-2 font-medium">Current</th>
                        <th className="text-left px-3 py-2 font-medium">Latest</th>
                        <th className="px-3 py-2 w-8"></th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        className={`border-t border-gray-100 ${params.chart.has_update ? 'cursor-pointer hover:bg-gray-50' : ''}`}
                        onClick={() => params.chart.has_update && setChartExpanded(e => !e)}
                      >
                        <td className="px-3 py-2">
                          <div className="text-xs font-medium text-gray-800">CloudBees Core</div>
                          <div className="text-xs ds-u-color--muted font-mono">tag: {params.chart.current_tag || '—'}</div>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs ds-u-color--muted">{params.chart.current_version || '—'}</td>
                        <td className="px-3 py-2">
                          {params.chart.has_update ? (
                            <div className="flex flex-col gap-1">
                              <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${
                                params.chart.release_notes?.has_breaking ? 'bg-orange-100 text-orange-700' : 'bg-green-100 text-green-700'
                              } ${skipChart ? 'opacity-40 line-through' : ''}`}>
                                {params.chart.release_notes?.has_breaking && <AlertTriangle size={10} />}
                                {params.chart.latest_version}
                              </span>
                              <label
                                className="flex items-center gap-1 text-[11px] ds-u-color--muted cursor-pointer select-none"
                                onClick={e => e.stopPropagation()}
                              >
                                <input
                                  type="checkbox"
                                  checked={skipChart}
                                  onChange={() => setSkipChart(v => !v)}
                                  className="rounded border-gray-300 h-3 w-3"
                                />
                                Skip (stay on {params.chart.current_version || 'current'})
                              </label>
                            </div>
                          ) : (
                            <span className="text-xs ds-u-color--muted">up to date</span>
                          )}
                        </td>
                        <td className="px-3 py-2 ds-u-color--muted text-xs">
                          {params.chart.has_update && (chartExpanded ? '▲' : '▼')}
                        </td>
                      </tr>
                      {params.chart.has_update && chartExpanded && (
                        <tr className="border-t border-gray-100 bg-gray-50">
                          <td colSpan={4} className="px-4 py-3">
                            {params.chart.release_notes ? (
                              <CBReleaseNotesPanel rn={params.chart.release_notes} />
                            ) : (
                              <div className="flex items-center gap-2 text-xs ds-u-color--muted">
                                <Loader2 size={11} className="animate-spin" /> Loading release notes…
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  <div className="px-3 py-1.5 border-t border-gray-100 text-xs ds-u-color--muted font-mono">
                    {params.chart.file}
                  </div>
                </div>
              </div>

              {/* Karpenter OCI repositories (shared base for all clusters) */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  OCI Repositories (tag-based) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.oci_repos}
                  expandedKey={ociExpandedKey}
                  onToggle={toggleOciExpand}
                  skipped={ociSkipped}
                  onToggleSkip={toggleOciSkip}
                />
                <p className="text-xs ds-u-color--muted mt-1.5">
                  Shared across all CBJ clusters (base overlay). Karpenter and Karpenter CRD must always be updated to the same tag.
                </p>
              </div>

              {/* Post-merge steps */}
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1">
                <p className="font-semibold">Pull the <span className="font-mono">{params.branch}</span> branch locally:</p>
                <ol className="list-decimal list-inside space-y-0.5 text-blue-700">
                  <li>Run <span className="font-mono">terraform plan</span> + <span className="font-mono">apply</span></li>
                  <li>Run the Kubernetes apply: <span className="font-mono">kubectl apply -k .</span></li>
                  <li>Wait for Karpenter nodes to cycle</li>
                  <li>Login to the Jenkins instance</li>
                  <li>Run <span className="font-mono">Cluster Ops → plugins-upgrade</span> pipeline in CJOC</li>
                  <li>Run <span className="font-mono">Cluster Ops → managed-master-update</span> pipeline in CJOC</li>
                  <li>Drain the node CJOC is running on and wait for Karpenter to replace it and CJOC to come back up</li>
                </ol>
              </div>

              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
              )}

              <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-3 py-3">
                <input
                  type="checkbox"
                  id="cbj-prod-confirm"
                  className="mt-0.5 flex-shrink-0 accent-red-600"
                  checked={confirmed}
                  onChange={e => setConfirmed(e.target.checked)}
                />
                <label htmlFor="cbj-prod-confirm" className="text-sm text-red-800 cursor-pointer">
                  I confirm this is the <strong>prod environment</strong> and I have reviewed all changes above.
                </label>
              </div>

              <p className="text-xs ds-u-color--muted">
                <span className="font-mono">main</span> is merged into the maintenance branch
                before anything is written, so a commit cannot land on a stale base.
              </p>

              <div className="flex gap-3 pt-1">
                <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={applying || totalUpdates === 0 || !confirmed}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying ? <><Loader2 size={15} className="animate-spin" /> Committing...</> : `Apply ${totalUpdates} update${totalUpdates !== 1 ? 's' : ''}`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

function JFrogDevModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<JFrogDevParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ committed_files: string[]; branch_url: string } | null>(null)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const toggleSkip = (key: string) =>
    setSkipped(s => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key)
      else n.add(key)
      return n
    })

  function toggleExpand(key: string) {
    setExpandedKey(prev => prev === key ? null : key)
  }

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setLoading(true)
    getJFrogDevParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to fetch JFrog dev state.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setParams(null)
    setError('')
    setResult(null)
    onClose()
  }

  async function handleApply() {
    if (!params) return
    setError('')
    setApplying(true)
    try {
      const helmVersions: Record<string, string> = {}
      for (const row of params.helm_charts) {
        if (row.has_update && row.latest_version && !skipped.has(row.key)) helmVersions[row.key] = row.latest_version
      }
      const ociVersions: Record<string, string> = {}
      for (const row of params.oci_repos) {
        if (row.has_update && row.latest_version && !skipped.has(row.key)) ociVersions[row.key] = row.latest_version
      }
      const res = await applyJFrogDevChanges({
        branch: params.branch,
        // Either file can be the stale one: prod's nodeclass patches the base, so
        // tfvars can be current while the nodeclass is not. The backend skips a
        // file whose content already matches, so sending it is safe either way.
        new_ami: (params.ami.has_update || params.ami.has_update_nodeclass) && params.ami.latest_ami
          ? params.ami.latest_ami : '',
        new_ami_name: params.ami.has_update ? (params.ami.latest_ami_name || '') : '',
        helm_versions: helmVersions,
        oci_versions: ociVersions,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply changes.'))
    } finally {
      setApplying(false)
    }
  }

  const totalUpdates = params
    ? (params.ami.has_update || params.ami.has_update_nodeclass ? 1 : 0) +
      params.helm_charts.filter(r => r.has_update && !skipped.has(r.key)).length +
      params.oci_repos.filter(r => r.has_update && !skipped.has(r.key)).length
    : 0

  const hasBreaking =
    params?.helm_charts.some(r => r.has_update && r.is_breaking) ||
    params?.oci_repos.some(r => r.has_update && r.is_breaking)

  return (
    <Modal open={open} onClose={handleClose} title="JFrog — Dev Maintenance" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Changes committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {result.committed_files.length} file{result.committed_files.length !== 1 ? 's' : ''} updated on{' '}
                <span className="font-mono">{params?.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          <a
            href={result.branch_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            View branch on GitHub <ExternalLink size={13} />
          </a>

          {/* Post-merge next steps */}
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1.5">
            <p className="font-semibold">After merging the maintenance branch:</p>
            <ol className="list-decimal list-inside space-y-1 text-blue-700">
              <li><span className="font-mono bg-blue-100 px-1 rounded">git pull</span> the repo locally</li>
              <li>Run <span className="font-mono bg-blue-100 px-1 rounded">terraform apply</span> from <span className="font-mono">terraform/envs/jfrog/envs/dev/</span></li>
              <li><span className="font-mono bg-blue-100 px-1 rounded">cd</span> into <span className="font-mono">Kubernetes/envs/jfrog/envs/dev/</span> and run <span className="font-mono bg-blue-100 px-1 rounded">kubectl apply -k .</span></li>
            </ol>
            <a
              href="https://confluenceent.cms.gov/spaces/COM/pages/1384893085/Runbook+JFrog+Maintenance"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:underline font-medium mt-1"
            >
              JFrog Maintenance Runbook <ExternalLink size={10} />
            </a>
          </div>

          <button onClick={handleClose} className="btn-secondary w-full">Close</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm ds-u-color--muted">
              <Loader2 size={16} className="animate-spin" />
              Fetching current state and latest versions…
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {params && (
            <>
              {/* Branch status */}
              <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm">
                  <GitBranch size={14} className="ds-u-color--muted" />
                  <span className="font-mono text-gray-700">{params.branch}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    params.branch_created
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-green-100 text-green-700'
                  }`}>
                    {params.branch_created ? 'Created' : 'Found'}
                  </span>
                </div>
                <a
                  href={params.branch_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
                >
                  GitHub <ExternalLink size={11} />
                </a>
              </div>

              {/* AMI section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  AMI (EKS {params.ami.eks_version})
                </p>
                {params.ami.error ? (
                  <p className="text-xs text-red-600 flex items-center gap-1">
                    <AlertTriangle size={11} /> {params.ami.error}
                  </p>
                ) : (
                  <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-gray-50 text-xs ds-u-color--muted">
                          <th className="text-left px-3 py-2 font-medium">File</th>
                          <th className="text-left px-3 py-2 font-medium">Current</th>
                          <th className="text-left px-3 py-2 font-medium">Latest</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-t border-gray-100">
                          <td className="px-3 py-2 text-xs ds-u-color--muted font-mono">terraform.tfvars</td>
                          <td className="px-3 py-2 font-mono text-xs text-gray-700">{params.ami.current_ami || '—'}</td>
                          <td className="px-3 py-2">
                            {params.ami.has_update ? (
                              <span className="font-mono text-xs text-green-700 font-medium">{params.ami.latest_ami}</span>
                            ) : (
                              <span className="text-xs ds-u-color--muted">up to date</span>
                            )}
                          </td>
                        </tr>
                        <tr className="border-t border-gray-100">
                          <td className="px-3 py-2 text-xs ds-u-color--muted font-mono">karpenter-node-class.yaml</td>
                          <td className="px-3 py-2 font-mono text-xs text-gray-700">{params.ami.current_ami_nodeclass || '—'}</td>
                          <td className="px-3 py-2">
                            {!params.ami.current_ami_nodeclass ? (
                              <span className="text-xs ds-u-color--muted">not tracked</span>
                            ) : params.ami.has_update_nodeclass ? (
                              <span className="font-mono text-xs text-green-700 font-medium">{params.ami.latest_ami}</span>
                            ) : (
                              <span className="text-xs ds-u-color--muted">up to date</span>
                            )}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    {params.ami.latest_ami_name && (
                      <p className="px-3 py-1.5 text-xs ds-u-color--muted border-t border-gray-100 font-mono">
                        {params.ami.latest_ami_name}
                      </p>
                    )}
                  </div>
                )}

                {/* AMI release notes */}
                {params.ami.release_notes && (
                  <div className="mt-3">
                    <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-1.5">
                      Gold Image Release Notes
                      {params.ami.release_notes.date && (
                        <span className="ml-2 font-normal normal-case ds-u-color--muted">
                          {params.ami.release_notes.date}
                        </span>
                      )}
                    </p>
                    {params.ami.release_notes.available && params.ami.release_notes.notes?.length ? (
                      <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
                        <ul className="space-y-1">
                          {params.ami.release_notes.notes.map((note, i) => (
                            <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                              <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
                              <span>{note}</span>
                            </li>
                          ))}
                        </ul>
                        {params.ami.release_notes.source_url && (
                          <a
                            href={params.ami.release_notes.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline mt-2"
                          >
                            Full release notes <ExternalLink size={10} />
                          </a>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs ds-u-color--muted italic">
                        {params.ami.release_notes.error
                          ? `Release notes unavailable: ${params.ami.release_notes.error}`
                          : 'No release notes available for this AMI.'}
                        {params.ami.release_notes.source_url && (
                          <a
                            href={params.ami.release_notes.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-2 text-cms-blue hover:underline not-italic"
                          >
                            View page <ExternalLink size={10} className="inline" />
                          </a>
                        )}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* Helm charts section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  Helm Charts (HelmRelease) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.helm_charts}
                  expandedKey={expandedKey}
                  onToggle={toggleExpand}
                  skipped={skipped}
                  onToggleSkip={toggleSkip}
                />
              </div>

              {/* OCI repositories section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  OCI Repositories (tag-based) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.oci_repos}
                  expandedKey={expandedKey}
                  onToggle={toggleExpand}
                  skipped={skipped}
                  onToggleSkip={toggleSkip}
                />
                <p className="text-xs ds-u-color--muted mt-1.5">
                  Karpenter and Karpenter CRD must always be updated to the same tag.
                </p>
              </div>

              {/* Breaking change warning */}
              {hasBreaking && (
                <div className="flex items-start gap-2 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2.5 text-xs text-orange-800">
                  <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-orange-500" />
                  <span>
                    <strong>Review release notes before applying.</strong> One or more components have minor or major
                    version bumps — check for renamed values, schema migrations, or required manual steps.
                  </span>
                </div>
              )}

              {totalUpdates === 0 && (
                <div className="text-center py-4 text-sm ds-u-color--muted">
                  All components are already up to date.
                </div>
              )}

              {/* Post-merge steps reminder */}
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1.5">
                <p className="font-semibold">After merging the maintenance branch:</p>
                <ol className="list-decimal list-inside space-y-1 text-blue-700">
                  <li><span className="font-mono bg-blue-100 px-1 rounded">git pull</span> the repo locally</li>
                  <li>Run <span className="font-mono bg-blue-100 px-1 rounded">terraform apply</span> from <span className="font-mono">terraform/envs/jfrog/envs/dev/</span></li>
                  <li><span className="font-mono bg-blue-100 px-1 rounded">cd</span> into <span className="font-mono">Kubernetes/envs/jfrog/envs/dev/</span> and run <span className="font-mono bg-blue-100 px-1 rounded">kubectl apply -k .</span></li>
                </ol>
                <a
                  href="https://confluenceent.cms.gov/spaces/COM/pages/1384893085/Runbook+JFrog+Maintenance"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-blue-600 hover:underline font-medium mt-1"
                >
                  JFrog Maintenance Runbook <ExternalLink size={10} />
                </a>
              </div>

              <p className="text-xs ds-u-color--muted">
                <span className="font-mono">main</span> is merged into the maintenance branch
                before anything is written, so a commit cannot land on a stale base.
              </p>

              <div className="flex gap-3">
                <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={applying || totalUpdates === 0}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying && <Loader2 size={15} className="animate-spin" />}
                  {applying ? 'Applying…' : `Apply ${totalUpdates} Update${totalUpdates !== 1 ? 's' : ''}`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

// ─── EKS Control Plane Upgrade Modal ──────────────────────────────────────────

function PlutoReportPanel({ report }: { report: PlutoReport }) {
  if (!report.available) {
    return (
      <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 text-xs ds-u-color--muted">
        Deprecated API scan unavailable{report.error ? `: ${report.error}` : '.'}
      </div>
    )
  }
  const items = report.items ?? []
  if (items.length === 0) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2.5 text-xs text-green-800">
        <CheckCircle size={13} className="flex-shrink-0 mt-0.5 text-green-600" />
        <span>
          <strong>No deprecated or removed APIs found.</strong> pluto scanned {report.files_scanned} manifest
          {report.files_scanned !== 1 ? 's' : ''} against Kubernetes v{report.target_version}.
        </span>
      </div>
    )
  }
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-800">
        <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-red-500" />
        <span>
          <strong>{report.removed_count} removed</strong> and{' '}
          <strong>{report.deprecated_count} deprecated</strong> API
          {(report.removed_count ?? 0) + (report.deprecated_count ?? 0) !== 1 ? 's' : ''} in{' '}
          {report.files_scanned} scanned manifest{report.files_scanned !== 1 ? 's' : ''}. Fix the removed ones
          before upgrading the control plane, or those objects stop reconciling.
        </span>
      </div>
      <div className="rounded-lg border border-gray-100 overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-gray-50 ds-u-color--muted">
              <th className="text-left px-3 py-2 font-medium">Kind</th>
              <th className="text-left px-3 py-2 font-medium">API version</th>
              <th className="text-left px-3 py-2 font-medium">Replace with</th>
              <th className="text-left px-3 py-2 font-medium">File</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={`${it.file}-${it.kind}-${i}`} className={i > 0 ? 'border-t border-gray-100' : ''}>
                <td className="px-3 py-2">
                  <span className="font-medium text-gray-800">{it.kind}</span>
                  {it.name && <span className="ds-u-color--muted"> / {it.name}</span>}
                  <span
                    className={`ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      it.removed ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
                    }`}
                  >
                    {it.removed ? `removed in ${it.removed_in}` : `deprecated in ${it.deprecated_in}`}
                  </span>
                </td>
                <td className="px-3 py-2 font-mono text-gray-600">{it.api_version}</td>
                <td className="px-3 py-2 font-mono text-gray-600">{it.replacement_api || '—'}</td>
                <td className="px-3 py-2 font-mono ds-u-color--muted truncate max-w-[16rem]" title={it.file}>
                  {it.file}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {report.scanned_paths && (
        <p className="text-[11px] ds-u-color--muted">
          Scanned: {report.scanned_paths.join(', ')}
        </p>
      )}
    </div>
  )
}

function K8sNotesPanel({ notes }: { notes: K8sReleaseNotes }) {
  if (!notes.available) {
    return (
      <p className="text-xs ds-u-color--muted italic">
        {notes.error ? `Release notes unavailable: ${notes.error}` : 'No release notes available.'}
        {notes.source_url && (
          <a href={notes.source_url} target="_blank" rel="noopener noreferrer" className="ml-1 text-cms-blue hover:underline not-italic">
            Changelog
          </a>
        )}
      </p>
    )
  }
  const group = (title: string, bullets: string[] | undefined, tone: string) =>
    bullets && bullets.length > 0 ? (
      <div>
        <p className={`text-[11px] font-semibold uppercase tracking-wide mb-1 ${tone}`}>{title}</p>
        <ul className="space-y-1">
          {bullets.map((b, i) => (
            <li key={i} className="text-xs text-gray-600 flex gap-1.5">
              <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      </div>
    ) : null

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 space-y-3">
      {group('Urgent upgrade notes', notes.urgent, 'text-red-600')}
      {group('Deprecations', notes.deprecations, 'text-amber-600')}
      {group('API changes', notes.api_changes, 'ds-u-color--muted')}
      {notes.source_url && (
        <a
          href={notes.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          Full Kubernetes {notes.version} changelog <ExternalLink size={10} />
        </a>
      )}
    </div>
  )
}

function EksUpgradeModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<EksUpgradeParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null)
  const [targetVersion, setTargetVersion] = useState('')
  const [preview, setPreview] = useState<EksUpgradePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [confirmProd, setConfirmProd] = useState(false)
  const [result, setResult] = useState<EksUpgradeApplyResult | null>(null)

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setSelectedCluster(null)
    setTargetVersion('')
    setPreview(null)
    setConfirmProd(false)
    setLoading(true)
    getEksUpgradeParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to read cluster versions.')))
      .finally(() => setLoading(false))
  }, [open])

  const cluster = params?.clusters.find(c => c.key === selectedCluster) ?? null

  function pickCluster(key: string) {
    const c = params?.clusters.find(x => x.key === key) ?? null
    setSelectedCluster(key)
    setPreview(null)
    setConfirmProd(false)
    setTargetVersion(c?.next_version ?? '')
  }

  async function loadPreview(version: string) {
    if (!selectedCluster || !version) return
    setError('')
    setPreview(null)
    setPreviewLoading(true)
    try {
      setPreview(await getEksUpgradePreview(selectedCluster, version))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to build the upgrade preview.'))
    } finally {
      setPreviewLoading(false)
    }
  }

  async function handleApply() {
    if (!params || !cluster || !targetVersion) return
    setError('')
    setApplying(true)
    try {
      const res = await applyEksUpgrade({
        branch: params.branch,
        cluster: cluster.key,
        target_version: targetVersion,
        new_ami: preview?.gold_image.ami_id ?? '',
        new_ami_name: preview?.gold_image.ami_name ?? '',
        confirm_prod: confirmProd,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply the upgrade.'))
    } finally {
      setApplying(false)
    }
  }

  const blockedByRemoved = (preview?.pluto.removed_count ?? 0) > 0
  const canApply =
    !!cluster &&
    !!targetVersion &&
    !!preview &&
    !previewLoading &&
    (!cluster.is_prod || confirmProd)

  return (
    <Modal open={open} onClose={onClose} title="EKS Control Plane Upgrade" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Upgrade committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {cluster?.label} targeted at <span className="font-mono">{targetVersion}</span> on{' '}
                <span className="font-mono">{result.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          {result.errors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 space-y-1">
              {result.errors.map(e => (
                <p key={e} className="text-xs text-red-700">{e}</p>
              ))}
            </div>
          )}
          <a
            href={result.branch_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            View branch on GitHub <ExternalLink size={13} />
          </a>
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1.5">
            <p className="font-semibold">After merging the maintenance branch:</p>
            <ol className="list-decimal list-inside space-y-1 text-blue-700">
              <li>Run <span className="font-mono bg-blue-100 px-1 rounded">terraform apply</span> for this env to move the control plane</li>
              <li>Wait for the control-plane upgrade to finish before the nodes roll</li>
              <li>Apply the nodeclass so Karpenter replaces nodes onto the matching gold image</li>
              <li>Upgrade the EKS add-ons to versions supported on the new minor</li>
            </ol>
          </div>
          <button onClick={onClose} className="btn-primary w-full">Done</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-6 justify-center">
              <Loader2 size={15} className="animate-spin" /> Reading cluster versions…
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {params && (
            <>
              <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm">
                  <GitBranch size={14} className="ds-u-color--muted" />
                  <span className="font-mono text-gray-700">{params.branch}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    params.branch_exists ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'
                  }`}>
                    {params.branch_exists ? 'Found' : 'Not cut yet'}
                  </span>
                </div>
                <a
                  href={params.branch_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
                >
                  GitHub <ExternalLink size={11} />
                </a>
              </div>

              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  Clusters — pick one to upgrade
                </p>
                <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-gray-50 text-xs ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Cluster</th>
                        <th className="text-left px-3 py-2 font-medium">Region</th>
                        <th className="text-left px-3 py-2 font-medium" title="The version the control plane is running, read from AWS">Running</th>
                        <th className="text-left px-3 py-2 font-medium">Available</th>
                      </tr>
                    </thead>
                    <tbody>
                      {params.clusters.map((c, i) => (
                        <tr
                          key={c.key}
                          onClick={() => pickCluster(c.key)}
                          className={`cursor-pointer ${i > 0 ? 'border-t border-gray-100' : ''} ${
                            selectedCluster === c.key ? 'bg-blue-50' : 'hover:bg-gray-50'
                          }`}
                        >
                          <td className="px-3 py-2">
                            <span className="text-xs font-medium text-gray-800">{c.label}</span>
                            {c.is_prod && (
                              <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700">
                                prod
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 font-mono text-xs ds-u-color--muted">{c.region}</td>
                          <td className="px-3 py-2 font-mono text-xs">
                            {/* Running first, because that is the question being asked.
                                tfvars can be bumped well before anyone applies it. */}
                            <span className="text-gray-700">{c.live_version || (c.live_error ? '—' : c.current_version || '—')}</span>
                            {c.version_drift && (
                              <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-800"
                                    title={`terraform.tfvars declares ${c.current_version}, but the control plane is running ${c.live_version}. The declared bump has not been applied.`}>
                                tfvars says {c.current_version}
                              </span>
                            )}
                            {!c.live_version && (
                              <span className="ml-2 text-[10px] ds-u-color--muted"
                                    title={c.live_error || 'The running version could not be read'}>
                                declared only
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs">
                            {c.error ? (
                              <span className="text-red-600" title={c.error}>lookup failed</span>
                            ) : c.upgrade_targets.length > 0 ? (
                              <span className="text-green-700 font-medium">
                                {c.upgrade_targets.map(v => v.version).join(', ')}
                              </span>
                            ) : (
                              <span className="ds-u-color--muted">on the latest</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {cluster && (
                <div className="space-y-4 border-t border-gray-100 pt-4">
                  <div className="flex items-end gap-3">
                    <div className="flex-1">
                      <label className="block text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-1.5">
                        Target version for {cluster.label}
                      </label>
                      <select
                        value={targetVersion}
                        onChange={e => { setTargetVersion(e.target.value); setPreview(null) }}
                        className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm"
                      >
                        <option value="">Select a version…</option>
                        {cluster.upgrade_targets.map(v => (
                          <option key={v.version} value={v.version}>
                            {v.version}
                            {v.default ? ' (EKS default)' : ''}
                            {v.status && v.status !== 'STANDARD_SUPPORT' ? ` — ${v.status.toLowerCase().replace(/_/g, ' ')}` : ''}
                            {v.end_of_standard_support ? ` — standard support ends ${v.end_of_standard_support}` : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                    <button
                      onClick={() => loadPreview(targetVersion)}
                      disabled={!targetVersion || previewLoading}
                      className="btn-secondary flex items-center gap-2"
                    >
                      {previewLoading && <Loader2 size={14} className="animate-spin" />}
                      {previewLoading ? 'Scanning…' : 'Check upgrade'}
                    </button>
                  </div>

                  {cluster.upgrade_targets.length === 0 && !cluster.error && (
                    <p className="text-xs ds-u-color--muted">
                      This cluster is already on the newest version AWS offers in {cluster.region}.
                    </p>
                  )}

                  {previewLoading && (
                    <div className="flex items-center gap-2 text-sm ds-u-color--muted py-4 justify-center">
                      <Loader2 size={15} className="animate-spin" />
                      Fetching release notes and scanning manifests with pluto…
                    </div>
                  )}

                  {preview && (
                    <>
                      <div>
                        <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                          Deprecated APIs and CRDs (pluto, scanned from {preview.ref_scanned})
                        </p>
                        <PlutoReportPanel report={preview.pluto} />
                      </div>

                      <div>
                        <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                          Kubernetes {preview.target_version} release notes
                        </p>
                        <K8sNotesPanel notes={preview.release_notes} />
                      </div>

                      <div>
                        <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                          Gold image for EKS {preview.target_version}
                        </p>
                        {preview.gold_image.ami_id ? (
                          <div className="rounded-lg border border-gray-100 px-3 py-2.5 text-xs">
                            <p className="font-mono text-gray-700">{preview.gold_image.ami_id}</p>
                            <p className="font-mono ds-u-color--muted mt-0.5">{preview.gold_image.ami_name}</p>
                            <p className="ds-u-color--muted mt-1.5">
                              Apply writes this to <span className="font-mono">{cluster.tfvars_path}</span>
                              {cluster.nodeclass_paths.length > 0
                                ? ' and the Karpenter nodeclass, so the nodes move with the control plane.'
                                : '. This cluster inherits its nodeclass AMI from the shared base.'}
                            </p>
                          </div>
                        ) : (
                          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
                            <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-amber-500" />
                            <span>
                              {preview.gold_image.error || 'No gold image found for this version.'} Apply will
                              still bump <span className="font-mono">eks_version</span>, but the nodes will stay
                              on the current image until a gold image for {preview.target_version} is published.
                            </span>
                          </div>
                        )}
                      </div>

                      {blockedByRemoved && (
                        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 text-xs text-red-800">
                          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-red-500" />
                          <span>
                            <strong>Removed APIs are still in the manifests.</strong> Migrate them first, then
                            re-run the check. Applying now bumps the version but leaves those objects broken on
                            the new control plane.
                          </span>
                        </div>
                      )}

                      {cluster.is_prod && (
                        <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer select-none bg-purple-50 border border-purple-200 rounded-lg px-3 py-2.5">
                          <input
                            type="checkbox"
                            checked={confirmProd}
                            onChange={e => setConfirmProd(e.target.checked)}
                            className="rounded border-gray-300 mt-0.5"
                          />
                          <span className="text-xs text-purple-900">
                            I confirm this is the <strong>prod</strong> cluster {cluster.label}, and I have
                            reviewed the deprecated API report and release notes above.
                          </span>
                        </label>
                      )}

                      <p className="text-xs ds-u-color--muted">
                        <span className="font-mono">main</span> is merged into the maintenance branch
                        before anything is written, so a commit cannot land on a stale base.
                      </p>
                    </>
                  )}
                </div>
              )}

              <div className="flex gap-3">
                <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={!canApply || applying}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying && <Loader2 size={15} className="animate-spin" />}
                  {applying ? 'Applying…' : targetVersion ? `Commit upgrade to ${targetVersion}` : 'Commit upgrade'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

// ─── Shared Base Helm Charts Modal ────────────────────────────────────────────

function BaseChartsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<BaseChartsParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ committed_files: string[]; branch_url: string } | null>(null)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<Set<string>>(new Set())

  const toggleSkip = (key: string) =>
    setSkipped(s => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key)
      else n.add(key)
      return n
    })

  function toggleExpand(key: string) {
    setExpandedKey(prev => (prev === key ? null : key))
  }

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setSkipped(new Set())
    setLoading(true)
    getBaseChartsParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to fetch base chart state.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setParams(null)
    setError('')
    setResult(null)
    onClose()
  }

  async function handleApply() {
    if (!params) return
    setError('')
    setApplying(true)
    try {
      const helmVersions: Record<string, string> = {}
      for (const row of params.helm_charts) {
        if (row.has_update && row.latest_version && !skipped.has(row.key)) helmVersions[row.key] = row.latest_version
      }
      const res = await applyBaseChartsChanges({
        branch: params.branch,
        helm_versions: helmVersions,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply changes.'))
    } finally {
      setApplying(false)
    }
  }

  const totalUpdates = params
    ? params.helm_charts.filter(r => r.has_update && !skipped.has(r.key)).length
    : 0
  const hasBreaking = params?.helm_charts.some(r => r.has_update && r.is_breaking)

  return (
    <Modal open={open} onClose={handleClose} title="Base Helm Charts — Shared" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Changes committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {result.committed_files.length} file{result.committed_files.length !== 1 ? 's' : ''} updated on{' '}
                <span className="font-mono">{params?.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          <a
            href={result.branch_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            View branch on GitHub <ExternalLink size={13} />
          </a>
          <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
            <p className="font-semibold">These charts are shared.</p>
            <p className="mt-0.5 text-amber-700">
              Every JFrog and CloudBees cluster reconciles <span className="font-mono">kubernetes/base/releases</span>,
              so plan the rollout across both tools rather than one overlay at a time.
            </p>
          </div>
          <button onClick={handleClose} className="btn-primary w-full">Done</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-6 justify-center">
              <Loader2 size={15} className="animate-spin" /> Reading base charts…
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {params && (
            <>
              <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm">
                  <GitBranch size={14} className="ds-u-color--muted" />
                  <span className="font-mono text-gray-700">{params.branch}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    params.branch_exists ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'
                  }`}>
                    {params.branch_exists ? 'Found' : 'Not cut yet'}
                  </span>
                </div>
                <a
                  href={params.branch_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
                >
                  GitHub <ExternalLink size={11} />
                </a>
              </div>

              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-2.5 text-xs text-blue-800">
                <span className="font-mono">kubernetes/base/releases</span> is pulled by both the JFrog and
                CloudBees clusters. Bumping a chart here changes every environment that reconciles it.
              </div>

              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  Shared Charts — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.helm_charts}
                  expandedKey={expandedKey}
                  onToggle={toggleExpand}
                  skipped={skipped}
                  onToggleSkip={toggleSkip}
                />
              </div>

              {hasBreaking && (
                <div className="flex items-start gap-2 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2.5 text-xs text-orange-800">
                  <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-orange-500" />
                  <span>
                    <strong>Review release notes before applying.</strong> One or more charts have minor or major
                    version bumps, and these land in every cluster at once.
                  </span>
                </div>
              )}

              {totalUpdates === 0 && (
                <div className="text-center py-4 text-sm ds-u-color--muted">
                  All shared base charts are already up to date.
                </div>
              )}

              <p className="text-xs ds-u-color--muted">
                <span className="font-mono">main</span> is merged into the maintenance branch
                before anything is written, so a commit cannot land on a stale base.
              </p>

              <div className="flex gap-3">
                <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={applying || totalUpdates === 0}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying && <Loader2 size={15} className="animate-spin" />}
                  {applying ? 'Applying…' : `Apply ${totalUpdates} Update${totalUpdates !== 1 ? 's' : ''}`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

// ─── JFrog Prod Maintenance Modal ─────────────────────────────────────────────

function JFrogProdModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [params, setParams] = useState<JFrogDevParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ committed_files: string[]; branch_url: string } | null>(null)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const toggleSkip = (key: string) =>
    setSkipped(s => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key)
      else n.add(key)
      return n
    })
  const [prodConfirmed, setProdConfirmed] = useState(false)

  function toggleExpand(key: string) {
    setExpandedKey(prev => prev === key ? null : key)
  }

  useEffect(() => {
    if (!open) return
    setParams(null)
    setError('')
    setResult(null)
    setProdConfirmed(false)
    setLoading(true)
    getJFrogProdParams()
      .then(setParams)
      .catch((err: any) => setError(apiErrorMessage(err, 'Failed to fetch JFrog prod state.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setParams(null)
    setError('')
    setResult(null)
    setProdConfirmed(false)
    onClose()
  }

  async function handleApply() {
    if (!params) return
    setError('')
    setApplying(true)
    try {
      const helmVersions: Record<string, string> = {}
      for (const row of params.helm_charts) {
        if (row.has_update && row.latest_version && !skipped.has(row.key)) helmVersions[row.key] = row.latest_version
      }
      const ociVersions: Record<string, string> = {}
      for (const row of params.oci_repos) {
        if (row.has_update && row.latest_version && !skipped.has(row.key)) ociVersions[row.key] = row.latest_version
      }
      const res = await applyJFrogProdChanges({
        branch: params.branch,
        // Either file can be the stale one: prod's nodeclass patches the base, so
        // tfvars can be current while the nodeclass is not. The backend skips a
        // file whose content already matches, so sending it is safe either way.
        new_ami: (params.ami.has_update || params.ami.has_update_nodeclass) && params.ami.latest_ami
          ? params.ami.latest_ami : '',
        new_ami_name: params.ami.has_update ? (params.ami.latest_ami_name || '') : '',
        helm_versions: helmVersions,
        oci_versions: ociVersions,
      })
      setResult(res)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to apply changes.'))
    } finally {
      setApplying(false)
    }
  }

  const totalUpdates = params
    ? (params.ami.has_update || params.ami.has_update_nodeclass ? 1 : 0) +
      params.helm_charts.filter(r => r.has_update && !skipped.has(r.key)).length +
      params.oci_repos.filter(r => r.has_update && !skipped.has(r.key)).length
    : 0

  const hasBreaking =
    params?.helm_charts.some(r => r.has_update && r.is_breaking) ||
    params?.oci_repos.some(r => r.has_update && r.is_breaking)

  return (
    <Modal open={open} onClose={handleClose} title="JFrog — Prod Maintenance" wide>
      {result ? (
        <div className="space-y-5 py-2">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">Changes committed!</p>
              <p className="text-sm text-green-700 mt-0.5">
                {result.committed_files.length} file{result.committed_files.length !== 1 ? 's' : ''} updated on{' '}
                <span className="font-mono">{params?.branch}</span>
              </p>
            </div>
          </div>
          <div className="bg-gray-50 rounded-lg p-3 space-y-1">
            {result.committed_files.map(f => (
              <p key={f} className="text-xs font-mono text-gray-600 truncate">{f}</p>
            ))}
          </div>
          <a
            href={result.branch_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            View branch on GitHub <ExternalLink size={13} />
          </a>

          {/* Post-merge next steps */}
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1.5">
            <p className="font-semibold">After merging the maintenance branch:</p>
            <ol className="list-decimal list-inside space-y-1 text-blue-700">
              <li><span className="font-mono bg-blue-100 px-1 rounded">git pull</span> the repo locally</li>
              <li>Run <span className="font-mono bg-blue-100 px-1 rounded">terraform apply</span> from <span className="font-mono">terraform/envs/jfrog/envs/prod/</span></li>
              <li><span className="font-mono bg-blue-100 px-1 rounded">cd</span> into <span className="font-mono">Kubernetes/envs/jfrog/envs/prod/</span> and run <span className="font-mono bg-blue-100 px-1 rounded">kubectl apply -k .</span></li>
            </ol>
            <a
              href="https://confluenceent.cms.gov/spaces/COM/pages/1384893085/Runbook+JFrog+Maintenance"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-600 hover:underline font-medium mt-1"
            >
              JFrog Maintenance Runbook <ExternalLink size={10} />
            </a>
          </div>

          <button onClick={handleClose} className="btn-secondary w-full">Close</button>
        </div>
      ) : (
        <div className="space-y-5">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm ds-u-color--muted">
              <Loader2 size={16} className="animate-spin" />
              Fetching current state and latest versions…
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {params && (
            <>
              {/* Branch status */}
              <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-2.5">
                <div className="flex items-center gap-2 text-sm">
                  <GitBranch size={14} className="ds-u-color--muted" />
                  <span className="font-mono text-gray-700">{params.branch}</span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    params.branch_created
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-green-100 text-green-700'
                  }`}>
                    {params.branch_created ? 'Created' : 'Found'}
                  </span>
                </div>
                <a
                  href={params.branch_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
                >
                  GitHub <ExternalLink size={11} />
                </a>
              </div>

              {/* AMI section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  AMI (EKS {params.ami.eks_version})
                </p>
                {params.ami.error ? (
                  <p className="text-xs text-red-600 flex items-center gap-1">
                    <AlertTriangle size={11} /> {params.ami.error}
                  </p>
                ) : (
                  <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
                    <table className="w-full">
                      <thead>
                        <tr className="bg-gray-50 text-xs ds-u-color--muted">
                          <th className="text-left px-3 py-2 font-medium">File</th>
                          <th className="text-left px-3 py-2 font-medium">Current</th>
                          <th className="text-left px-3 py-2 font-medium">Latest</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-t border-gray-100">
                          <td className="px-3 py-2 text-xs ds-u-color--muted font-mono">terraform.tfvars</td>
                          <td className="px-3 py-2 font-mono text-xs text-gray-700">{params.ami.current_ami || '—'}</td>
                          <td className="px-3 py-2">
                            {params.ami.has_update ? (
                              <span className="font-mono text-xs text-green-700 font-medium">{params.ami.latest_ami}</span>
                            ) : (
                              <span className="text-xs ds-u-color--muted">up to date</span>
                            )}
                          </td>
                        </tr>
                        <tr className="border-t border-gray-100">
                          <td className="px-3 py-2 text-xs ds-u-color--muted font-mono">karpenter-node-class.yaml</td>
                          <td className="px-3 py-2 font-mono text-xs text-gray-700">{params.ami.current_ami_nodeclass || '—'}</td>
                          <td className="px-3 py-2">
                            {!params.ami.current_ami_nodeclass ? (
                              <span className="text-xs ds-u-color--muted">not tracked</span>
                            ) : params.ami.has_update_nodeclass ? (
                              <span className="font-mono text-xs text-green-700 font-medium">{params.ami.latest_ami}</span>
                            ) : (
                              <span className="text-xs ds-u-color--muted">up to date</span>
                            )}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    {params.ami.latest_ami_name && (
                      <p className="px-3 py-1.5 text-xs ds-u-color--muted border-t border-gray-100 font-mono">
                        {params.ami.latest_ami_name}
                      </p>
                    )}
                  </div>
                )}

                {/* AMI release notes */}
                {params.ami.release_notes && (
                  <div className="mt-3">
                    <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-1.5">
                      Gold Image Release Notes
                      {params.ami.release_notes.date && (
                        <span className="ml-2 font-normal normal-case ds-u-color--muted">
                          {params.ami.release_notes.date}
                        </span>
                      )}
                    </p>
                    {params.ami.release_notes.available && params.ami.release_notes.notes?.length ? (
                      <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
                        <ul className="space-y-1">
                          {params.ami.release_notes.notes.map((note, i) => (
                            <li key={i} className="text-xs text-gray-600 flex gap-1.5">
                              <span className="text-gray-300 flex-shrink-0 mt-0.5">•</span>
                              <span>{note}</span>
                            </li>
                          ))}
                        </ul>
                        {params.ami.release_notes.source_url && (
                          <a
                            href={params.ami.release_notes.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline mt-2"
                          >
                            Full release notes <ExternalLink size={10} />
                          </a>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs ds-u-color--muted italic">
                        {params.ami.release_notes.error
                          ? `Release notes unavailable: ${params.ami.release_notes.error}`
                          : 'No release notes available for this AMI.'}
                        {params.ami.release_notes.source_url && (
                          <a
                            href={params.ami.release_notes.source_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-2 text-cms-blue hover:underline not-italic"
                          >
                            View page <ExternalLink size={10} className="inline" />
                          </a>
                        )}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* Helm charts section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  Helm Charts (HelmRelease) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.helm_charts}
                  expandedKey={expandedKey}
                  onToggle={toggleExpand}
                  skipped={skipped}
                  onToggleSkip={toggleSkip}
                />
              </div>

              {/* OCI repositories section */}
              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">
                  OCI Repositories (tag-based) — click a row to see release notes
                </p>
                <ChartTable
                  rows={params.oci_repos}
                  expandedKey={expandedKey}
                  onToggle={toggleExpand}
                  skipped={skipped}
                  onToggleSkip={toggleSkip}
                />
                <p className="text-xs ds-u-color--muted mt-1.5">
                  Karpenter and Karpenter CRD must always be updated to the same tag.
                </p>
              </div>

              {/* Breaking change warning */}
              {hasBreaking && (
                <div className="flex items-start gap-2 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2.5 text-xs text-orange-800">
                  <AlertTriangle size={13} className="flex-shrink-0 mt-0.5 text-orange-500" />
                  <span>
                    <strong>Review release notes before applying.</strong> One or more components have minor or major
                    version bumps — check for renamed values, schema migrations, or required manual steps.
                  </span>
                </div>
              )}

              {totalUpdates === 0 && (
                <div className="text-center py-4 text-sm ds-u-color--muted">
                  All components are already up to date.
                </div>
              )}

              {/* Post-merge steps reminder */}
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 text-xs text-blue-800 space-y-1.5">
                <p className="font-semibold">After merging the maintenance branch:</p>
                <ol className="list-decimal list-inside space-y-1 text-blue-700">
                  <li><span className="font-mono bg-blue-100 px-1 rounded">git pull</span> the repo locally</li>
                  <li>Run <span className="font-mono bg-blue-100 px-1 rounded">terraform apply</span> from <span className="font-mono">terraform/envs/jfrog/envs/prod/</span></li>
                  <li><span className="font-mono bg-blue-100 px-1 rounded">cd</span> into <span className="font-mono">Kubernetes/envs/jfrog/envs/prod/</span> and run <span className="font-mono bg-blue-100 px-1 rounded">kubectl apply -k .</span></li>
                </ol>
                <a
                  href="https://confluenceent.cms.gov/spaces/COM/pages/1384893085/Runbook+JFrog+Maintenance"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-blue-600 hover:underline font-medium mt-1"
                >
                  JFrog Maintenance Runbook <ExternalLink size={10} />
                </a>
              </div>

              {/* Prod confirmation checkbox */}
              <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-3 py-3">
                <input
                  type="checkbox"
                  id="jfrog-prod-confirm"
                  className="mt-0.5 flex-shrink-0 accent-red-600"
                  checked={prodConfirmed}
                  onChange={e => setProdConfirmed(e.target.checked)}
                />
                <label htmlFor="jfrog-prod-confirm" className="text-sm text-red-800 cursor-pointer">
                  I confirm this is the <strong>prod</strong> environment and I have reviewed all changes above.
                </label>
              </div>

              <p className="text-xs ds-u-color--muted">
                <span className="font-mono">main</span> is merged into the maintenance branch
                before anything is written, so a commit cannot land on a stale base.
              </p>

              <div className="flex gap-3">
                <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleApply}
                  disabled={applying || totalUpdates === 0 || !prodConfirmed}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {applying && <Loader2 size={15} className="animate-spin" />}
                  {applying ? 'Applying…' : `Apply ${totalUpdates} Update${totalUpdates !== 1 ? 's' : ''}`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}

// ─── Tool Maintenance Card ────────────────────────────────────────────────────

interface ToolCardProps {
  name: string
  description: string
  environment?: string
  onAction?: () => void
  comingSoon?: boolean
  blocked?: boolean
  blockedReason?: string
}

function ToolCard({
  name,
  description,
  environment,
  onAction,
  comingSoon = false,
  blocked = false,
  blockedReason,
}: ToolCardProps) {
  // The base-chart prerequisite is a sequencing rule, not a hard constraint: a
  // chart can be intentionally left behind, so the gate is overridable per card.
  const [override, setOverride] = useState(false)
  const gated = blocked && !override

  return (
    <div
      className={`theme-card theme-card--plain ${
        comingSoon ? 'opacity-60' : ''
      } ${gated ? 'border-amber-200 bg-amber-50/30' : 'border-gray-100'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-gray-800">{name}</p>
            {environment && (
              <Badge
                className={`ds-c-badge--xs ${
                  environment === 'prod'
                    ? 'ds-c-badge--prod'
                    : environment === 'dev'
                      ? 'ds-c-badge--dev'
                      : ''
                }`}
              >
                {environment}
              </Badge>
            )}
          </div>
          <p className="text-xs ds-u-color--muted mt-1">{description}</p>
        </div>
        {comingSoon && (
          <span className="flex-shrink-0 text-xs bg-gray-100 ds-u-color--muted px-2 py-0.5 rounded-full font-medium">
            Coming Soon
          </span>
        )}
      </div>
      {gated && (
        <div className="flex items-start gap-1.5 text-[11px] text-amber-800 bg-amber-100/70 rounded px-2 py-1.5">
          <AlertTriangle size={12} className="flex-shrink-0 mt-0.5 text-amber-600" />
          <span>
            {blockedReason}{' '}
            <button
              onClick={() => setOverride(true)}
              className="underline font-medium hover:text-amber-900"
            >
              Run anyway
            </button>
          </span>
        </div>
      )}
      <div className="mt-auto">
        <button
          onClick={onAction}
          disabled={comingSoon || gated}
          title={gated ? blockedReason : undefined}
          className="btn-maintenance"
        >
          Run Maintenance
        </button>
      </div>
    </div>
  )
}

// ─── Base-chart prerequisite banner ───────────────────────────────────────────

interface PrereqState {
  loading: boolean
  pending: number
  total: number
  branchExists: boolean
  error: string
}

function BaseChartsPrereq({
  state,
  onRecheck,
  onOpen,
}: {
  state: PrereqState
  onRecheck: () => void
  onOpen: () => void
}) {
  const { loading, pending, total, error } = state

  return (
    <Alert
      variation={loading ? undefined : error || pending > 0 ? 'warn' : 'success'}
      weight={loading ? 'lightweight' : undefined}
      className="maintenance-prereq-alert mb-4"
    >
      <div className="ds-c-alert__content flex w-full items-center justify-between gap-4 text-xs">
        <div>
          {loading && 'Checking the shared base charts…'}
          {!loading && error && (
            <>
              Could not check the shared base charts: {error}. Nothing is gated.
            </>
          )}
          {!loading && !error && pending > 0 && (
            <>
              <strong>{pending} of {total} shared base charts are behind.</strong> Run{' '}
              <button onClick={onOpen} className="underline font-medium hover:text-amber-950">
                Base Helm Charts
              </button>{' '}
              first: the JFrog and CloudBees clusters reconcile them, so those upgrades build
              on top. SonarQube is unaffected and stays open.
            </>
          )}
          {!loading && !error && pending === 0 && total > 0 && (
            <>All {total} shared base charts are up to date. The JFrog and CloudBees upgrades are clear to run.</>
          )}
        </div>
        <button
          onClick={onRecheck}
          disabled={loading}
          className="alert__action shrink-0 text-xs font-medium underline whitespace-nowrap disabled:opacity-50"
        >
          Re-check
        </button>
      </div>
    </Alert>
  )
}

// ─── Main Maintenance Page ────────────────────────────────────────────────────

type ModalKey = 'branch' | 'datadog' | 'xoceoc' | 'sonarqube' | 'sonarqube-prod' | 'jfrog-dev' | 'jfrog-prod' | 'cloudbees-dev' | 'cloudbees-prod' | 'base-charts' | 'eks-upgrade' | null

const BLOCKED_REASON = 'Shared base charts are behind. Bring them up first.'
// SonarQube is not gated: it deploys through its own Jenkins pipeline and does
// not reconcile kubernetes/base/releases.

export default function Maintenance() {
  const [openModal, setOpenModal] = useState<ModalKey>(null)
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)
  const [ddStatus, setDdStatus] = useState<'active' | 'scheduled' | null>(null)
  const [searchParams] = useSearchParams()
  const [prereq, setPrereq] = useState<PrereqState>({
    loading: true, pending: 0, total: 0, branchExists: false, error: '',
  })

  // Only gate on a definite answer: a failed check leaves the tool cards usable
  // rather than blocking the window on a GitHub or ArtifactHub hiccup.
  const toolsBlocked = !prereq.loading && !prereq.error && prereq.pending > 0

  function loadPrereq() {
    setPrereq(p => ({ ...p, loading: true, error: '' }))
    getBaseChartsParams()
      .then(d => setPrereq({
        loading: false,
        pending: d.helm_charts.filter(r => r.has_update).length,
        total: d.helm_charts.length,
        branchExists: d.branch_exists,
        error: '',
      }))
      .catch((err: any) => setPrereq({
        loading: false, pending: 0, total: 0, branchExists: false,
        error: apiErrorMessage(err, 'check failed'),
      }))
  }

  useEffect(() => {
    getActiveDatadogDowntime().then(r => setDdStatus(r.downtime?.status ?? null)).catch(() => {})
    loadPrereq()
  }, [])

  // Re-check only when the base-charts modal itself closes, since that is the
  // one action that can change the answer.
  const prevModal = useRef<ModalKey>(null)
  useEffect(() => {
    if (prevModal.current === 'base-charts' && openModal === null) loadPrereq()
    prevModal.current = openModal
  }, [openModal])

  useEffect(() => {
    const open = searchParams.get('open') as ModalKey
    if (open) setOpenModal(open)
  }, [searchParams])

  function refreshDdStatus() {
    getActiveDatadogDowntime().then(r => setDdStatus(r.downtime?.status ?? null)).catch(() => {})
  }

  function showToast(message: string, type: 'success' | 'error' = 'success') {
    setToast({ message, type })
    setTimeout(() => setToast(null), 5000)
  }

  return (
    <div className="space-y-8">
      {/* Actions section */}
      <section>
        <div className="mb-4">
          <h2 className="text-base font-semibold text-gray-800">Actions</h2>
          <p className="text-sm ds-u-color--muted mt-0.5">
            Automation shortcuts for common maintenance tasks
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
          <ActionCard
            icon={<GitBranch size={20} className="text-white" />}
            label="Cut Maintenance Branch"
            description="Create branch from main"
            color="bg-gray-700"
            onClick={() => setOpenModal('branch')}
          />
          <ActionCard
            icon={<Clock size={20} className="text-white" />}
            label={ddStatus === 'active' ? 'Downtime Active' : ddStatus === 'scheduled' ? 'Downtime Scheduled' : 'Create DD Downtime'}
            description={ddStatus === 'active' ? 'Monitors are silenced' : ddStatus === 'scheduled' ? 'Downtime is upcoming' : 'Silence Datadog monitors'}
            color={ddStatus === 'active' ? 'bg-green-500' : ddStatus === 'scheduled' ? 'bg-amber-500' : 'bg-purple-500'}
            onClick={() => setOpenModal('datadog')}
          />
          <ActionCard
            icon={<Bell size={20} className="text-white" />}
            label="Notify XOC / EOC"
            description="Send maintenance notification"
            color="bg-orange-500"
            onClick={() => setOpenModal('xoceoc')}
          />
        </div>
      </section>

      {/* Tool maintenance section */}
      <section>
        <div className="mb-4">
          <h2 className="text-base font-semibold text-gray-800">Tool Maintenance</h2>
          <p className="text-sm ds-u-color--muted mt-0.5">
            Run the shared platform layer first, then the per-tool jobs
          </p>
        </div>

        <div className="flex items-center gap-2 mb-3">
          <span className="inline-flex items-center justify-center h-5 px-2 rounded-full bg-gray-800 text-white text-[11px] font-semibold">
            Step 1
          </span>
          <h3 className="text-sm font-semibold text-gray-700">Shared platform</h3>
          <span className="text-xs ds-u-color--muted">runs before any tool upgrade</span>
        </div>
        <BaseChartsPrereq
          state={prereq}
          onRecheck={loadPrereq}
          onOpen={() => setOpenModal('base-charts')}
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          <ToolCard
            name="Base Helm Charts"
            description="Bump the shared kubernetes/base/releases charts that both the JFrog and CloudBees clusters pull. Run this first."
            environment="shared"
            onAction={() => setOpenModal('base-charts')}
          />
          <ToolCard
            name="EKS Control Plane"
            description="Pull the versions AWS offers, review release notes and deprecated APIs with pluto, then bump eks_version and realign the gold image."
            environment="shared"
            onAction={() => setOpenModal('eks-upgrade')}
          />
        </div>

        <div className="flex items-center gap-2 mt-8 mb-3">
          <span className="inline-flex items-center justify-center h-5 px-2 rounded-full bg-gray-800 text-white text-[11px] font-semibold">
            Step 2
          </span>
          <h3 className="text-sm font-semibold text-gray-700">Per-tool maintenance</h3>
          <span className="text-xs ds-u-color--muted">Jenkins pipelines and per-env manifests</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          <ToolCard
            name="SonarQube"
            description="Run upgrades, re-indexing, plugin updates, or config sync via Jenkins pipeline."
            environment="dev"
            onAction={() => setOpenModal('sonarqube')}
          />
          <ToolCard
            name="JFrog"
            description="Update node AMI, Karpenter nodeclass, and helm chart versions on the maintenance branch."
            environment="dev"
            onAction={() => setOpenModal('jfrog-dev')}
            blocked={toolsBlocked}
            blockedReason={BLOCKED_REASON}
          />
          <ToolCard
            name="CloudBees CI"
            description="Update chart version, image tag, and node AMIs for Commercial Dev and Gov Cloud Dev."
            environment="dev"
            onAction={() => setOpenModal('cloudbees-dev')}
            blocked={toolsBlocked}
            blockedReason={BLOCKED_REASON}
          />
          <ToolCard
            name="SonarQube"
            description="Run upgrades, re-indexing, plugin updates, or config sync via Jenkins pipeline."
            environment="prod"
            onAction={() => setOpenModal('sonarqube-prod')}
          />
          <ToolCard
            name="JFrog"
            description="Update node AMI, Karpenter nodeclass, and helm chart versions for prod."
            environment="prod"
            onAction={() => setOpenModal('jfrog-prod')}
            blocked={toolsBlocked}
            blockedReason={BLOCKED_REASON}
          />
          <ToolCard
            name="CloudBees CI"
            description="Update chart version, image tag, and node AMIs for Commercial Prod and Gov Cloud Prod."
            environment="prod"
            onAction={() => setOpenModal('cloudbees-prod')}
            blocked={toolsBlocked}
            blockedReason={BLOCKED_REASON}
          />
        </div>
      </section>

      {/* Modals */}
      <BranchModal
        open={openModal === 'branch'}
        onClose={() => setOpenModal(null)}
        onSuccess={(msg) => { setOpenModal(null); showToast(msg) }}
      />
      <DatadogModal
        open={openModal === 'datadog'}
        onClose={() => { setOpenModal(null); refreshDdStatus() }}
        onSuccess={(msg) => showToast(msg)}
      />
      <XocEocModal
        open={openModal === 'xoceoc'}
        onClose={() => setOpenModal(null)}
      />
      <SonarQubeModal
        open={openModal === 'sonarqube'}
        onClose={() => setOpenModal(null)}
        targetEnv="dev"
      />
      <SonarQubeModal
        open={openModal === 'sonarqube-prod'}
        onClose={() => setOpenModal(null)}
        targetEnv="prod"
      />
      <JFrogDevModal
        open={openModal === 'jfrog-dev'}
        onClose={() => setOpenModal(null)}
      />
      <JFrogProdModal
        open={openModal === 'jfrog-prod'}
        onClose={() => setOpenModal(null)}
      />
      <CloudBeesDevModal
        open={openModal === 'cloudbees-dev'}
        onClose={() => setOpenModal(null)}
      />
      <CloudBeesProdModal
        open={openModal === 'cloudbees-prod'}
        onClose={() => setOpenModal(null)}
      />
      <BaseChartsModal
        open={openModal === 'base-charts'}
        onClose={() => setOpenModal(null)}
      />
      <EksUpgradeModal
        open={openModal === 'eks-upgrade'}
        onClose={() => setOpenModal(null)}
      />

      {/* Toast notifications */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {/* Maintenance reference */}
      <section>
        <div className="theme-card theme-card--plain">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 bg-yellow-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <Wrench size={16} className="text-yellow-700" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800">Maintenance Runbooks</p>
              <p className="text-sm ds-u-color--muted mt-0.5">
                Refer to the Confluence runbooks for step-by-step maintenance procedures,
                rollback plans, and escalation paths.
              </p>
              <div className="flex flex-col items-start gap-1.5 mt-2">
                {[
                  { label: 'CloudBees Jenkins', href: 'https://confluenceent.cms.gov/spaces/COM/pages/1384884288/Runbook+CloudBees+Jenkins+Maintenance' },
                  { label: 'JFrog', href: 'https://confluenceent.cms.gov/spaces/COM/pages/1384893085/Runbook+JFrog+Maintenance' },
                  { label: 'SonarQube', href: 'https://confluenceent.cms.gov/spaces/COM/pages/1325592270/Runbook+SonarQube+Maintenance' },
                ].map((rb) => (
                  <a
                    key={rb.label}
                    href={rb.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 text-sm text-cms-blue hover:underline"
                  >
                    {rb.label} Maintenance Runbook
                    <ExternalLink size={12} />
                  </a>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
