import { useState } from 'react'
import { AlertTriangle, Bot, CheckCircle, Loader2, Send, Upload } from 'lucide-react'
import {
  apiErrorMessage,
  assignCopilotSeats,
  getCopilotSeatEligibility,
  type CopilotSeatJobExtra,
} from '../../api/client'
import { parseList } from '../../utils/parseList'
import { useGithubEligibility } from '../../hooks/useGithubEligibility'
import { useBulkJob } from '../../hooks/useBulkJob'
import { useCsvTextareaUpload } from '../../hooks/useCsvTextareaUpload'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import JobProgress from '../ui/JobProgress'

function Bucket({ title, tone, items, note }: { title: string; tone: string; items: string[]; note?: string }) {
  if (items.length === 0) return null
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${tone}`}>
      <p className="font-medium">{title} ({items.length})</p>
      <p className="mt-0.5 font-mono break-words">{items.join(', ')}</p>
      {note && <p className="mt-1 opacity-80">{note}</p>}
    </div>
  )
}

export default function GitHubCopilotSeatAssign() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<Bot size={20} className="text-white" />}
        label="GitHub Copilot Seat Assignment"
        description="Bulk-assign Copilot seats to GitHub handles"
        color="bg-violet-600"
        onClick={() => setOpen(true)}
      />
      <Modal open={open} onClose={() => setOpen(false)} title="GitHub Copilot Seat Assignment" wide>
        <CopilotSeatAssignForm />
      </Modal>
    </>
  )
}

function CopilotSeatAssignForm() {
  const { eligibility, checking, orgs, org, setOrg } = useGithubEligibility(getCopilotSeatEligibility, true)

  const [handlesRaw, setHandlesRaw] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [error, setError] = useState('')
  const { job, start } = useBulkJob<unknown, CopilotSeatJobExtra>()

  const handles = parseList(handlesRaw, true)
  const running = job?.status === 'running'
  const onFileChosen = useCsvTextareaUpload(setHandlesRaw, 'handle')

  async function submit() {
    setError('')
    if (handles.length === 0) {
      setError('Enter at least one GitHub handle.')
      return
    }
    setAssigning(true)
    try {
      const { job_id } = await assignCopilotSeats(handles, org)
      start(job_id)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not start assigning Copilot seats.'))
    } finally {
      setAssigning(false)
    }
  }

  if (checking) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Checking whether you can assign seats…
      </div>
    )
  }

  if (!eligibility?.can_send) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        <span>
          You need your own GitHub PAT on file to assign Copilot seats from here — the assignment is
          made with your credential. Save a PAT with Copilot billing permission (classic scope{' '}
          <code className="font-mono">manage_billing:copilot</code>, or org admin) under your Profile,
          then come back to this tab.
        </span>
      </div>
    )
  }

  return (
    <section className="space-y-3">
      <p className="text-[11px] ds-u-color--muted bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
        This assigns real Copilot seats in <strong>{org || '…'}</strong> using your own saved PAT
        ({eligibility.login}). Only handles that are active org members without a seat already get
        changed — everyone else is reported back, not silently skipped.
      </p>

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

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="block text-xs font-medium ds-u-color--muted">
            GitHub handles (comma or newline separated)
          </label>
          <label className="inline-flex items-center gap-1 text-[11px] text-cms-blue hover:underline cursor-pointer">
            <Upload size={11} /> Upload .csv / .txt
            <input type="file" accept=".csv,.txt" onChange={onFileChosen} className="hidden" disabled={running} />
          </label>
        </div>
        <textarea
          value={handlesRaw}
          onChange={e => setHandlesRaw(e.target.value)}
          rows={5}
          disabled={running}
          placeholder={'octocat\nhubot'}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm font-mono disabled:opacity-60"
        />
        {handles.length > 0 && (
          <p className="text-[11px] ds-u-color--muted mt-1">{handles.length} handle{handles.length === 1 ? '' : 's'}</p>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      <button
        onClick={submit}
        disabled={assigning || running || handles.length === 0}
        className="inline-flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg bg-cms-blue text-white hover:opacity-90 disabled:opacity-50"
      >
        {assigning ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
        Assign {handles.length > 0 ? handles.length : ''} seat{handles.length === 1 ? '' : 's'} in {org || '…'}
      </button>

      {job && running && <JobProgress job={job} />}

      {job && job.status === 'error' && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
          <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" /> {job.error}
        </div>
      )}

      {job && job.status === 'done' && (() => {
        const e = job.extra
        return (
        <div className="space-y-2 pt-2">
          <p className="text-[11px] ds-u-color--muted">
            Org {e.org}, assigned by <span className="font-mono">{e.assigned_by}</span>.
          </p>
          {e.policy_warning && (
            <Bucket title="Policy warning" tone="bg-amber-50 border-amber-200 text-amber-900" items={[e.policy_warning]} />
          )}
          <Bucket title="Assigned" tone="bg-green-50 border-green-200 text-green-800" items={e.assigned} />
          <Bucket title="Already had a seat" tone="bg-gray-50 border-gray-200 text-gray-700" items={e.already_seated} />
          <Bucket
            title="Not org members"
            tone="bg-red-50 border-red-200 text-red-700"
            items={e.not_members}
            note="The API will not assign a seat until they accept an org invite."
          />
          <Bucket
            title="Invite pending"
            tone="bg-amber-50 border-amber-200 text-amber-900"
            items={e.pending_invite}
            note="Can't hold a seat until the org invite is accepted."
          />
          <Bucket
            title="Could not be checked"
            tone="bg-gray-50 border-gray-200 text-gray-700"
            items={e.undetermined}
            note="Permissions, rate limit, or API error — excluded from this run rather than guessed at."
          />
          <Bucket
            title="Assignment did not take"
            tone="bg-red-50 border-red-200 text-red-700"
            items={e.assign_failed}
            note="Confirmed without a seat after the write — investigate before assuming this is complete."
          />
          <Bucket
            title="Could not verify"
            tone="bg-amber-50 border-amber-200 text-amber-900"
            items={e.assign_unverifiable}
            note="Not the same as a failure — the assignment may have worked; re-check."
          />
          {e.rejected_input.length > 0 && (
            <Bucket
              title="Rejected input"
              tone="bg-gray-50 border-gray-200 text-gray-700"
              items={e.rejected_input.map(r => `${r.value} (${r.reason})`)}
            />
          )}
          {e.assigned.length === 0 && e.already_seated.length === 0 &&
            e.not_members.length === 0 && e.assign_failed.length === 0 &&
            e.rejected_input.length === 0 && e.pending_invite.length === 0 &&
            e.undetermined.length === 0 && e.assign_unverifiable.length === 0 && (
              <div className="flex items-start gap-2 bg-green-50 border border-green-200 text-green-800 rounded-lg px-3 py-2 text-xs">
                <CheckCircle size={13} className="flex-shrink-0 mt-0.5" /> Nothing needed changing.
              </div>
          )}
        </div>
        )
      })()}
    </section>
  )
}
