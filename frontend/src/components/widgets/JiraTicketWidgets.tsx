import { useState, useEffect, FormEvent } from 'react'
import { Ticket, CheckCircle, ExternalLink, Lock, AlertTriangle, Loader2 } from 'lucide-react'
import Modal from '../ui/Modal'
import ActionCard from '../ui/ActionCard'
import { useAuth } from '../../App'
import { MAINT_START_TIME, MAINT_END_TIME, to12Hour } from '../../utils/maintenanceWindow'
import {
  getXocEocPreview,
  getMggdTasks,
  createITCTicket,
  createMGGDTicket,
  getCloudBeesDevParams,
  type User,
  type ITCTicketResult,
  type MGGDTicketResult, apiErrorMessage,
  getMaintPrepStatus, type MaintPrepStatus, previewNewsletter,
  getMaintenanceWindow, type MaintenanceWindow } from '../../api/client'

// ─── Defaults + helpers (moved from the Maintenance page) ─────────────────────

const DEFAULT_JFROG = `Update EKS Nodes AMIs.
Update EKS add-ons and supporting components
Update application version to the latest`

const DEFAULT_JENKINS = `Update EKS Nodes AMIs.
Update EKS add-ons and supporting components
Upgrade CB Jenkins CI APP version for OC & Manage controllers`

const DEFAULT_SONAR = `Upgrade the Node AMI to the latest AMI release from SecOps`

const SYSTEMS_IMPACTED = `aws-cms-oit-iusg-devops-services-prod (623510781344)
aws-cms-oit-iusg-draas-awswest32 (478919403635)
aws-cms-oit-iusg-gc-cbj-prod (020847197482)`

function buildITCDescription(jfrog: string, jenkins: string, sonar: string): string {
  const section = (label: string, tasks: string) => {
    const lines = tasks.trim().split('\n').filter(Boolean)
    if (!lines.length) return ''
    // Jira wiki markup: '*' = top bullet (the tool), '**' = sub-bullet (each task)
    return `\n * ${label}:\n` + lines.map(l => ` ** ${l.trim()}`).join('\n')
  }
  const systems = SYSTEMS_IMPACTED.trim().split('\n').map(l => ` ** ${l.trim()}`).join('\n')
  return (
    'The below describes the work Cloud DevOps will be performing:' +
    section('JFrog', jfrog) +
    section('CB Jenkins', jenkins) +
    section('SonarQube', sonar) +
    `\n\n * *Systems impacted:*\n${systems}`
  )
}

const MGGD_RUNBOOK_LINKS = `*Link to deployment runbooks:*
[JFrog Deployment Runbook|https://confluenceent.cms.gov/spaces/COM/pages/646577617/JFrog+Deployment+Runbook]
[EKS AMI Update|https://confluenceent.cms.gov/display/COC/EKS+AMI+Update]
[Update CBC CJOC and Managed Controllers to latest version|https://confluenceent.cms.gov/display/COC/Runbook%3A+Update+CBC+CJOC+and+Managed+Controllers+to+latest+version]

Link to smoke testing plan:
[JFrog Deployment Runbook|https://confluenceent.cms.gov/spaces/COM/pages/646577617/JFrog+Deployment+Runbook]
[EKS AMI Update|https://confluenceent.cms.gov/display/COC/EKS+AMI+Update]
[Update CBC CJOC and Managed Controllers to latest version|https://confluenceent.cms.gov/display/COC/Runbook%3A+Update+CBC+CJOC+and+Managed+Controllers+to+latest+version]

Link to rollback plan:
[JFrog Deployment Runbook|https://confluenceent.cms.gov/spaces/COM/pages/646577617/JFrog+Deployment+Runbook]
[EKS AMI Update|https://confluenceent.cms.gov/display/COC/EKS+AMI+Update]
[Update CBC CJOC and Managed Controllers to latest version|https://confluenceent.cms.gov/display/COC/Runbook%3A+Update+CBC+CJOC+and+Managed+Controllers+to+latest+version]`

