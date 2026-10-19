import { useState } from 'react'
import { AlertTriangle, CheckCircle, FolderGit2, Loader2, Plus, Send, Trash2, Upload, Wand2, XCircle } from 'lucide-react'
import {
  apiErrorMessage,
  createRepos,
  getRepoCreateEligibility,
  type RepoCreateJobExtra,
  type RepoCreateResult,
  type RepoCreateSpec,
} from '../../api/client'
import { useGithubEligibility } from '../../hooks/useGithubEligibility'
import { useBulkJob } from '../../hooks/useBulkJob'
import { splitCsvRow } from '../../utils/parseList'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import JobProgress from '../ui/JobProgress'

interface Row {
  id: number
  name: string
  requestor: string
  extraAdmins: string
  ticketKey: string
}

let nextId = 1
function emptyRow(): Row {
  return { id: nextId++, name: '', requestor: '', extraAdmins: '', ticketKey: '' }
}

const _NAME_COLUMNS = new Set(['name', 'repo', 'repo_name', 'repository'])
const _REQUESTOR_COLUMNS = new Set(['requestor', 'handle', 'github_handle', 'username'])
const _EXTRA_COLUMNS = new Set(['extra_admins', 'extraadmins', 'admins'])
const _TICKET_COLUMNS = new Set(['ticket_key', 'ticket', 'ticketkey', 'cldspt'])

function parseRepoCsv(text: string): { name: string; requestor: string; extraAdmins: string; ticketKey: string }[] {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(splitCsvRow)
  if (lines.length === 0) return []
  const header = lines[0].map(h => h.trim().toLowerCase().replace(/[\s_]+/g, '_'))
  const nameIdx = header.findIndex(h => _NAME_COLUMNS.has(h))
  const reqIdx = header.findIndex(h => _REQUESTOR_COLUMNS.has(h))
  const extraIdx = header.findIndex(h => _EXTRA_COLUMNS.has(h))
  const ticketIdx = header.findIndex(h => _TICKET_COLUMNS.has(h))
  const hasHeader = nameIdx >= 0 && reqIdx >= 0
  const dataRows = hasHeader ? lines.slice(1) : lines
  const nIdx = hasHeader ? nameIdx : 0
  const rIdx = hasHeader ? reqIdx : 1
  const eIdx = hasHeader ? extraIdx : 2
  const tIdx = hasHeader ? ticketIdx : 3
  return dataRows
    .map(cols => ({
      name: (cols[nIdx] ?? '').trim(),
      requestor: (cols[rIdx] ?? '').trim(),
      extraAdmins: eIdx >= 0 ? (cols[eIdx] ?? '').trim() : '',
      ticketKey: tIdx >= 0 ? (cols[tIdx] ?? '').trim() : '',
    }))
    .filter(r => r.name && r.requestor)
}

export default function GitHubRepoCreate() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<FolderGit2 size={20} className="text-white" />}
        label="GitHub Repo Creation"
        description="Bulk-create repos with the team's standard baseline access"
        color="bg-emerald-600"
        onClick={() => setOpen(true)}
      />
      <Modal open={open} onClose={() => setOpen(false)} title="GitHub Repo Creation" wide>
        <RepoCreateForm />
      </Modal>
    </>
  )
}

