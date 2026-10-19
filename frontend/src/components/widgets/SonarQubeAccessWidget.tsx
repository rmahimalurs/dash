import { useState, FormEvent } from 'react'
import {
  ShieldCheck, Loader2, AlertTriangle, ChevronDown, Info, Search,
  CheckCircle2, XCircle, UserCheck, MailWarning,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getSonarQubeUserAccess, type SonarQubeUserAccess, type SonarQubeAppAccess, apiErrorMessage,
} from '../../api/client'

export default function SonarQubeAccessWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<ShieldCheck size={20} className="text-white" />}
        label="Check User Access"
        description="Confirm a user's SonarQube access and their project permissions"
        color="bg-sky-600"
        onClick={() => setOpen(true)}
      />
      <SonarQubeAccessModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function roleBadge(role: SonarQubeAppAccess['role']) {
  const map: Record<string, string> = {
    admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
    user: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    member: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  }
  return map[role] || map.member
}

function fmtDate(iso?: string | null) {
  if (!iso) return 'never'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

function SonarQubeAccessModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<'dev' | 'prod'>('prod')
  const [username, setUsername] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<SonarQubeUserAccess | null>(null)
  const [error, setError] = useState('')

  function handleClose() {
    setEnv('prod'); setUsername(''); setSubmitting(false); setResult(null); setError('')
    onClose()
  }

  async function lookup(value: string) {
    const v = value.trim()
    setError(''); setResult(null)
    if (!v) { setError('Enter a username.'); return }
    setSubmitting(true)
    try {
      setResult(await getSonarQubeUserAccess(env, v))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Access lookup failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(e: FormEvent) { e.preventDefault(); lookup(username) }
  function pickCandidate(login: string) { setUsername(login); lookup(login) }

  return (
    <Modal open={open} onClose={handleClose} title="SonarQube User Access">
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="label">Environment</label>
          <div className="relative">
            <select
              className="input-field pr-8 appearance-none"
              value={env}
              onChange={e => { setEnv(e.target.value as 'dev' | 'prod'); setResult(null) }}
            >
              <option value="prod">Prod (sonarqube.cloud.cms.gov)</option>
              <option value="dev">Dev (sonarqube-dev.cloud.cms.gov)</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div>
          <label className="label">Search by EUA, login, name, or email</label>
          <div className="flex gap-2">
            <input
              type="text"
              className="input-field font-mono"
              value={username}
              onChange={e => { setUsername(e.target.value); setResult(null) }}
              placeholder="sbs2  /  srikanth-rao-sharikar82151"
              autoComplete="off"
              autoFocus
              required
            />
            <button
              type="submit"
              disabled={submitting || !username.trim()}
              className="btn-primary flex items-center justify-center gap-2 px-4 whitespace-nowrap"
            >
              {submitting ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
              {submitting ? 'Checking…' : 'Check'}
            </button>
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2">
          <Info size={13} className="flex-shrink-0 mt-0.5" />
          <span>
            Read-only. Project access at CMS is granted by group
            (<code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">&lt;app&gt;-users</code> /
            <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">&lt;app&gt;-administrators</code>),
            so this lists the applications the user can reach and their role in each.
          </span>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <AlertTriangle size={14} className="flex-shrink-0" />
            {error}
          </div>
        )}

        {result && <ResultView r={result} onPick={pickCandidate} />}
      </form>
    </Modal>
  )
}

function EmailCollisionBanner({ title, detail, accounts }: {
  title: string; detail: React.ReactNode; accounts: SonarQubeUserAccess['email_shared_with']
}) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 text-sm dark:bg-red-900/20 dark:border-red-700">
      <div className="flex items-start gap-2 text-red-800 dark:text-red-300">
        <MailWarning size={16} className="flex-shrink-0 mt-0.5" />
        <div>
          <p className="font-semibold">{title}</p>
          <p className="text-xs mt-0.5">{detail}</p>
        </div>
      </div>
      {accounts && accounts.length > 0 && (
        <div className="mt-2 rounded-md border border-red-200 dark:border-red-700/60 divide-y divide-red-100 dark:divide-red-800/60 bg-white/60 dark:bg-black/10">
          {accounts.map(c => (
            <div key={c.login} className="flex items-center justify-between px-2.5 py-1.5 text-xs">
              <span className="text-gray-700 dark:text-gray-300">
                <code className="bg-red-100 dark:bg-red-800/40 px-1 rounded">{c.login}</code>
                {c.name && <span className="ds-u-color--muted"> · {c.name}</span>}
                {c.eua && <span className="ds-u-color--muted"> · EUA {c.eua}</span>}
              </span>
              {!c.active && <span className="text-[10px] uppercase ds-u-color--muted">inactive</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ResultView({ r, onPick }: { r: SonarQubeUserAccess; onPick: (login: string) => void }) {
  if (r.configured === false) {
    return (
      <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2.5 text-sm dark:bg-amber-900/20 dark:border-amber-700 dark:text-amber-300">
        <AlertTriangle size={15} className="flex-shrink-0 mt-0.5" />
        {r.message}
      </div>
    )
  }

  if (r.ambiguous && r.candidates && r.candidates.length > 0) {
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2.5 text-sm dark:bg-amber-900/20 dark:border-amber-700 dark:text-amber-300">
          <Info size={15} className="flex-shrink-0 mt-0.5" />
          <div>{r.candidates.length} matching user(s) — select one:</div>
        </div>
        <div className="rounded-lg border border-gray-100 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700 max-h-64 overflow-y-auto">
          {r.candidates.map(c => (
            <button
              type="button"
              key={c.login}
              onClick={() => onPick(c.login!)}
              className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{c.name || c.login}</p>
                <p className="text-xs ds-u-color--muted truncate">
                  <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{c.login}</code>
                  {c.eua && <> · EUA <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{c.eua}</code></>}
                  {c.email && <> · {c.email}</>}
                </p>
              </div>
              {!c.active && <span className="text-[10px] font-semibold uppercase ds-u-color--muted bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded flex-shrink-0">inactive</span>}
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (r.found === false) {
    if (r.email_collision) {
      const c = r.email_collision
      return (
        <EmailCollisionBanner
          title="Login blocked by an email collision"
          detail={<>
            {c.ad_name || r.login} is not provisioned in SonarQube, but their AD email{' '}
            <code className="bg-red-100 dark:bg-red-800/40 px-1 rounded">{c.ad_email}</code> is already used by the
            account(s) below. SonarQube requires unique emails, so their LDAP login is rejected. Free the email on
            that account (change or clear it) to let them sign in.
          </>}
          accounts={c.conflicting}
        />
      )
    }
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2.5 text-sm dark:bg-amber-900/20 dark:border-amber-700 dark:text-amber-300">
          <XCircle size={15} className="flex-shrink-0 mt-0.5" />
          <div>
            No SonarQube user matching <code className="bg-amber-100 dark:bg-amber-800/40 px-1 rounded">{r.login}</code> found
            in <span className="font-medium">{r.env}</span> (searched login, EUA, name, and email). They likely have not signed in / been provisioned.
          </div>
        </div>
      </div>
    )
  }

  const apps = r.applications || []
  const shared = r.email_shared_with || []
  return (
    <div className="space-y-4 border-t border-gray-100 dark:border-gray-700 pt-4">
      {shared.length > 0 && (
        <EmailCollisionBanner
          title={`Email shared with ${shared.length} other account${shared.length > 1 ? 's' : ''}`}
          detail={<>
            <code className="bg-red-100 dark:bg-red-800/40 px-1 rounded">{r.email}</code> is used by more than one
            SonarQube account. Shared emails break LDAP auto-provisioning and can block one of these users from
            logging in — give each account a unique email.
          </>}
          accounts={shared}
        />
      )}

      {/* Identity + status */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <UserCheck size={16} className="text-sky-600" />
            {r.name || r.login}
            <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded text-xs font-normal">{r.login}</code>
          </p>
          {r.email && <p className="text-xs ds-u-color--muted mt-0.5 ml-6">{r.email}</p>}
        </div>
        <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full ${r.active
          ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
          : 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300'}`}>
          {r.active ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
          {r.active ? 'Active' : 'Inactive'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <div><span className="ds-u-color--muted">EUA</span><div className="font-medium text-gray-700 dark:text-gray-300 font-mono">{r.eua || '—'}</div></div>
        <div><span className="ds-u-color--muted">Auth source</span><div className="font-medium text-gray-700 dark:text-gray-300">{r.local ? 'Local account' : (r.external_provider || 'unknown')}</div></div>
        <div><span className="ds-u-color--muted">Last sign-in</span><div className="font-medium text-gray-700 dark:text-gray-300">{fmtDate(r.last_connection)}</div></div>
        <div><span className="ds-u-color--muted">Applications</span><div className="font-medium text-gray-700 dark:text-gray-300">{r.application_count ?? apps.length}{r.admin_count ? ` (${r.admin_count} admin)` : ''}</div></div>
        <div><span className="ds-u-color--muted">Groups</span><div className="font-medium text-gray-700 dark:text-gray-300">{r.groups?.length ?? 0}</div></div>
      </div>

      {/* Application access */}
      <div>
        <p className="label mb-1.5">Application project access</p>
        {apps.length === 0 ? (
          <p className="text-sm ds-u-color--muted bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-2">
            Baseline access only (<code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">sonar-users</code>) — no application projects.
          </p>
        ) : (
          <div className="max-h-52 overflow-y-auto rounded-lg border border-gray-100 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
            {apps.map(a => (
              <div key={a.application} className="flex items-center justify-between px-3 py-1.5">
                <code className="text-xs text-gray-700 dark:text-gray-300">{a.application}</code>
                <span className={`text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${roleBadge(a.role)}`}>
                  {a.role}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