function buildMGGDDescription(jfrog: string, jenkins: string, sonar: string): string {
  const section = (label: string, tasks: string) => {
    const lines = tasks.trim().split('\n').filter(Boolean)
    if (!lines.length) return ''
    return ` * ${label}:\n` + lines.map(l => ` ** ${l.trim()}`).join('\n') + '\n\n'
  }
  const systems = SYSTEMS_IMPACTED.trim().split('\n').map(l => ` ** ${l.trim()}`).join('\n')
  return (
    'The below describes the work Cloud DevOps will be performing:\n' +
    section('Jfrog', jfrog) +
    section('CB Jenkins', jenkins) +
    section('SonarQube', sonar) +
    ` * *Systems impacted:*\n${systems}\n\n` +
    MGGD_RUNBOOK_LINKS
  )
}

function toJiraIso(localDt: string): string {
  // datetime-local gives "YYYY-MM-DDTHH:MM" — append Eastern offset
  if (!localDt) return ''
  const offset = '-0400'  // Eastern Daylight Time; update to -0500 for EST
  return `${localDt}:00.000${offset}`
}

function toDisplayDate(isoDate: string): string {
  // "YYYY-MM-DD" → "MM-DD-YYYY"
  const [y, m, d] = isoDate.split('-')
  return `${m}-${d}-${y}`
}

// Go/No-Go review date = N calendar days before maintenance (10 per the
// maintenance timeline; was the Tuesday-before ~3-4 days).
function daysBefore(dateStr: string, n: number): string {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T12:00:00')
  d.setDate(d.getDate() - n)
  return d.toISOString().split('T')[0]
}

// Prep tickets are a prerequisite for ITC/MGGD. Fetch their status when a modal
// opens; the Create button is disabled until all three prep tickets exist.
function usePrepGate(open: boolean, enabled: boolean): MaintPrepStatus | null {
  const [prep, setPrep] = useState<MaintPrepStatus | null>(null)
  useEffect(() => {
    if (!open || !enabled) { setPrep(null); return }
    let alive = true
    getMaintPrepStatus().then(p => { if (alive) setPrep(p) }).catch(() => { if (alive) setPrep(null) })
    return () => { alive = false }
  }, [open, enabled])
  return prep
}

function PrepGateNote({ prep }: { prep: MaintPrepStatus | null }) {
  if (!prep) return null

  // Prep exists but states a different window than the one in play. Either the
  // window moved after the prep tickets were written, or the override is
  // wrong; this does not guess which, it just shows both dates.
  const mismatch = prep.date_mismatch ?? []
  if (prep.all_created) {
    if (mismatch.length === 0) return null
    const stated = prep.tools[mismatch[0]]?.window_date_str
    return (
      <div className="flex items-start gap-2 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-800">
        <AlertTriangle size={14} className="shrink-0 mt-0.5" />
        <span>
          Using the existing Maintenance Prep tickets. They state{' '}
          <strong>{stated}</strong> and this window is{' '}
          <strong>{prep.maint_date_str}</strong>. If the window moved after they
          were created, update their descriptions so the two agree.
        </span>
      </div>
    )
  }

  const missing = Object.entries(prep.tools).filter(([, v]) => !v).map(([k]) => k)
  const found = Object.entries(prep.tools).filter(([, v]) => !!v).map(([k]) => k)
  return (
    <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-800">
      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
      <span>
        Create the Maintenance Prep tickets first (Automation &rsaquo; Maintenance Prep).
        No ticket found for {prep.maint_date_str}: <strong>{missing.join(', ')}</strong>.
        {found.length > 0 && <> Found for {found.join(', ')}.</>}
      </span>
    </div>
  )
}

/** The maintenance date and window from the server, so the forms pre-fill the
 *  same values the tickets are created with. The third-Saturday math in the
 *  browser cannot see the admin override, so it is not used for this. */
function useMaintWindow(open: boolean) {
  const [win, setWin] = useState<MaintenanceWindow | null>(null)
  useEffect(() => {
    if (!open) return
    let alive = true
    getMaintenanceWindow()
      .then(w => { if (alive) setWin(w) })
      .catch(() => { /* fall back to the standard window below */ })
    return () => { alive = false }
  }, [open])
  return win
}