function RepoCreateForm() {
  const { eligibility, checking } = useGithubEligibility(getRepoCreateEligibility)

  const [rows, setRows] = useState<Row[]>([emptyRow()])
  const [fillAll, setFillAll] = useState('')
  const [forceExisting, setForceExisting] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const { job, start } = useBulkJob<RepoCreateResult, RepoCreateJobExtra>()
  const running = job?.status === 'running'

  function updateRow(id: number, patch: Partial<Row>) {
    setRows(rs => rs.map(r => (r.id === id ? { ...r, ...patch } : r)))
  }

  function addRow() {
    setRows(rs => [...rs, emptyRow()])
  }

  function removeRow(id: number) {
    setRows(rs => (rs.length > 1 ? rs.filter(r => r.id !== id) : rs))
  }

  function applyFillAll() {
    if (!fillAll.trim()) return
    setRows(rs => rs.map(r => ({ ...r, requestor: fillAll.trim() })))
  }

  function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    file.text().then(text => {
      const parsed = parseRepoCsv(text)
      if (parsed.length === 0) return
      setRows(rs => {
        const nonEmpty = rs.filter(r => r.name.trim() || r.requestor.trim())
        return [...nonEmpty, ...parsed.map(p => ({ id: nextId++, ...p }))]
      })
    })
  }

  const validRows = rows.filter(r => r.name.trim() && r.requestor.trim())

  async function submit() {
    setError('')
    if (validRows.length === 0) {
      setError('Enter at least one repo name with a requestor.')
      return
    }
    const specs: RepoCreateSpec[] = validRows.map(r => ({
      name: r.name.trim(),
      requestor: r.requestor.trim(),
      extra_admins: r.extraAdmins.split(',').map(a => a.trim()).filter(Boolean),
      ticket_key: r.ticketKey.trim(),
    }))
    setCreating(true)
    try {
      const { job_id } = await createRepos(specs, forceExisting)
      start(job_id)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not start creating the repositories.'))
    } finally {
      setCreating(false)
    }
  }

  if (checking) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Checking whether you can create repos…
      </div>
    )
  }

  if (!eligibility?.can_send) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        <span>
          You need your own GitHub PAT on file to create repos from here — creation happens with your
          credential. Save a PAT with org-admin and repo permission (classic scopes{' '}
          <code className="font-mono">admin:org</code>, <code className="font-mono">repo</code>) under your
          Profile, then come back to this tab.
        </span>
      </div>
    )
  }

  return (
    <section className="space-y-3 max-w-3xl">
      <p className="text-[11px] ds-u-color--muted bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        This creates real private repos using your own saved PAT ({eligibility.login}), and grants the
        standard baseline access to each one: 3 baseline teams as Admin, the GitHub/Jira service account
        as Admin, plus each repo's own requestor (and any extra admins you list) as Admin.
      </p>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-xs font-medium ds-u-color--muted mb-1">
            Fill all rows with one requestor (when every repo below is for the same person)
          </label>
          <input
            value={fillAll}
            onChange={e => setFillAll(e.target.value)}
            placeholder="shared-requestor-handle"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono"
          />
        </div>
        <button
          onClick={applyFillAll}
          disabled={!fillAll.trim()}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 ds-u-color--muted hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
        >
          <Wand2 size={12} /> Apply to all rows
        </button>
      </div>

      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={row.id} className="flex items-start gap-2 rounded-lg border border-gray-100 dark:border-gray-700 p-2">
            <span className="text-xs ds-u-color--muted pt-2 w-5 flex-shrink-0 text-right">{i + 1}</span>
            <div className="flex-1 grid grid-cols-4 gap-2">
              <input
                value={row.name}
                onChange={e => updateRow(row.id, { name: e.target.value })}
                placeholder="repo-name"
                className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2.5 py-1.5 text-xs font-mono"
              />
              <input
                value={row.requestor}
                onChange={e => updateRow(row.id, { requestor: e.target.value })}
                placeholder="requestor github handle"
                className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2.5 py-1.5 text-xs font-mono"
              />
              <input
                value={row.extraAdmins}
                onChange={e => updateRow(row.id, { extraAdmins: e.target.value })}
                placeholder="extra admins (optional, comma-separated)"
                className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2.5 py-1.5 text-xs font-mono"
              />
              <input
                value={row.ticketKey}
                onChange={e => updateRow(row.id, { ticketKey: e.target.value })}
                placeholder="CLDSPT-##### (optional)"
                title="If someone can't be added as admin yet (not an org member), a comment goes on this ticket instead of relying on memory."
                className="rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
            <button
              onClick={() => removeRow(row.id)}
              disabled={rows.length === 1}
              className="p-1.5 rounded ds-u-color--muted hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-30"
              title="Remove row"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            onClick={addRow}
            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 ds-u-color--muted hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <Plus size={12} /> Add another repo
          </button>
          <label className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline cursor-pointer">
            <Upload size={12} /> Upload .csv (name, requestor, extra_admins, ticket_key columns)
            <input type="file" accept=".csv,.txt" onChange={onFileChosen} className="hidden" disabled={running} />
          </label>
        </div>
        <label className="flex items-center gap-1.5 text-xs ds-u-color--muted">
          <input type="checkbox" checked={forceExisting} onChange={e => setForceExisting(e.target.checked)} disabled={running} />
          If a name already exists, re-apply access to it anyway
        </label>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <div>
        <button
          onClick={submit}
          disabled={creating || running || validRows.length === 0}
          className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg bg-cms-blue text-white hover:opacity-90 disabled:opacity-50"
        >
          {creating ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          Create {validRows.length > 0 ? validRows.length : ''} repo{validRows.length === 1 ? '' : 's'}
        </button>
      </div>

      {job && running && <JobProgress job={job} />}

      {job && job.status === 'error' && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" /> {job.error}
        </div>
      )}

      {job && job.status !== 'running' && job.status !== 'error' && (
        <div className="space-y-2 pt-2 max-h-96 overflow-y-auto">
          {job.results.map(r => {
            const blocked = r.repo_already_existed && !!r.repo_error
            const tone = r.ok
              ? 'bg-green-50 border-green-200 text-green-900'
              : blocked
                ? 'bg-amber-50 border-amber-200 text-amber-900'
                : 'bg-red-50 border-red-200 text-red-900'
            return (
            <div key={r.name} className={`rounded-lg border px-3 py-2 text-xs ${tone}`}>
              <p className="font-medium flex items-center gap-1.5">
                {r.ok ? <CheckCircle size={13} /> : blocked ? <AlertTriangle size={13} /> : <XCircle size={13} />}
                {r.name}
                <span className="font-normal opacity-80">
                  — requestor {r.requestor}{r.extra_admins.length > 0 ? `, +${r.extra_admins.join(', ')}` : ''}
                </span>
              </p>
              {r.repo_error && <p className="mt-1">{r.repo_error}</p>}
              {r.invalid_handles.length > 0 && (
                <p className="mt-1">Unknown GitHub handle(s), nothing created: {r.invalid_handles.join(', ')}</p>
              )}
              {!r.repo_error && r.invalid_handles.length === 0 && (
                <>
                  <p className="mt-1 opacity-80">
                    {r.repo_already_existed ? 'Repo already existed — access re-applied and verified.' : 'Repo created.'}
                  </p>
                  {[...r.teams, ...r.collaborators].filter(s => !s.ok).map((s, i) => (
                    <p key={`failed-${i}`} className="mt-0.5">
                      Grant failed: {s.team ?? s.username} ({s.error})
                    </p>
                  ))}
                  {[...r.teams, ...r.collaborators].filter(s => s.ok && !s.verified).map((s, i) => (
                    <p key={`unverified-${i}`} className="mt-0.5">
                      GitHub accepted the grant for {s.team ?? s.username}, but re-checking it afterward
                      didn't show Admin access — verify manually before trusting this one.
                    </p>
                  ))}
                  {r.skipped_non_members.length > 0 && (
                    <p className="mt-1 text-amber-800">
                      Not added as admin — not yet an org member: {r.skipped_non_members.join(', ')}.
                      Get them through the access-request process, then add them as a collaborator here.
                    </p>
                  )}
                </>
              )}
            </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
