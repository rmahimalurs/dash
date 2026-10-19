import { useState, useEffect, useRef, FormEvent } from 'react'
import { Copy, Loader2, AlertCircle, CheckCircle, ExternalLink, XCircle } from 'lucide-react'
import Modal from '../ui/Modal'
import {
  previewCopyController,
  runCopyController,
  applyCopyControllerSecrets,
  applyCopyControllerJobs,
  getCopyControllerStatus,
  type CopyControllerPreview,
  type CopyControllerRunResult,
  type CopyControllerStatus, apiErrorMessage } from '../../api/client'


export default function CopyControllerWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex flex-col items-start gap-3 p-5 bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 shadow-sm hover:shadow-md hover:border-cms-blue/30 transition-all duration-150 text-left group w-full"
      >
        <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-cms-blue group-hover:scale-110 transition-transform duration-150">
          <Copy size={20} className="text-white" />
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-800 dark:text-gray-100 group-hover:text-cms-blue transition-colors">
            Copy Controllers
          </p>
          <p className="text-xs ds-u-color--muted mt-0.5">
            Copy controllers from prod to dev
          </p>
        </div>
      </button>
      <CopyControllerModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function CopyControllerModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('')
  const [jobsMode, setJobsMode] = useState<'all' | 'list' | 'none'>('none')
  const [jobList, setJobList] = useState('')
  const [copySecrets, setCopySecrets] = useState(false)
  const [copyPlugins, setCopyPlugins] = useState(false)
  const [copyAwsRoles, setCopyAwsRoles] = useState(true)

  const [preview, setPreview] = useState<CopyControllerPreview | null>(null)
  const [awsRoles, setAwsRoles] = useState('')
  const [networkCidrs, setNetworkCidrs] = useState('')
  const [admins, setAdmins] = useState('')

  const [previewing, setPreviewing] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<CopyControllerRunResult | null>(null)

  function reset() {
    setName('')
    setJobsMode('none')
    setJobList('')
    setCopySecrets(false)
    setCopyPlugins(false)
    setCopyAwsRoles(true)
    setPreview(null)
    setAwsRoles('')
    setNetworkCidrs('')
    setAdmins('')
    setError('')
    setResult(null)
  }

  function handleDismiss() {
    reset()
    onClose()
  }

  async function handlePreview(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) {
      setError('Controller name is required')
      return
    }
    setError('')
    setPreviewing(true)
    try {
      const data = await previewCopyController(name.trim())
      setPreview(data)
      // AWS Roles only auto-populates when the copy checkbox is ticked.
      setAwsRoles(copyAwsRoles ? data.aws_roles.join('\n') : '')
      setNetworkCidrs(data.network_cidrs.join('\n'))
      setAdmins(data.admins.join('\n'))
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Preview failed.'))
    } finally {
      setPreviewing(false)
    }
  }

  async function handleRun() {
    setError('')
    setRunning(true)
    try {
      const splitLines = (s: string) =>
        s.split(/[\n,]+/).map(x => x.trim()).filter(Boolean)
      const res = await runCopyController({
        controller_name: name.trim(),
        aws_roles: splitLines(awsRoles),
        network_ranges: splitLines(networkCidrs),
        admins: splitLines(admins),
        migrate_all_jobs: jobsMode === 'all',
        job_list: jobsMode === 'list' ? splitLines(jobList) : [],
        copy_secrets: copySecrets,
        copy_plugins: copyPlugins,
      })
      setResult(res)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Run failed.'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal open={open} onClose={handleDismiss} title="Copy Controller — Prod → Dev" wide>
      {result ? (
        <ResultPanel result={result} onClose={handleDismiss} />
      ) : (
        <div className="space-y-5">
          {/* Step 1: name + options */}
          <form onSubmit={handlePreview} className="space-y-4">
            <div>
              <label className="label">Controller name</label>
              <input
                type="text"
                className="input-field font-mono"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="appserv"
                disabled={!!preview}
              />
              <p className="text-[11px] ds-u-color--muted mt-1">Name of the prod-east controller to copy.</p>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide">Job migration</p>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="jobs" checked={jobsMode === 'none'} onChange={() => setJobsMode('none')} />
                <span>Do not migrate jobs (MVP)</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="jobs" checked={jobsMode === 'all'} onChange={() => setJobsMode('all')} />
                <span>Migrate all jobs</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="jobs" checked={jobsMode === 'list'} onChange={() => setJobsMode('list')} />
                <span>Migrate specific jobs</span>
              </label>
              {jobsMode === 'list' && (
                <>
                  <input
                    type="text"
                    className="input-field font-mono"
                    value={jobList}
                    onChange={e => setJobList(e.target.value)}
                    placeholder="job-a, folder/job-b, job-c, folder/*, prefix-*"
                  />
                  <p className="text-[11px] ds-u-color--muted">
                    Wildcards supported. <code className="font-mono">*</code> matches any run of characters including <code className="font-mono">/</code>. Example: <code className="font-mono">folder/*</code> exports everything under <code className="font-mono">folder</code>; <code className="font-mono">deploy-*</code> exports every top-level item starting with <code className="font-mono">deploy-</code>.
                  </p>
                </>
              )}
            </div>

            <div className="flex flex-wrap gap-x-6 gap-y-2">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={copyAwsRoles} onChange={e => setCopyAwsRoles(e.target.checked)} />
                <span>Copy AWS Roles</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={copySecrets} onChange={e => setCopySecrets(e.target.checked)} />
                <span>Copy secrets</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={copyPlugins} onChange={e => setCopyPlugins(e.target.checked)} />
                <span>Copy plugins</span>
              </label>
            </div>

            {!preview && (
              <div className="flex gap-3">
                <button type="button" onClick={handleDismiss} className="btn-secondary flex-1">Cancel</button>
                <button
                  type="submit"
                  disabled={previewing || !name.trim()}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {previewing && <Loader2 size={14} className="animate-spin" />}
                  {previewing ? 'Loading…' : 'Preview'}
                </button>
              </div>
            )}
          </form>

          {/* Step 2: preview / edit */}
          {preview && (
            <div className="space-y-4 pt-3 border-t border-gray-100">
              <p className="text-xs ds-u-color--muted uppercase tracking-wide font-semibold">
                Discovered config (editable before Run)
              </p>

              {preview.already_exists_on_dev && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex items-start gap-2">
                  <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold">Controller already exists on dev-east.</p>
                    <p className="mt-0.5">
                      The onboarding job will be <strong>skipped</strong>. Jobs, secrets, plugins,
                      and any other follow-ups you enable will still run against the existing controller.
                    </p>
                  </div>
                </div>
              )}

              <EditableList
                label="AWS Roles"
                value={awsRoles}
                onChange={setAwsRoles}
                error={copyAwsRoles ? preview.aws_roles_error : null}
                hint={
                  !copyAwsRoles
                    ? '"Copy AWS Roles" is unchecked — field left empty. Tick it in step 1 to auto-populate.'
                    : preview.aws_policy_arn ? `From IAM policy: ${preview.aws_policy_arn}` : undefined
                }
                placeholder="arn:aws:iam::123456789012:role/example-role"
              />
              <EditableList
                label="Network Ranges (CIDRs)"
                value={networkCidrs}
                onChange={setNetworkCidrs}
                error={preview.network_cidrs_error}
                hint={
                  preview.network_namespace
                    ? `Discovered from ${preview.network_np_count ?? 0} NetworkPolicy egress rules in ${preview.network_namespace}.`
                    : undefined
                }
                placeholder="10.232.0.0/19"
              />
              <EditableList
                label="Admins"
                value={admins}
                onChange={setAdmins}
                error={preview.admins_error}
                hint="From the prod controller's CloudBees RBAC groups carrying the admin role. Comma- or newline-separated usernames."
                placeholder="rwrw, h4qt"
              />

              <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-blue-800 space-y-1">
                <p className="font-semibold">On Run, this will:</p>
                <ul className="list-disc list-inside space-y-0.5 text-blue-700">
                  {preview.already_exists_on_dev ? (
                    <li><strong>Skip</strong> the onboarding trigger (controller already exists on dev-east)</li>
                  ) : (
                    <>
                      <li>Trigger <code className="font-mono">cbc-onboarding-casc</code> on dev-east tooling</li>
                      <li>Pass <code className="font-mono">TEAM_NAME</code>, <code className="font-mono">AWS_ROLES</code>, <code className="font-mono">NETWORK_RANGES</code>, <code className="font-mono">ADMINS</code>; <code className="font-mono">CLDSPT_TICKET=CLDSPT-99999</code>, <code className="font-mono">FISMAID=test</code></li>
                    </>
                  )}
                  <li>Run any enabled follow-ups: {[jobsMode !== 'none' && 'jobs', copySecrets && 'secrets', copyPlugins && 'plugins'].filter(Boolean).join(', ') || 'none'}</li>
                </ul>
              </div>

              {error && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
                  <XCircle size={14} className="flex-shrink-0" /> {error}
                </div>
              )}

              <div className="flex gap-3">
                <button onClick={handleDismiss} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleRun}
                  disabled={running}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {running && <Loader2 size={14} className="animate-spin" />}
                  {running
                    ? 'Running…'
                    : preview.already_exists_on_dev
                      ? 'Run follow-ups only'
                      : 'Run'}
                </button>
              </div>
            </div>
          )}

          {error && !preview && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <XCircle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}


function EditableList({
  label,
  value,
  onChange,
  error,
  hint,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  error?: string | null
  hint?: string
  placeholder?: string
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <textarea
        className="input-field font-mono text-xs"
        rows={Math.max(2, Math.min(6, value.split('\n').length))}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {error && (
        <p className="text-[11px] text-amber-700 mt-1 flex items-center gap-1">
          <AlertCircle size={11} /> {error}
        </p>
      )}
      {!error && hint && (
        <p className="text-[11px] ds-u-color--muted mt-1">{hint}</p>
      )}
    </div>
  )
}


function ResultPanel({ result, onClose }: { result: CopyControllerRunResult; onClose: () => void }) {
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<string | null>(null)
  const [applyError, setApplyError] = useState('')
  const [secretsEdit, setSecretsEdit] = useState(result.secrets_encoded || '')

  // Live poller for onboarding build + controller readiness on dev-east.
  // Seed with what we know from the Run response so we don't wait for the
  // first tick to render something.
  const [status, setStatus] = useState<CopyControllerStatus | null>(() => ({
    controller_name: result.controller_name,
    controller_exists_on_dev: !!result.already_existed_on_dev,
    existence_error: null,
    build_url:  result.build_url ?? result.queue_url ?? null,
    build_number: result.build_number ?? null,
    build_building: result.already_existed_on_dev ? false : true,
    build_result: null,
    build_error: null,
  }))
  const [pollElapsed, setPollElapsed] = useState(0)
  const startedAtRef = useRef<number>(Date.now())

  useEffect(() => {
    // Nothing to poll if the controller was already online at Run time.
    if (result.already_existed_on_dev) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const POLL_INTERVAL = 15_000
    const MAX_POLL_MS = 20 * 60 * 1000  // give up after 20 minutes

    const tick = async () => {
      if (cancelled) return
      try {
        const s = await getCopyControllerStatus(result.controller_name, result.build_url ?? undefined)
        if (cancelled) return
        setStatus(s)
        setPollElapsed(Date.now() - startedAtRef.current)
        // Stop conditions
        if (s.controller_exists_on_dev) return
        if (s.build_result && s.build_result !== 'SUCCESS') return
        if (Date.now() - startedAtRef.current > MAX_POLL_MS) return
      } catch {
        // swallow transient errors and keep polling
      }
      timer = setTimeout(tick, POLL_INTERVAL)
    }

    // First tick after a small delay to give the build a moment to appear.
    timer = setTimeout(tick, 4_000)
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [result.controller_name, result.build_url, result.already_existed_on_dev])

  const controllerReady = status?.controller_exists_on_dev ?? false
  const buildFailed = status?.build_result && status.build_result !== 'SUCCESS'
  const pollTimedOut = pollElapsed > 20 * 60 * 1000

  async function handleApply() {
    setApplyError('')
    setApplyResult(null)
    setApplying(true)
    try {
      const res = await applyCopyControllerSecrets(result.controller_name, secretsEdit)
      setApplyResult(res.output || 'Applied.')
    } catch (e: any) {
      setApplyError(apiErrorMessage(e, 'Apply failed.'))
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className={`flex items-start gap-3 rounded-lg p-4 border ${
        result.already_existed_on_dev
          ? 'bg-amber-50 border-amber-200'
          : 'bg-green-50 border-green-200'
      }`}>
        {result.already_existed_on_dev ? (
          <AlertCircle size={20} className="text-amber-600 flex-shrink-0 mt-0.5" />
        ) : (
          <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
        )}
        <div>
          <p className={`text-sm font-semibold ${result.already_existed_on_dev ? 'text-amber-800' : 'text-green-800'}`}>
            {result.already_existed_on_dev
              ? 'Onboarding skipped — controller already existed on dev-east.'
              : 'Onboarding job triggered.'}
          </p>
          <p className={`text-sm mt-0.5 ${result.already_existed_on_dev ? 'text-amber-700' : 'text-green-700'}`}>
            {result.controller_name} — status: <strong>{result.status}</strong>
          </p>
        </div>
      </div>

      {result.build_url && (
        <a href={result.build_url} target="_blank" rel="noopener noreferrer"
           className="flex items-center gap-2 text-sm text-cms-blue hover:underline">
          Build #{result.build_number} <ExternalLink size={13} />
        </a>
      )}
      {!result.build_url && result.queue_url && (
        <a href={result.queue_url} target="_blank" rel="noopener noreferrer"
           className="flex items-center gap-2 text-sm text-cms-blue hover:underline">
          Queue item <ExternalLink size={13} />
        </a>
      )}

      {!result.already_existed_on_dev && (
        <div className={`rounded-lg px-3 py-3 border ${
          buildFailed || pollTimedOut
            ? 'bg-red-50 border-red-200'
            : controllerReady
              ? 'bg-green-50 border-green-200'
              : 'bg-blue-50 border-blue-100'
        }`}>
          <div className="flex items-center gap-2 text-xs font-semibold">
            {controllerReady ? (
              <CheckCircle size={14} className="text-green-600" />
            ) : buildFailed || pollTimedOut ? (
              <XCircle size={14} className="text-red-600" />
            ) : (
              <Loader2 size={14} className="text-blue-600 animate-spin" />
            )}
            {controllerReady
              ? <span className="text-green-800">Controller is online on dev-east — Apply buttons enabled.</span>
              : buildFailed
                ? <span className="text-red-800">Onboarding build ended: {status?.build_result}. Investigate before applying follow-ups.</span>
                : pollTimedOut
                  ? <span className="text-red-800">Controller hasn't come online after 20 minutes. Investigate the build.</span>
                  : <span className="text-blue-800">
                      Onboarding {status?.build_building ? 'running' : 'starting'}
                      {status?.build_number ? ` — build #${status.build_number}` : ''}
                      {pollElapsed > 0 ? ` — elapsed ${Math.round(pollElapsed / 1000)}s` : ''}
                    </span>
            }
          </div>
          {!controllerReady && !buildFailed && !pollTimedOut && (
            <p className="text-[11px] text-blue-700 mt-1">
              Apply Secrets / Jobs / Plugins buttons stay disabled until the dev-east controller is online.
              Polls every 15 s; stops after 20 min if the controller doesn't come up.
            </p>
          )}
        </div>
      )}

      <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
        <p className="text-xs font-semibold text-gray-600 mb-1">Parameters sent</p>
        <dl className="text-xs grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
          {Object.entries(result.parameters).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-mono ds-u-color--muted">{k}</dt>
              <dd className="font-mono text-gray-700 break-all">{v || '(empty)'}</dd>
            </div>
          ))}
        </dl>
      </div>

      {result.pending_followups.secrets && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-3 space-y-2">
          <p className="text-xs font-semibold text-blue-800">Secrets exported from prod</p>
          {result.secrets_error ? (
            <p className="text-xs text-red-700 flex items-center gap-1">
              <AlertCircle size={11} /> {result.secrets_error}
            </p>
          ) : result.secrets_encoded ? (
            <>
              <p className="text-[11px] text-blue-700">
                Wait for the onboarding build to finish, then click <strong>Apply secrets</strong> to push these
                credentials into the new dev controller's System store.
              </p>
              <textarea
                className="input-field font-mono text-[10px] leading-tight"
                rows={4}
                value={secretsEdit}
                onChange={e => setSecretsEdit(e.target.value)}
              />
              <button
                onClick={handleApply}
                disabled={applying || !secretsEdit.trim() || !controllerReady}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {applying && <Loader2 size={14} className="animate-spin" />}
                {applying
                  ? 'Applying…'
                  : !controllerReady
                    ? 'Waiting for controller to come online…'
                    : `Apply secrets to dev/${result.controller_name}`}
              </button>
              {applyError && (
                <p className="text-xs text-red-700 flex items-start gap-1"><XCircle size={11} className="mt-0.5" /> {applyError}</p>
              )}
              {applyResult && (
                <pre className="text-[10px] bg-white border border-gray-100 rounded p-2 overflow-x-auto whitespace-pre-wrap">{applyResult}</pre>
              )}
            </>
          ) : null}
        </div>
      )}

      {result.pending_followups.jobs && (
        <JobsApplySection result={result} controllerReady={controllerReady} />
      )}

      {result.pending_followups.plugins && (
        <PluginsSyncSection result={result} />
      )}

      <button onClick={onClose} className="btn-secondary w-full">Done</button>
    </div>
  )
}


function PluginsSyncSection({ result }: { result: CopyControllerRunResult }) {
  const delta = result.plugins_delta ?? []
  const gaps = result.plugins_catalog_gaps ?? []
  if (result.plugins_error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
        <p className="font-semibold flex items-center gap-1"><XCircle size={11} /> Plugin sync failed</p>
        <p className="mt-0.5 break-words">{result.plugins_error}</p>
      </div>
    )
  }
  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-3 space-y-2">
      <p className="text-xs font-semibold text-emerald-800">Plugins synced to CasC bundle</p>
      {result.plugins_no_changes ? (
        <p className="text-[11px] text-emerald-700">{result.plugins_summary}</p>
      ) : (
        <>
          <p className="text-[11px] text-emerald-700">
            {delta.length} plugin(s) added to <code className="font-mono bg-white px-1 rounded">{result.controller_name}-bundle/plugins.yaml</code> on <strong>develop</strong>.
            {gaps.length > 0 && (
              <> {gaps.length} not present in <code className="font-mono bg-white px-1 rounded">CI-parent/plugin-catalog.yaml</code> (flagged in the PR).</>
            )}
          </p>
          {result.plugins_pr_url && (
            <a href={result.plugins_pr_url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-xs text-cms-blue hover:underline">
              Open PR #{result.plugins_pr_number} <ExternalLink size={11} />
            </a>
          )}
          {delta.length > 0 && (
            <details className="text-[11px] text-emerald-700">
              <summary className="cursor-pointer">Delta plugin list ({delta.length})</summary>
              <pre className="mt-1 bg-white border border-gray-100 rounded p-2 overflow-x-auto max-h-40 text-[10px]">{delta.join('\n')}</pre>
            </details>
          )}
        </>
      )}
    </div>
  )
}


