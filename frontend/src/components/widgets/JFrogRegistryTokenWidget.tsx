import { useState, useEffect } from 'react'
import { KeyRound, Loader2, CheckCircle, AlertTriangle, ChevronDown, ChevronLeft, ShieldCheck } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getJFrogRegistryTokenTargets,
  rotateJFrogRegistryToken,
  refreshJFrogRegistryToken,
  type JFrogRegistryTokenTarget,
  type JFrogRegistryTokenResult, apiErrorMessage } from '../../api/client'

export default function JFrogRegistryTokenWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<KeyRound size={20} className="text-white" />}
        label="JFrog Entitlement Credential"
        description="Apply the monthly JFrog subscription credential"
        color="bg-amber-600"
        onClick={() => setOpen(true)}
      />
      <JFrogRegistryTokenModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function JFrogRegistryTokenModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [targets, setTargets] = useState<JFrogRegistryTokenTarget[]>([])
  const [env, setEnv] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<JFrogRegistryTokenResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    getJFrogRegistryTokenTargets()
      .then(ts => {
        setTargets(ts)
        const first = ts.find(t => t.ready) ?? ts[0]
        if (first) setEnv(prev => prev || first.env)
      })
      .catch(() => setTargets([]))
  }, [open])

  function handleClose() {
    setEnv(''); setUsername(''); setPassword('')
    setConfirming(false); setResult(null); setError('')
    onClose()
  }

  const current = targets.find(t => t.env === env)
  const ready = current?.ready !== false
  const canSubmit = ready && !running && username.trim().length > 0 && password.length > 0

  // The refresh token authenticates with the credential already in the secret,
  // so there is nothing for the engineer to paste.
  async function handleRequest() {
    setError(''); setRunning(true)
    try {
      setResult(await refreshJFrogRegistryToken(env))
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Could not request a token from JFrog.'))
    } finally {
      setPassword('')
      setConfirming(false)
      setRunning(false)
    }
  }

  async function handleRun() {
    setError(''); setRunning(true)
    try {
      setResult(await rotateJFrogRegistryToken(env, username.trim(), password))
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Rotation failed.'))
    } finally {
      setPassword('')
      setConfirming(false)
      setRunning(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="JFrog Entitlement Credential">
      {result ? (
        <div className="space-y-4 py-2">
          <div className="flex items-center gap-2 text-green-700">
            <CheckCircle size={18} /> <span className="font-semibold">Committed to {result.branch}</span>
          </div>
          <div className="text-sm space-y-1.5 text-gray-700 dark:text-gray-300">
            <p><span className="font-medium">Branch:</span> <code className="text-xs break-all">{result.branch}</code></p>
            <p><span className="font-medium">File:</span> <code className="text-xs break-all">{result.path}</code></p>
            <p>
              <span className="font-medium">Branch sync:</span>{' '}
              {result.branch_synced
                ? <span>{result.sync_note}</span>
                : <span className="text-amber-700">{result.sync_note}. The credential is committed, but the branch is behind main.</span>}
            </p>
            <p>
              <span className="font-medium">Verified:</span> {result.verified.username} against{' '}
              <code className="text-xs break-all">{result.verified.registry}</code>
              {result.verified.verified ? '' : ' (not verified)'}
            </p>
            <div>
              <span className="font-medium">Secret{result.secrets.length === 1 ? '' : 's'} rewritten:</span>
              {result.secrets.map(s => (
                <div key={s}><code className="text-xs break-all">{s}</code></div>
              ))}
            </div>
          </div>
          <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2 text-xs">
            <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
            <span>
              This is committed to the maintenance branch <strong>{result.branch}</strong> only. It still
              needs review and a merge before the cluster picks it up.
            </span>
          </div>

          {result.refresh_note && (
            <div className={`flex items-start gap-2 rounded-lg px-3 py-2 text-xs border ${
              result.refresh_token_stored
                ? 'bg-blue-50 border-blue-200 text-blue-800'
                : 'bg-red-50 border-red-200 text-red-700'}`}>
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{result.refresh_note}</span>
            </div>
          )}

          {result.apply_commands && result.apply_commands.length > 0 && (
            <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
              <p className="text-xs font-medium text-gray-900 dark:text-gray-100">
                Run these to put it into the {result.env} cluster
              </p>
              <p className="text-[11px] ds-u-color--muted mt-0.5">
                From a checkout of cmscloud-devops on <code>{result.branch}</code>.
              </p>
              <ol className="mt-2 space-y-2">
                {result.apply_commands.map((c, i) => (
                  <li key={i} className="text-xs">
                    <span className="ds-u-color--muted">{i + 1}. {c.step}</span>
                    <pre className="mt-1 whitespace-pre-wrap break-all bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded px-2 py-1.5 font-mono text-[11px]">{c.command}</pre>
                  </li>
                ))}
              </ol>
            </div>
          )}
          <div className="pt-1">
            <button onClick={handleClose} className="btn-primary w-full">Done</button>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 text-xs text-blue-800">
            JFrog issues this credential against our subscription and it is regenerated monthly on the
            JFrog user profile page. Supplying it here re-encrypts every SOPS secret that carries it for
            this environment and commits the change to the current maintenance branch, so it goes live
            with that month's maintenance. It authenticates to releases-authenticated-docker.jfrog.io and
            charts.jfrog.io, not to CMS Artifactory.
          </div>

          <div>
            <label className="label">Environment</label>
            <div className="relative">
              <select className="input-field pr-8 appearance-none" value={env}
                      onChange={e => { setEnv(e.target.value); setConfirming(false); setError('') }}>
                {targets.map(t => (
                  <option key={t.env} value={t.env} disabled={!t.ready}>
                    {t.label}{t.ready ? '' : ' (not ready)'}
                  </option>
                ))}
              </select>
              <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
            </div>
            {current && (
              <p className="text-[11px] ds-u-color--muted mt-1">
                <code className="break-all">{current.enc_path}</code> ({current.secret_count} secret
                {current.secret_count === 1 ? '' : 's'})
              </p>
            )}
          </div>

          {current?.ready === false && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2 text-xs">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{current.label} isn&apos;t ready yet{current.reason ? `: ${current.reason}` : ''}. This target is disabled until then.</span>
            </div>
          )}

          <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-3">
            <p className="text-xs font-medium text-gray-900 dark:text-gray-100">
              Request the token from JFrog
            </p>
            <p className="text-[11px] ds-u-color--muted mt-0.5">
              Uses the refresh token from 1Password and the credential already in the
              secret, so there is nothing to paste. Fall back to the fields below only
              if JFrog refuses the refresh.
            </p>
            <button
              onClick={handleRequest}
              disabled={!ready || running}
              className="btn-primary w-full mt-2 disabled:opacity-50"
            >
              {running ? 'Requesting…' : 'Request and rotate'}
            </button>
          </div>

          <div>
            <label className="label">JFrog username</label>
            <input className="input-field" value={username} autoComplete="off"
                   onChange={e => { setUsername(e.target.value); setConfirming(false) }} />
          </div>

          <div>
            <label className="label">JFrog password</label>
            <input type="password" className="input-field" value={password} autoComplete="new-password"
                   onChange={e => { setPassword(e.target.value); setConfirming(false) }} />
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}

          {confirming ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-3 space-y-2">
              <p className="text-sm text-rose-800 flex items-center gap-1.5">
                <AlertTriangle size={15} /> Rotate the <strong>production</strong> pull credentials?
              </p>
              <p className="text-[11px] text-rose-600">
                Rewrites the production SOPS secret and commits it to the maintenance branch. Anything that
                pulls with these credentials breaks if the credential is wrong.
              </p>
              <div className="flex gap-2">
                <button onClick={() => setConfirming(false)} className="btn-secondary flex-1 flex items-center justify-center gap-1">
                  <ChevronLeft size={14} /> Back
                </button>
                <button onClick={handleRun} disabled={!canSubmit}
                        className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50">
                  {running ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                  Confirm rotate
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-3 pt-1">
              <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
              <button onClick={() => (env === 'prod' ? setConfirming(true) : handleRun())} disabled={!canSubmit}
                      className="btn-primary flex-1 flex items-center justify-center gap-2">
                {running && <Loader2 size={15} className="animate-spin" />}
                {running ? 'Rotating…' : env === 'prod' ? 'Review prod change' : `Rotate ${current?.label ?? env}`}
              </button>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
