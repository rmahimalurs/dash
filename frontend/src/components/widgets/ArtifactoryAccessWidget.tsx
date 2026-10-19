import { useState, FormEvent } from 'react'
import {
  ShieldCheck, Loader2, AlertTriangle, ChevronDown, Info, Search, CheckCircle2, XCircle,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getArtifactoryUserAccess, type ArtifactoryUserAccess, type ArtifactoryUserEnv, apiErrorMessage,
} from '../../api/client'

export default function ArtifactoryAccessWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<ShieldCheck size={20} className="text-white" />}
        label="Check User Access"
        description="Confirm a user's Artifactory access — groups, projects, and permissions"
        color="bg-sky-600"
        onClick={() => setOpen(true)}
      />
      <ArtifactoryAccessModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function fmtDate(iso?: string | null) {
  if (!iso) return 'never'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

function ArtifactoryAccessModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<ArtifactoryUserEnv>('prod')
  const [username, setUsername] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<ArtifactoryUserAccess | null>(null)
  const [error, setError] = useState('')

  function handleClose() {
    setEnv('prod'); setUsername(''); setSubmitting(false); setResult(null); setError(''); onClose()
  }

  async function lookup(value: string) {
    const v = value.trim()
    setError(''); setResult(null)
    if (!v) { setError('Enter an EUA.'); return }
    setSubmitting(true)
    try {
      setResult(await getArtifactoryUserAccess(env, v))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Access lookup failed.'))
    } finally {
      setSubmitting(false)
    }
  }
  function handleSubmit(e: FormEvent) { e.preventDefault(); lookup(username) }

  return (
    <Modal open={open} onClose={handleClose} title="Artifactory User Access">
      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="label">Environment</label>
          <div className="relative">
            <select className="input-field pr-8 appearance-none" value={env}
              onChange={e => { setEnv(e.target.value as ArtifactoryUserEnv); setResult(null) }}>
              <option value="prod">Prod (artifactory.cloud.cms.gov)</option>
              <option value="dev">Dev (artifactory-dev.cloud.cms.gov)</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div>
          <label className="label">Search by EUA (Artifactory login)</label>
          <div className="flex gap-2">
            <input type="text" className="input-field font-mono" value={username}
              onChange={e => { setUsername(e.target.value); setResult(null) }}
              placeholder="a06j" autoComplete="off" autoFocus required />
            <button type="submit" disabled={submitting || !username.trim()}
              className="btn-primary flex items-center justify-center gap-2 px-4 whitespace-nowrap">
              {submitting ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
              {submitting ? 'Checking…' : 'Check'}
            </button>
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2">
          <Info size={13} className="flex-shrink-0 mt-0.5" />
          <span>Read-only. Shows whether the user is provisioned plus their groups, project memberships (with role), and the permission targets that grant them access.</span>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <AlertTriangle size={14} className="flex-shrink-0" /> {error}
          </div>
        )}

        {result && <ResultView r={result} />}
      </form>
    </Modal>
  )
}

function Chips({ items, cls }: { items: string[]; cls: string }) {
  if (!items.length) return <span className="text-xs ds-u-color--muted">none</span>
  return (
    <div className="flex flex-wrap gap-1">
      {items.map(i => <span key={i} className={`text-[11px] px-1.5 py-0.5 rounded ${cls}`}>{i}</span>)}
    </div>
  )
}

function ResultView({ r }: { r: ArtifactoryUserAccess }) {
  if (r.configured === false) {
    return <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">{r.message}</div>
  }
  if (!r.found) {
    return (
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 flex items-start gap-3">
        <XCircle size={18} className="ds-u-color--muted flex-shrink-0 mt-0.5" />
        <p className="text-sm text-gray-700 dark:text-gray-300">{r.message}</p>
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-green-200 bg-green-50 dark:bg-green-900/20 p-3 flex items-start gap-2.5">
        <CheckCircle2 size={18} className="text-green-600 flex-shrink-0 mt-0.5" />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">
            {r.username}
            {r.admin && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">ADMIN</span>}
            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{r.realm}</span>
          </p>
          <p className="text-xs ds-u-color--muted mt-0.5">
            {r.email || 'no email'} · status {r.status || '?'} · last login {fmtDate(r.last_logged_in)}
          </p>
        </div>
      </div>

      <Section title={`Groups (${r.groups?.length ?? 0})`}>
        <Chips items={r.groups ?? []} cls="bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300" />
      </Section>

      <Section title={`Projects (${r.project_count ?? 0})`}>
        {(r.projects ?? []).length === 0
          ? <span className="text-xs ds-u-color--muted">No project memberships</span>
          : <ul className="space-y-1">
              {(r.projects ?? []).map(p => (
                <li key={p.project} className="text-xs flex items-center gap-2">
                  <span className="font-mono text-gray-700 dark:text-gray-300">{p.project}</span>
                  <Chips items={p.roles} cls="bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300" />
                </li>
              ))}
            </ul>}
      </Section>

      <Section title={`Permission targets (${r.permission_target_count ?? 0})`}>
        {(r.permission_targets ?? []).length === 0
          ? <span className="text-xs ds-u-color--muted">No permission targets</span>
          : <ul className="space-y-1.5">
              {(r.permission_targets ?? []).map(pt => (
                <li key={pt.name} className="text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-700 dark:text-gray-300">{pt.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 ds-u-color--muted">{pt.via}</span>
                    <Chips items={pt.permissions} cls="bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300" />
                  </div>
                  {pt.repositories.length > 0 &&
                    <p className="text-[10px] ds-u-color--muted mt-0.5 ml-0.5">repos: {pt.repositories.join(', ')}</p>}
                </li>
              ))}
            </ul>}
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide ds-u-color--muted font-semibold mb-1">{title}</p>
      {children}
    </div>
  )
}
