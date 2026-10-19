import { useState } from 'react'
import { AlertTriangle, CheckCircle, Loader2, Send, Upload, UserPlus } from 'lucide-react'
import {
  apiErrorMessage,
  getOrgInviteEligibility,
  sendOrgInvites,
  type OrgInviteJobExtra,
  type OrgInviteResult,
} from '../../api/client'
import { parseList } from '../../utils/parseList'
import { useGithubEligibility } from '../../hooks/useGithubEligibility'
import { useBulkJob } from '../../hooks/useBulkJob'
import { useCsvTextareaUpload } from '../../hooks/useCsvTextareaUpload'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import JobProgress from '../ui/JobProgress'

export default function GitHubOrgInvites() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<Send size={20} className="text-white" />}
        label="GitHub Org Invitations"
        description="Bulk-invite users to the org, attributed to your own GitHub PAT"
        color="bg-slate-800"
        onClick={() => setOpen(true)}
      />
      <Modal open={open} onClose={() => setOpen(false)} title="GitHub Org Invitations" wide>
        <OrgInvitesForm />
      </Modal>
    </>
  )
}

function OrgInvitesForm() {
  const { eligibility, checking, orgs, org, setOrg } = useGithubEligibility(getOrgInviteEligibility, true)

  const [emailsRaw, setEmailsRaw] = useState('')
  const [role, setRole] = useState<'member' | 'owner'>('member')
  const [team, setTeam] = useState('')
  const [approvalNote, setApprovalNote] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const { job, start } = useBulkJob<OrgInviteResult, OrgInviteJobExtra>()

  const emails = parseList(emailsRaw)
  const running = job?.status === 'running'
  const onFileChosen = useCsvTextareaUpload(setEmailsRaw, 'email')

  async function submit() {
    setError('')
    if (emails.length === 0) {
      setError('Enter at least one email address.')
      return
    }
    if (!approvalNote.trim()) {
      setError("Enter an approval reference (e.g. Hung's approval, or a ticket key).")
      return
    }
    setSending(true)
    try {
      const { job_id } = await sendOrgInvites(emails, role, team.trim(), approvalNote.trim(), org)
      start(job_id)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not start sending the invitations.'))
    } finally {
      setSending(false)
    }
  }

  if (checking) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Checking whether you can send invites…
      </div>
    )
  }

  if (!eligibility?.can_send) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        <span>
          You need your own GitHub PAT on file to send org invites from here — invites are sent with
          your credential so GitHub shows <em>you</em> as the inviter, not the dashboard's shared
          account. Save a PAT with org-invite permission (classic scope <code className="font-mono">admin:org</code>,
          or a fine-grained PAT with the Members: write org permission) under your Profile, then come
          back to this tab.
        </span>
      </div>
    )
  }

  return (
    <section className="space-y-3">
      <p className="text-[11px] ds-u-color--muted bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        This sends real GitHub org invitations to <strong>{org || '…'}</strong> using your own saved PAT
        ({eligibility.login}) — GitHub will show you as the inviter. This is not a dry run; double-check
        the org and the list before sending.
      </p>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs font-medium ds-u-color--muted">
            Emails to invite (comma or newline separated)
          </label>
          <label className="inline-flex items-center gap-1 text-[11px] text-cms-blue hover:underline cursor-pointer">
            <Upload size={11} /> Upload .csv / .txt
            <input type="file" accept=".csv,.txt" onChange={onFileChosen} className="hidden" disabled={running} />
          </label>
        </div>
        <textarea
          value={emailsRaw}
          onChange={e => setEmailsRaw(e.target.value)}
          rows={5}
          disabled={running}
          placeholder={'jane@example.com\njohn@example.com'}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono disabled:opacity-60"
        />
        {emails.length > 0 && (
          <p className="text-[11px] ds-u-color--muted mt-1">{emails.length} recipient{emails.length === 1 ? '' : 's'}</p>
        )}
      </div>

      <div>
        <label className="block text-xs font-medium ds-u-color--muted mb-1">Org</label>
        {orgs.length > 1 ? (
          <select
            value={org}
            onChange={e => setOrg(e.target.value)}
            className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
          >
            {orgs.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        ) : (
          <p className="text-sm font-mono px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-600 ds-u-color--muted">
            {org || '…'}
          </p>
        )}
        {orgs.length <= 1 && (
          <p className="text-[11px] ds-u-color--muted mt-1">
            Only org your saved PAT currently has access to. More orgs will appear here automatically
            once your PAT can see them.
          </p>
        )}
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <label className="block text-xs font-medium ds-u-color--muted mb-1">Role</label>
          <select
            value={role}
            onChange={e => setRole(e.target.value as 'member' | 'owner')}
            className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
          >
            <option value="member">Member</option>
            <option value="owner">Owner</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium ds-u-color--muted mb-1">Team (optional)</label>
          <input
            value={team}
            onChange={e => setTeam(e.target.value)}
            placeholder="cms-enterprise-all-users"
            className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium ds-u-color--muted mb-1">
          Approval reference (e.g. Hung's approval, or a CLDSPT ticket key)
        </label>
        <input
          value={approvalNote}
          onChange={e => setApprovalNote(e.target.value)}
          placeholder="Approved by Hung on CLDSPT-xxxxx"
          className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm"
        />
        <p className="text-[11px] ds-u-color--muted mt-1">Recorded in the audit log with this invite batch.</p>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <button
        onClick={submit}
        disabled={sending || running || emails.length === 0}
        className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg bg-cms-blue text-white hover:opacity-90 disabled:opacity-50"
      >
        {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
        Send {emails.length > 0 ? emails.length : ''} invite{emails.length === 1 ? '' : 's'} to {org || '…'}
      </button>

      {job && running && <JobProgress job={job} />}

      {job && job.status !== 'running' && (
        <div className="space-y-2 pt-2">
          {job.status === 'error' ? (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
              <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" /> {job.error}
            </div>
          ) : (
            <>
              {(() => {
                const sent = job.results.filter(r => r.ok).length
                const failed = job.results.length - sent
                return (
                  <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs border ${
                    failed === 0 ? 'bg-green-50 border-green-200 text-green-800' : 'bg-amber-50 border-amber-200 text-amber-900'
                  }`}>
                    {failed === 0 ? <CheckCircle size={13} className="flex-shrink-0 mt-0.5" /> : <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />}
                    <span>
                      {sent} sent, {failed} failed — org {job.extra.org}, role {job.extra.role},
                      team {job.extra.team ?? '(none)'}, invited by <span className="font-mono">{job.extra.invited_by}</span>.
                    </span>
                  </div>
                )
              })()}
              <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden max-h-80 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-800 ds-u-color--muted">
                      <th className="text-left px-3 py-1.5 font-medium">Email</th>
                      <th className="text-left px-3 py-1.5 font-medium">Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.results.map((r, i) => (
                      <tr key={r.email} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                        <td className="px-3 py-1.5">{r.email}</td>
                        <td className="px-3 py-1.5">
                          {r.ok ? (
                            <span className="text-green-700 inline-flex items-center gap-1"><UserPlus size={11} /> invited</span>
                          ) : (
                            <span className="text-red-600">{r.error}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