function fmtReadable(dateStr: string, time: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr + 'T12:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) + ` ${time} ET`
}

// ─── ITC Ticket Modal ─────────────────────────────────────────────────────────

function ITCTicketModal({ open, onClose, onSuccess, currentUser }: {
  open: boolean; onClose: () => void; onSuccess: (msg: string) => void; currentUser: User | null
}) {
  const isAuthorized = !!currentUser?.jira_authorized

  const [form, setForm] = useState({
    date: '',
    jfrog: DEFAULT_JFROG,
    jenkins: DEFAULT_JENKINS,
    sonar: DEFAULT_SONAR,
    confluenceUrl: '',
    mggdUrl: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ITCTicketResult | null>(null)

  const win = useMaintWindow(open)
  const startTime = win?.start_time ?? MAINT_START_TIME
  const endTime = win?.end_time ?? MAINT_END_TIME
  const startLabel = to12Hour(startTime)
  const endLabel = to12Hour(endTime)

  // Pre-fill the date once the window arrives, without clobbering an edit.
  useEffect(() => {
    if (win?.date) setForm(f => (f.date ? f : { ...f, date: win.date }))
  }, [win?.date])

  // Derived date values
  const startDtLocal = form.date ? `${form.date}T${startTime}` : ''
  const endDtLocal   = form.date ? `${form.date}T${endTime}` : ''
  const prep = usePrepGate(open, isAuthorized)
  const prepBlocked = !!prep && !prep.all_created

  // Auto-fill the "Link to Comms Request" field with the maintenance-week
  // newsletter page URL (dry-run resolve, never edits the page).
  useEffect(() => {
    if (!open || !isAuthorized || !form.date) return
    const d = new Date(form.date + 'T12:00:00')
    const mdy = `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`
    let alive = true
    previewNewsletter({ maint_date_mdy: mdy, start_dt: toJiraIso(startDtLocal), end_dt: toJiraIso(endDtLocal) })
      .then(res => { if (alive && res.url) setForm(f => (f.confluenceUrl ? f : { ...f, confluenceUrl: res.url })) })
      .catch(() => {})
    return () => { alive = false }
  }, [open, form.date])

  // Auto-fetch this month's MGGD ticket URL + parse task bullets when modal opens
  useEffect(() => {
    if (!open || !isAuthorized) return
    getXocEocPreview()
      .then(data => {
        if (!data.mggd?.url) return
        setForm(f => ({ ...f, mggdUrl: data.mggd!.url }))
        const key = data.mggd!.url.split('/').pop() || ''
        if (!key) return
        getMggdTasks(key)
          .then(tasks => {
            setForm(f => ({
              ...f,
              jfrog:   tasks.jfrog   || f.jfrog,
              jenkins: tasks.jenkins || f.jenkins,
              sonar:   tasks.sonar   || f.sonar,
            }))
          })
          .catch(() => {})
      })
      .catch(() => {})
  }, [open])

  function set(field: string, value: string) {
    setForm(f => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const description = buildITCDescription(form.jfrog, form.jenkins, form.sonar)
      const res = await createITCTicket({
        maintenance_date: toDisplayDate(form.date),
        description,
        start_dt: toJiraIso(startDtLocal),
        end_dt: toJiraIso(endDtLocal),
        confluence_url: form.confluenceUrl,
        mggd_url: form.mggdUrl,
      })
      setResult(res.ticket)
      onSuccess(`ITC ticket ${res.ticket.key} created!`)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to create ITC ticket.'))
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    setForm({ date: '', jfrog: DEFAULT_JFROG, jenkins: DEFAULT_JENKINS, sonar: DEFAULT_SONAR, confluenceUrl: '', mggdUrl: '' })
    setError('')
    setResult(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Create ITC Maintenance Ticket">
      {result ? (
        <div className="text-center space-y-4 py-4">
          <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle size={28} className="text-green-600" />
          </div>
          <div>
            <p className="font-semibold text-gray-900">Ticket Created!</p>
            <p className="text-sm ds-u-color--muted mt-1">{result.key} — cloned from {result.cloned_from}</p>
          </div>
          <a
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            Open {result.key} in Jira <ExternalLink size={13} />
          </a>
          <div className="pt-2">
            <button onClick={handleClose} className="btn-secondary w-full">Close</button>
          </div>
        </div>
      ) : !isAuthorized ? (
        <div className="text-center space-y-4 py-6">
          <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <Lock size={24} className="ds-u-color--muted" />
          </div>
          <div>
            <p className="font-semibold text-gray-800">Restricted Action</p>
            <p className="text-sm ds-u-color--muted mt-1">
              ITC ticket creation is restricted to Patrick Hendren.
            </p>
          </div>
          <button onClick={handleClose} className="btn-secondary">Close</button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          {/* Dates */}
          <div>
            <label className="label">Maintenance Date</label>
            <input type="date" className="input-field" value={form.date}
              onChange={e => set('date', e.target.value)} required />
          </div>
          {form.date && (
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2.5 text-xs text-gray-600 dark:text-gray-300 space-y-1">
              <div className="flex justify-between"><span className="font-medium">Start</span><span>{fmtReadable(form.date, startLabel)}</span></div>
              <div className="flex justify-between"><span className="font-medium">End</span><span>{fmtReadable(form.date, endLabel)}</span></div>
            </div>
          )}

          {/* Tool sections */}
          <div>
            <label className="label">JFrog Tasks</label>
            <textarea className="input-field min-h-[70px] resize-y font-mono text-xs"
              value={form.jfrog} onChange={e => set('jfrog', e.target.value)}
              placeholder="One task per line..." />
          </div>
          <div>
            <label className="label">CB Jenkins Tasks</label>
            <textarea className="input-field min-h-[70px] resize-y font-mono text-xs"
              value={form.jenkins} onChange={e => set('jenkins', e.target.value)}
              placeholder="One task per line..." />
          </div>
          <div>
            <label className="label">SonarQube Tasks</label>
            <textarea className="input-field min-h-[50px] resize-y font-mono text-xs"
              value={form.sonar} onChange={e => set('sonar', e.target.value)}
              placeholder="One task per line..." />
          </div>

          {/* Links */}
          <div>
            <label className="label">Confluence Change Advisory Page URL <span className="ds-u-color--muted font-normal">(optional)</span></label>
            <input className="input-field text-sm" value={form.confluenceUrl}
              onChange={e => set('confluenceUrl', e.target.value)}
              placeholder="https://confluenceent.cms.gov/spaces/COC/pages/..." />
          </div>
          <div>
            <label className="label">
              MGGD Ticket URL <span className="ds-u-color--muted font-normal">(auto-fetched — override if needed)</span>
            </label>
            {form.mggdUrl && (
              <a href={form.mggdUrl} target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-xs text-cms-blue hover:underline mb-1.5 break-all">
                <ExternalLink size={11} className="flex-shrink-0" />
                {form.mggdUrl}
              </a>
            )}
            <input className="input-field text-sm" value={form.mggdUrl}
              onChange={e => set('mggdUrl', e.target.value)}
              placeholder="https://jira.cms.gov/browse/MGGD-..." />
          </div>

          <PrepGateNote prep={prep} />
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" disabled={loading || prepBlocked} title={prepBlocked ? 'Create the Maintenance Prep tickets first' : ''} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {loading && <Loader2 size={15} className="animate-spin" />}
              Create ITC Ticket
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

// ─── MGGD Ticket Modal ────────────────────────────────────────────────────────

function MGGDTicketModal({ open, onClose, onSuccess, currentUser }: {
  open: boolean; onClose: () => void; onSuccess: (msg: string) => void; currentUser: User | null
}) {
  const isAuthorized = !!currentUser?.jira_authorized

  const [form, setForm] = useState({
    date: '',
    itcKey: '',
    jfrog: DEFAULT_JFROG,
    jenkins: DEFAULT_JENKINS,
    sonar: DEFAULT_SONAR,
    downtime: true,
    implRollbackPlan: true,
  })
  const [releaseNumber, setReleaseNumber] = useState('')
  const [loadingRelease, setLoadingRelease] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<MGGDTicketResult | null>(null)

  const win = useMaintWindow(open)
  const startTime = win?.start_time ?? MAINT_START_TIME
  const endTime = win?.end_time ?? MAINT_END_TIME
  const startLabel = to12Hour(startTime)
  const endLabel = to12Hour(endTime)

  useEffect(() => {
    if (win?.date) setForm(f => (f.date ? f : { ...f, date: win.date }))
  }, [win?.date])

  // Derived date values. The Go/No-Go comes from the server so an admin
  // override is honored; the local minus-10 is only the fallback, and it is
  // what put a review date in the past when a window was arranged late.
  const goNoGoDate = win?.go_nogo_date ?? daysBefore(form.date, 10)
  const goNoGoPast = win ? win.go_nogo_in_past : false
  const leadDays = win?.lead_days ?? null
  const shortLead = leadDays !== null && leadDays < (win?.go_nogo_lead_days ?? 10)
  const startDtLocal = form.date ? `${form.date}T${startTime}` : ''
  const endDtLocal   = form.date ? `${form.date}T${endTime}` : ''
  const prep = usePrepGate(open, isAuthorized)
  const prepBlocked = !!prep && !prep.all_created

  // Fetch latest CB tag when modal opens
  useEffect(() => {
    if (!open || !isAuthorized) return
    setLoadingRelease(true)
    getCloudBeesDevParams()
      .then(data => {
        const tag = data.chart.latest_tag
        if (tag) setReleaseNumber(`Cloudbees_${tag}`)
      })
      .catch(() => {})
      .finally(() => setLoadingRelease(false))
  }, [open])

  function set<K extends keyof typeof form>(field: K, value: typeof form[K]) {
    setForm(f => ({ ...f, [field]: value }))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const description = buildMGGDDescription(form.jfrog, form.jenkins, form.sonar)
      const res = await createMGGDTicket({
        maintenance_date: toDisplayDate(form.date),
        description,
        start_dt: toJiraIso(startDtLocal),
        end_dt: toJiraIso(endDtLocal),
        go_nogo_review_date: goNoGoDate,
        release_number: releaseNumber,
        downtime: form.downtime,
        impl_rollback_plan_attached: form.implRollbackPlan,
        itc_key: form.itcKey || undefined,
      })
      setResult(res.ticket)
      onSuccess(`MGGD ticket ${res.ticket.key} created!`)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to create MGGD ticket.'))
    } finally {
      setLoading(false)
    }
  }

  function handleClose() {
    setForm({
      date: '', itcKey: '',
      jfrog: DEFAULT_JFROG, jenkins: DEFAULT_JENKINS, sonar: DEFAULT_SONAR,
      downtime: true, implRollbackPlan: true,
    })
    setError('')
    setResult(null)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Create MGGD Ticket">
      {result ? (
        <div className="text-center space-y-4 py-4">
          <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle size={28} className="text-green-600" />
          </div>
          <div>
            <p className="font-semibold text-gray-900">Ticket Created!</p>
            <p className="text-sm ds-u-color--muted mt-1">{result.key}</p>
          </div>
          <a
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-cms-blue hover:underline font-medium"
          >
            Open {result.key} in Jira <ExternalLink size={13} />
          </a>
          <div className="pt-2">
            <button onClick={handleClose} className="btn-secondary w-full">Close</button>
          </div>
        </div>
      ) : !isAuthorized ? (
        <div className="text-center space-y-4 py-6">
          <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <Lock size={24} className="ds-u-color--muted" />
          </div>
          <div>
            <p className="font-semibold text-gray-800">Restricted Action</p>
            <p className="text-sm ds-u-color--muted mt-1">
              MGGD ticket creation is restricted to Patrick Hendren.
            </p>
          </div>
          <button onClick={handleClose} className="btn-secondary">Close</button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          {/* Maintenance date */}
          <div>
            <label className="label">Maintenance Date</label>
            <input type="date" className="input-field" value={form.date}
              onChange={e => set('date', e.target.value)} required />
          </div>

          {/* Auto-derived schedule — read-only */}
          {form.date && (
            <div className="bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2.5 text-xs text-gray-600 dark:text-gray-300 space-y-1">
              <div className="flex justify-between"><span className="font-medium">Go/No-Go</span><span>{fmtReadable(goNoGoDate, '')}</span></div>
              <div className="flex justify-between"><span className="font-medium">Start</span><span>{fmtReadable(form.date, startLabel)}</span></div>
              <div className="flex justify-between"><span className="font-medium">End</span><span>{fmtReadable(form.date, endLabel)}</span></div>
              <div className="flex justify-between"><span className="font-medium">Release</span>
                <span className="font-mono">{loadingRelease ? '…' : releaseNumber || '—'}</span>
              </div>
            </div>
          )}

          {/* ITC key */}
          <div>
            <label className="label">ITC Ticket # <span className="ds-u-color--muted font-normal">(optional, for IR Plan)</span></label>
            <input className="input-field font-mono text-sm" value={form.itcKey}
              onChange={e => set('itcKey', e.target.value)}
              placeholder="ITC-XXXX" />
          </div>

          {/* Tool sections */}
          <div>
            <label className="label">JFrog Tasks</label>
            <textarea className="input-field min-h-[70px] resize-y font-mono text-xs"
              value={form.jfrog} onChange={e => set('jfrog', e.target.value)}
              placeholder="One task per line..." />
          </div>
          <div>
            <label className="label">CB Jenkins Tasks</label>
            <textarea className="input-field min-h-[70px] resize-y font-mono text-xs"
              value={form.jenkins} onChange={e => set('jenkins', e.target.value)}
              placeholder="One task per line..." />
          </div>
          <div>
            <label className="label">SonarQube Tasks</label>
            <textarea className="input-field min-h-[50px] resize-y font-mono text-xs"
              value={form.sonar} onChange={e => set('sonar', e.target.value)}
              placeholder="One task per line..." />
          </div>

          {/* Options */}
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input type="checkbox" className="rounded" checked={form.downtime}
                onChange={e => set('downtime', e.target.checked)} />
              Application downtime
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input type="checkbox" className="rounded" checked={form.implRollbackPlan}
                onChange={e => set('implRollbackPlan', e.target.checked)} />
              Rollback plan attached
            </label>
          </div>

          <PrepGateNote prep={prep} />
          {(goNoGoPast || shortLead) && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-800">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                {goNoGoPast && (
                  <><strong>The Go/No-Go review date ({goNoGoDate}) has already passed.</strong>{' '}
                  Change Management rejects this. Set it explicitly on the Admin page before creating.{' '}</>
                )}
                {shortLead && (
                  <>This window is <strong>{leadDays} days out</strong> and the process wants{' '}
                  {win?.go_nogo_lead_days ?? 10}. Expect to supply an out-of-cycle justification.</>
                )}
              </span>
            </div>
          )}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button type="submit" disabled={loading || prepBlocked} title={prepBlocked ? 'Create the Maintenance Prep tickets first' : ''} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {loading && <Loader2 size={15} className="animate-spin" />}
              Create MGGD Ticket
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

// ─── Jira-tab widgets (ActionCard + modal, self-contained) ────────────────────

export function CreateItcWidget() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<Ticket size={20} className="text-white" />}
        label="Create ITC Ticket"
        description="Open maintenance ticket in Jira"
        color="bg-cms-blue"
        onClick={() => setOpen(true)}
      />
      <ITCTicketModal open={open} onClose={() => setOpen(false)} onSuccess={() => {}} currentUser={user} />
    </>
  )
}

export function CreateMggdWidget() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<Ticket size={20} className="text-white" />}
        label="Create MGGD Ticket"
        description="Open change request in Jira"
        color="bg-indigo-500"
        onClick={() => setOpen(true)}
      />
      <MGGDTicketModal open={open} onClose={() => setOpen(false)} onSuccess={() => {}} currentUser={user} />
    </>
  )
}