function JobsApplySection({ result, controllerReady }: { result: CopyControllerRunResult; controllerReady: boolean }) {
  const [applying, setApplying] = useState(false)
  const [output, setOutput] = useState<string | null>(null)
  const [err, setErr] = useState('')

  async function handleApply() {
    if (!result.jobs_payload) return
    setErr(''); setOutput(null); setApplying(true)
    try {
      const res = await applyCopyControllerJobs(result.controller_name, result.jobs_payload)
      setOutput(res.output || 'Applied.')
    } catch (e: any) {
      setErr(apiErrorMessage(e, 'Apply failed.'))
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="rounded-lg border border-indigo-100 bg-indigo-50 px-3 py-3 space-y-2">
      <p className="text-xs font-semibold text-indigo-800">Jobs exported from prod</p>
      {result.jobs_error ? (
        <p className="text-xs text-red-700 flex items-center gap-1">
          <AlertCircle size={11} /> {result.jobs_error}
        </p>
      ) : result.jobs_payload ? (
        <>
          <p className="text-[11px] text-indigo-700">
            {result.jobs_count ?? 0} item(s): {result.jobs_folders ?? 0} folder(s), {result.jobs_jobs ?? 0} job(s).
            Wait for the onboarding build to finish, then click below to recreate them on the dev controller.
            (Secrets, if also copied, should be applied first.)
          </p>
          {result.jobs_export_errors && result.jobs_export_errors.length > 0 && (
            <p className="text-[11px] text-amber-700">
              {result.jobs_export_errors.length} item(s) could not be exported and will be skipped.
            </p>
          )}
          <button
            onClick={handleApply}
            disabled={applying || !controllerReady}
            className="btn-primary w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700"
          >
            {applying && <Loader2 size={14} className="animate-spin" />}
            {applying
              ? 'Applying…'
              : !controllerReady
                ? 'Waiting for controller to come online…'
                : `Apply jobs to dev/${result.controller_name}`}
          </button>
          {err && (
            <p className="text-xs text-red-700 flex items-start gap-1"><XCircle size={11} className="mt-0.5" /> {err}</p>
          )}
          {output && (
            <pre className="text-[10px] bg-white border border-gray-100 rounded p-2 overflow-x-auto whitespace-pre-wrap">{output}</pre>
          )}
        </>
      ) : null}
    </div>
  )
}
