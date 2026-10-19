import { useState, useEffect, useCallback } from 'react'
import { ShieldCheck, Users, ScrollText, ChevronLeft, ChevronRight, RefreshCw, Wrench, Loader2, CalendarClock, Megaphone, CheckCircle } from 'lucide-react'
import { getAdminUsers, updateUserRole, getAuditLog, getMaintenanceModeAdmin, setMaintenanceMode, getSlackDirectory, uploadSlackDirectory, getMaintDateOverride, setMaintDateOverride, getReleaseAnnouncement, postReleaseAnnouncement, AdminUser, AuditEvent, ReleaseAnnouncement, apiErrorMessage } from '../api/client'

// ─── Tab types ─────────────────────────────────────────────────────────────────

type Tab = 'users' | 'audit'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function MaintenanceToggle() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMaintenanceModeAdmin()
      .then((s) => setEnabled(s.enabled))
      .catch(() => setError('Could not load maintenance status'))
  }, [])

  async function toggle() {
    if (enabled === null) return
    const next = !enabled
    if (next && !window.confirm('Turn ON maintenance mode? Non-admin users will see the Under Maintenance page.')) return
    setSaving(true)
    setError(null)
    try {
      const s = await setMaintenanceMode(next)
      setEnabled(s.enabled)
    } catch {
      setError('Failed to update maintenance mode')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`rounded-xl border p-4 mb-6 flex items-center justify-between ${enabled ? 'border-amber-300 bg-amber-50 dark:bg-amber-900/20' : 'border-gray-200 bg-white dark:bg-gray-800'}`}>
      <div className="flex items-center gap-3">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${enabled ? 'bg-amber-100 text-amber-600' : 'bg-gray-100 ds-u-color--muted'}`}>
          <Wrench size={18} />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Site Maintenance Mode</p>
          <p className="text-xs ds-u-color--muted">
            {enabled === null ? 'Loading…' : enabled ? 'ON — non-admins see the Under Maintenance page' : 'OFF — site is live for everyone'}
          </p>
          {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={saving || enabled === null}
        className={`min-w-[7rem] flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50
          ${enabled ? 'bg-gray-200 text-gray-800 hover:bg-gray-300' : 'bg-amber-500 text-white hover:bg-amber-600'}`}
      >
        {saving ? <Loader2 size={15} className="animate-spin" /> : null}
        {enabled ? 'Turn Off' : 'Turn On'}
      </button>
    </div>
  )
}

function ReleaseAnnouncementCard() {
  const [state, setState] = useState<ReleaseAnnouncement | null>(null)
  const [showPreview, setShowPreview] = useState(false)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  // A second copy has to be asked for twice. The startup post and a manual one
  // once put the same release in the channel four minutes apart.
  const [armedDuplicate, setArmedDuplicate] = useState(false)

  const load = useCallback(() => {
    getReleaseAnnouncement()
      .then(setState)
      .catch((e) => setError(apiErrorMessage(e, 'Could not read the release announcement')))
  }, [])

  useEffect(() => { load() }, [load])

  async function send(force: boolean) {
    setSending(true); setError(''); setResult('')
    try {
      const r = await postReleaseAnnouncement(force, armedDuplicate)
      if (r.duplicate_blocked) {
        setArmedDuplicate(true)
        setResult('')
        setError(`${r.reason} Click again to send it anyway.`)
        return
      }
      setArmedDuplicate(false)
      setResult(r.posted ? `Posted to #${state?.channel}` : `Not posted: ${r.reason}`)
      load()
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Could not post the announcement'))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white dark:bg-gray-800 p-4 mb-6">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gray-100 ds-u-color--muted flex items-center justify-center flex-shrink-0">
          <Megaphone size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Release Announcement</p>
          <p className="text-xs ds-u-color--muted">
            {state === null
              ? 'Loading…'
              : state.announced
                ? `${state.version} was announced in #${state.channel}${state.announced_by ? ` by ${state.announced_by}` : ''}. It goes out once per release, on the first start after a deploy.`
                : state.held
                  ? `${state.version} is held: it will not be announced on its own. Post it below when you want it to go out.`
                  : `${state.version} has not been announced yet. It goes out to #${state.channel} on the first start after a deploy.`}
          </p>
          {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
          {result && (
            <p className="text-xs text-green-700 mt-0.5 inline-flex items-center gap-1">
              <CheckCircle size={12} /> {result}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 mt-3">
            <button
              onClick={() => setShowPreview((v) => !v)}
              disabled={!state}
              className="text-sm px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 hover:bg-gray-50 disabled:opacity-50"
            >
              {showPreview ? 'Hide' : 'Preview'} the message
            </button>
            <button
              onClick={() => send(state?.announced === true)}
              disabled={sending || !state}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-cms-blue text-white font-medium hover:opacity-90 disabled:opacity-50"
            >
              {sending && <Loader2 size={13} className="animate-spin" />}
              {armedDuplicate ? 'Send a second copy' : state?.announced ? 'Post again' : 'Post now'}
            </button>
          </div>

          {showPreview && state && (
            <pre className="mt-3 text-xs whitespace-pre-wrap bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-3 ds-u-color--muted">
              {state.preview}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

function MaintDateOverrideCard() {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [date, setDate] = useState('')
  const [savedDate, setSavedDate] = useState<string | null>(null)
  // Blank means "leave at the standard window". Date and times override
  // independently, so a month that only moves its hours needs no date.
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [downtimeEnd, setDowntimeEnd] = useState('')
  const [goNoGo, setGoNoGo] = useState('')
  const [saved, setSaved] = useState<{ start?: string | null; end?: string | null; dd?: string | null; gng?: string | null }>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMaintDateOverride()
      .then((s) => {
        setEnabled(s.enabled); setSavedDate(s.date)
        if (s.date) setDate(s.date)
        if (s.start_time) setStartTime(s.start_time)
        if (s.end_time) setEndTime(s.end_time)
        if (s.downtime_end_time) setDowntimeEnd(s.downtime_end_time)
        if (s.go_nogo_date) setGoNoGo(s.go_nogo_date)
        setSaved({ start: s.start_time, end: s.end_time, dd: s.downtime_end_time, gng: s.go_nogo_date })
      })
      .catch(() => setError('Could not load the maintenance override'))
  }, [])

  const dirty = date !== (savedDate ?? '')
    || startTime !== (saved.start ?? '')
    || endTime !== (saved.end ?? '')
    || downtimeEnd !== (saved.dd ?? '')
    || goNoGo !== (saved.gng ?? '')

  async function save(nextEnabled: boolean) {
    if (nextEnabled && !date && !startTime && !endTime && !downtimeEnd && !goNoGo) {
      setError('Set a date, a time, a Go/No-Go date, or any combination.'); return
    }
    setSaving(true); setError(null)
    try {
      const s = await setMaintDateOverride(
        nextEnabled,
        nextEnabled ? (date || null) : null,
        nextEnabled
          ? { start_time: startTime || null, end_time: endTime || null,
              downtime_end_time: downtimeEnd || null, go_nogo_date: goNoGo || null }
          : { start_time: null, end_time: null, downtime_end_time: null, go_nogo_date: null },
      )
      setEnabled(s.enabled); setSavedDate(s.date)
      setSaved({ start: s.start_time, end: s.end_time, dd: s.downtime_end_time, gng: s.go_nogo_date })
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to update override'))
    } finally {
      setSaving(false)
    }
  }

  const windowSummary = () => {
    const parts: string[] = []
    if (savedDate) parts.push(fmtDate(savedDate))
    if (saved.start || saved.end) parts.push(`${saved.start ?? '09:00'} to ${saved.end ?? '13:00'} ET`)
    if (saved.dd) parts.push(`Datadog until ${saved.dd}`)
    if (saved.gng) parts.push(`Go/No-Go ${fmtDate(saved.gng)}`)
    return parts.join(', ')
  }

  const fmtDate = (iso: string) => {
    const [y, m, d] = iso.split('-').map(Number)
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })
  }

  return (
    <div className={`rounded-xl border p-4 mb-6 ${enabled ? 'border-indigo-300 bg-indigo-50 dark:bg-indigo-900/20' : 'border-gray-200 bg-white dark:bg-gray-800'}`}>
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${enabled ? 'bg-indigo-100 text-indigo-600' : 'bg-gray-100 ds-u-color--muted'}`}>
          <CalendarClock size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Maintenance Date and Window Override</p>
          <p className="text-xs ds-u-color--muted">
            {enabled === null
              ? 'Loading…'
              : enabled
                ? `ON. ${windowSummary()}. Used by the ITC, MGGD, prep and Datadog flows and stated in the reminder email.`
                : 'OFF. 3rd Saturday of each month, 9:00 AM to 1:00 PM ET, Datadog silenced until 2:00 PM.'}
          </p>
          {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mt-3">
            <label className="text-xs ds-u-color--muted">
              Date
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="mt-0.5 w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs ds-u-color--muted">
              Window start
              <input
                type="time"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                placeholder="09:00"
                className="mt-0.5 w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs ds-u-color--muted">
              Window end
              <input
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                placeholder="13:00"
                className="mt-0.5 w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs ds-u-color--muted">
              Go/No-Go review
              <input
                type="date"
                value={goNoGo}
                onChange={(e) => setGoNoGo(e.target.value)}
                className="mt-0.5 w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs ds-u-color--muted">
              Datadog silenced until
              <input
                type="time"
                value={downtimeEnd}
                onChange={(e) => setDowntimeEnd(e.target.value)}
                placeholder="14:00"
                className="mt-0.5 w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
          </div>
          <p className="text-[11px] ds-u-color--muted mt-1.5">
            Leave a field blank to keep the standard value for it. Go/No-Go defaults to
            10 days before the window, which lands in the past when a window is arranged
            late; set it explicitly then.
          </p>

          <div className="flex items-center gap-2 mt-3 flex-wrap">
            {enabled ? (
              <>
                <button
                  onClick={() => save(true)}
                  disabled={saving || !dirty}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {saving && <Loader2 size={14} className="animate-spin" />} Update override
                </button>
                <button
                  onClick={() => save(false)}
                  disabled={saving}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium bg-gray-200 text-gray-800 hover:bg-gray-300 disabled:opacity-50"
                >
                  Turn Off
                </button>
              </>
            ) : (
              <button
                onClick={() => save(true)}
                disabled={saving || enabled === null || (!date && !startTime && !endTime && !downtimeEnd)}
                className="px-4 py-1.5 rounded-lg text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1.5"
              >
                {saving && <Loader2 size={14} className="animate-spin" />} Turn On
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Slim the raw slack-cli users cache in the browser to {email: {handle,id,name}}
// BEFORE upload — the raw cache is ~60 MB and would exceed the 50 MB ingress body
// limit; the slim map is ~1-2 MB. Already-slim maps pass through unchanged.
function slimSlackCache(raw: any): Record<string, { handle: string; id: string; name: string }> {
  if (raw && !Array.isArray(raw) && !raw.payload && !raw.members) {
    const vals = Object.values(raw)
    if (vals.length && vals.every((v: any) => v && typeof v === 'object' && ('handle' in v || 'id' in v))) {
      return raw
    }
  }
  const members: any[] = Array.isArray(raw) ? raw : (raw.payload || raw.members || [])
  const out: Record<string, { handle: string; id: string; name: string }> = {}
  for (const m of members) {
    if (!m || m.deleted) continue
    const email = (m.profile?.email || '').trim().toLowerCase()
    if (!email) continue
    out[email] = {
      handle: m.name || '',
      id: m.id || '',
      name: m.profile?.real_name || m.profile?.display_name || m.name || '',
    }
  }
  return out
}

function SlackDirectoryUpload() {
  const [meta, setMeta] = useState<{ staged: boolean; count: number; fetched_at: string | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { getSlackDirectory().then(setMeta).catch(() => setError('Could not load status')) }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-selecting the same file
    if (!file) return
    setBusy(true); setError(null); setMsg(null)
    try {
      const slim = slimSlackCache(JSON.parse(await file.text()))
      if (Object.keys(slim).length === 0) {
        setError('No members with an email found — is this the slack-cli users cache JSON?')
        return
      }
      const r = await uploadSlackDirectory(slim)  // small payload, well under the ingress limit
      setMsg(`Staged ${r.count} entries`)
      setMeta({ staged: true, count: r.count, fetched_at: r.fetched_at })
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Upload failed (is this the slack-cli users cache JSON?)'))
    } finally { setBusy(false) }
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white dark:bg-gray-800 p-4 mb-6 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-gray-100 ds-u-color--muted flex items-center justify-center flex-shrink-0">
          <Users size={18} />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">Slack Directory (email → handle)</p>
          <p className="text-xs ds-u-color--muted">
            {meta?.staged ? `${meta.count} entries staged` : 'Not staged'} — used to resolve ADO emails for PVC cleanup.
            Upload <code>~/.slack-cli/cache/cmsgov-users.json</code>.
          </p>
          {msg && <p className="text-xs text-green-600 mt-0.5">{msg}</p>}
          {error && <p className="text-xs text-red-600 mt-0.5">{error}</p>}
        </div>
      </div>
      <label className="min-w-[7rem] flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-cms-blue text-white hover:opacity-90 cursor-pointer">
        {busy ? <Loader2 size={15} className="animate-spin" /> : null}
        Upload
        <input type="file" accept="application/json,.json" className="hidden" onChange={onFile} disabled={busy} />
      </label>
    </div>
  )
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      timeZoneName: 'short',
    })
  } catch {
    return ts
  }
}

function formatEventType(event: string): string {
  const labels: Record<string, string> = {
    'auth.login': 'Login',
    'auth.logout': 'Logout',
    'maintenance.itc_ticket': 'ITC Ticket Created',
    'maintenance.mggd_ticket': 'MGGD Ticket Created',
    'maintenance.sonarqube_deploy': 'SonarQube Deploy',
    'maintenance.datadog_downtime_create': 'Datadog Downtime Created',
    'maintenance.datadog_downtime_cancel': 'Datadog Downtime Cancelled',
    'maintenance.jfrog_dev_apply': 'JFrog Dev Apply',
    'maintenance.branch_cut': 'Branch Cut',
    'admin.role_change': 'Role Changed',
  }
  return labels[event] || event
}

function eventBadgeClass(event: string): string {
  if (event.startsWith('auth.')) return 'bg-blue-100 text-blue-800'
  if (event.startsWith('maintenance.')) return 'bg-amber-100 text-amber-800'
  if (event.startsWith('admin.')) return 'bg-purple-100 text-purple-800'
  return 'bg-gray-100 text-gray-700'
}

function formatDetails(details: Record<string, unknown>): string {
  if (!details || Object.keys(details).length === 0) return ''
  return Object.entries(details)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => {
      if (Array.isArray(v)) return `${k}: [${(v as string[]).join(', ')}]`
      return `${k}: ${v}`
    })
    .join(' | ')
}

// ─── Users Tab ────────────────────────────────────────────────────────────────

function UsersTab() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [updating, setUpdating] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setUsers(await getAdminUsers())
    } catch {
      setError('Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleRoleChange(username: string, newRole: 'admin' | 'user') {
    setUpdating(username)
    setNotice(null)
    try {
      const res = await updateUserRole(username, newRole)
      setUsers((prev) =>
        prev.map((u) => (u.username === username ? { ...u, role: newRole } : u))
      )
      // The promotion stands either way, so a failed notice is surfaced rather
      // than treated as an error.
      if (newRole === 'admin') {
        setNotice(
          res.notified
            ? `${username} was promoted and emailed.`
            : `${username} was promoted, but the email could not be sent${
                res.notify_error ? `: ${res.notify_error}` : '.'
              }`,
        )
      }
    } catch {
      setError(`Failed to update role for ${username}`)
    } finally {
      setUpdating(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 ds-u-color--muted">
        <RefreshCw size={18} className="animate-spin mr-2" /> Loading users...
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm">
        {error}
        <button onClick={load} className="ml-3 underline">Retry</button>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm ds-u-color--muted">{users.length} registered user{users.length !== 1 ? 's' : ''}</p>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-sm ds-u-color--muted hover:text-gray-800 transition-colors"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {notice && (
        <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-xs text-blue-900">
          <span>{notice}</span>
          <button onClick={() => setNotice(null)} className="underline whitespace-nowrap">
            Dismiss
          </button>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Username</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Display Name</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Email</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Role</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map((u) => (
              <tr key={u.username} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-mono text-xs text-gray-700">{u.username}</td>
                <td className="px-4 py-3 text-gray-900">{u.display_name}</td>
                <td className="px-4 py-3 ds-u-color--muted">{u.email}</td>
                <td className="px-4 py-3">
                  <select
                    value={u.role}
                    disabled={updating === u.username}
                    onChange={(e) => handleRoleChange(u.username, e.target.value as 'admin' | 'user')}
                    className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white
                      focus:outline-none focus:ring-2 focus:ring-cms-blue focus:border-transparent
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center ds-u-color--muted">
                  No users registered yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs ds-u-color--muted">
        Role changes take effect immediately. Users already logged in will see the change on their next page load.
      </p>
    </div>
  )
}

// ─── Audit Log Tab ────────────────────────────────────────────────────────────

const EVENT_TYPES = [
  { value: '', label: 'All events' },
  { value: 'auth', label: 'Auth (login/logout)' },
  { value: 'maintenance', label: 'Maintenance actions' },
  { value: 'admin', label: 'Admin actions' },
]

function AuditLogTab() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [filterUsername, setFilterUsername] = useState('')
  const [filterEventType, setFilterEventType] = useState('')
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')

  const PAGE_SIZE = 50

  const load = useCallback(async (currentPage: number) => {
    setLoading(true)
    setError(null)
    try {
      const result = await getAuditLog({
        page: currentPage,
        page_size: PAGE_SIZE,
        username: filterUsername || undefined,
        event_type: filterEventType || undefined,
        date_from: filterDateFrom || undefined,
        date_to: filterDateTo || undefined,
      })
      setEvents(result.events)
      setTotal(result.total)
    } catch {
      setError('Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }, [filterUsername, filterEventType, filterDateFrom, filterDateTo])

  useEffect(() => {
    setPage(1)
    load(1)
  }, [filterUsername, filterEventType, filterDateFrom, filterDateTo]) // eslint-disable-line react-hooks/exhaustive-deps

  function handlePageChange(newPage: number) {
    setPage(newPage)
    load(newPage)
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <input
          type="text"
          placeholder="Filter by username"
          value={filterUsername}
          onChange={(e) => setFilterUsername(e.target.value)}
          className="input text-sm w-44"
        />
        <select
          value={filterEventType}
          onChange={(e) => setFilterEventType(e.target.value)}
          className="input text-sm w-52"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <div className="flex items-center gap-2">
          <label className="text-sm ds-u-color--muted">From</label>
          <input
            type="date"
            value={filterDateFrom}
            onChange={(e) => setFilterDateFrom(e.target.value)}
            className="input text-sm w-38"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm ds-u-color--muted">To</label>
          <input
            type="date"
            value={filterDateTo}
            onChange={(e) => setFilterDateTo(e.target.value)}
            className="input text-sm w-38"
          />
        </div>
        <button
          onClick={() => { setFilterUsername(''); setFilterEventType(''); setFilterDateFrom(''); setFilterDateTo('') }}
          className="text-sm ds-u-color--muted hover:text-gray-700 transition-colors"
        >
          Clear
        </button>
        <button
          onClick={() => load(page)}
          className="flex items-center gap-1.5 text-sm ds-u-color--muted hover:text-gray-800 transition-colors ml-auto"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-red-700 text-sm mb-4">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 font-semibold text-gray-600 whitespace-nowrap">Timestamp</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">User</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Event</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">Details</th>
              <th className="text-left px-4 py-3 font-semibold text-gray-600">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center ds-u-color--muted">
                  <RefreshCw size={16} className="animate-spin inline mr-2" />Loading...
                </td>
              </tr>
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center ds-u-color--muted">No events found</td>
              </tr>
            ) : events.map((e, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-4 py-2.5 text-xs ds-u-color--muted whitespace-nowrap font-mono">
                  {formatTimestamp(e.timestamp)}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{e.username}</td>
                <td className="px-4 py-2.5">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${eventBadgeClass(e.event)}`}>
                    {formatEventType(e.event)}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs ds-u-color--muted max-w-xs truncate" title={formatDetails(e.details)}>
                  {formatDetails(e.details)}
                </td>
                <td className="px-4 py-2.5 text-xs ds-u-color--muted font-mono">{e.ip || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-3">
        <p className="text-xs ds-u-color--muted">
          {total === 0 ? 'No results' : `${((page - 1) * PAGE_SIZE) + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total}`}
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handlePageChange(page - 1)}
            disabled={page <= 1 || loading}
            className="p-1.5 rounded-md border border-gray-200 ds-u-color--muted hover:bg-gray-50
              disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="text-xs ds-u-color--muted">Page {page} of {totalPages}</span>
          <button
            onClick={() => handlePageChange(page + 1)}
            disabled={page >= totalPages || loading}
            className="p-1.5 rounded-md border border-gray-200 ds-u-color--muted hover:bg-gray-50
              disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Admin Page ───────────────────────────────────────────────────────────────

export default function Admin() {
  const [activeTab, setActiveTab] = useState<Tab>('users')

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'users', label: 'Users', icon: <Users size={15} /> },
    { key: 'audit', label: 'Audit Log', icon: <ScrollText size={15} /> },
  ]

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-9 h-9 rounded-lg bg-purple-100 flex items-center justify-center flex-shrink-0">
          <ShieldCheck size={18} className="text-purple-600" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Admin</h1>
          <p className="text-sm ds-u-color--muted">Manage user roles and review activity</p>
        </div>
      </div>

      {/* Site maintenance mode */}
      <MaintenanceToggle />

      {/* Maintenance date override */}
      <MaintDateOverrideCard />

      {/* Slack directory staging (for PVC cleanup ADO resolution) */}
      <SlackDirectoryUpload />

      {/* Release announcement to the team channel */}
      <ReleaseAnnouncementCard />

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors
                ${activeTab === tab.key
                  ? 'border-cms-blue text-cms-blue'
                  : 'border-transparent ds-u-color--muted hover:text-gray-800 hover:border-gray-300'
                }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'users' && <UsersTab />}
      {activeTab === 'audit' && <AuditLogTab />}
    </div>
  )
}
