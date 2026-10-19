import { useState } from 'react'
import { Loader2, CheckCircle, AlertTriangle, Eye, EyeOff } from 'lucide-react'
import { type RotateResult, type RotateOptions, apiErrorMessage } from '../../api/client'

/**
 * Full service-account rotation form: generate (or enter) a password, reset the
 * AD account, optionally save to 1Password, then update the tool. Reused by the
 * JFrog and CloudBees password widgets.
 */
export default function RotationPanel({ account, toolLabel, onRotate, onClose }: {
  account: string
  toolLabel: string
  onRotate: (opts: RotateOptions) => Promise<RotateResult>
  onClose: () => void
}) {
  const [generate, setGenerate] = useState(true)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [saveToOP, setSaveToOP] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<RotateResult | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  async function submit() {
    setError('')
    if (!generate) {
      if (password !== confirm) { setError('Passwords do not match.'); return }
      if (password.length < 12) { setError('Password must be at least 12 characters.'); return }
    }
    setSubmitting(true)
    try {
      setResult(await onRotate({ password: generate ? undefined : password, generate, save_to_1password: saveToOP }))
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Rotation failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    const partial = result.status === 'partial'
    const verifyFailed = partial && result.verified === false
    const title = verifyFailed
      ? 'Verification failed, tool not updated'
      : partial ? 'Rotated in AD, tool update failed' : 'Rotation complete'
    const message = verifyFailed
      ? 'was reset in AD and saved to 1Password, but the new password failed LDAP verification, so the tool was NOT updated. Re-run once resolved.'
      : partial
        ? 'was reset in AD, saved to 1Password, and verified, but the tool update failed. Re-run to finish.'
        : `was reset in AD, verified over LDAP, and ${toolLabel} was updated.`
    return (
      <div className="space-y-4 py-2">
        <div className="flex items-start gap-3">
          <div className={`w-11 h-11 rounded-full flex items-center justify-center flex-shrink-0 ${partial ? 'bg-amber-100' : 'bg-green-100'}`}>
            {partial ? <AlertTriangle size={22} className="text-amber-600" /> : <CheckCircle size={22} className="text-green-600" />}
          </div>
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">{title}</p>
            <p className="text-sm ds-u-color--muted mt-0.5">
              <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{result.account}</code>{' '}
              {message}
            </p>
          </div>
        </div>

        {/* LDAP verification outcome */}
        {result.test && (
          result.verified
            ? <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 flex items-start gap-1.5"><CheckCircle size={13} className="flex-shrink-0 mt-0.5" /> New password verified over LDAP.</p>
            : <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 break-words">LDAP verification failed: {result.test.message}</p>
        )}

        {result.generated_password && (
          <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg px-3 py-2.5">
            <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-1">Generated password (shown once — copy it now)</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs font-mono bg-white dark:bg-gray-800 border border-amber-200 dark:border-amber-700 rounded px-2 py-1 break-all">{result.generated_password}</code>
              <button type="button" onClick={() => { navigator.clipboard.writeText(result.generated_password || ''); setCopied(true) }}
                className="text-xs px-2 py-1 rounded bg-amber-100 dark:bg-amber-800/40 text-amber-800 dark:text-amber-300 font-semibold hover:bg-amber-200">
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        )}

        {result.onepassword && (
          result.onepassword.error
            ? <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">1Password not updated: {result.onepassword.error}</p>
            : <p className="text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">1Password {result.onepassword.action} — <span className="font-mono">{result.onepassword.title}</span> in {result.onepassword.vault}</p>
        )}

        {result.tool_error && (
          <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 break-words">Tool update error: {result.tool_error}</p>
        )}

        <button onClick={onClose} className="btn-secondary w-full">Close</button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded-lg px-3 py-2.5 text-xs text-red-800 dark:text-red-300">
        <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
        <span>
          Full rotation <strong>resets the AD password</strong> for <code className="bg-red-100 dark:bg-red-800/40 px-1 rounded">{account}</code>,
          {saveToOP ? ' saves it to 1Password,' : ''} verifies it over LDAP, then updates {toolLabel} only if the check passes.
          This changes the live service-account password.
        </span>
      </div>

      <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer select-none">
        <input type="checkbox" checked={generate} onChange={e => setGenerate(e.target.checked)} className="rounded border-gray-300" />
        Auto-generate a strong password
      </label>

      {!generate && (
        <>
          <div>
            <label className="label">New password</label>
            <div className="relative">
              <input type={showPw ? 'text' : 'password'} className="input-field pr-10" value={password}
                onChange={e => setPassword(e.target.value)} autoComplete="new-password" />
              <button type="button" onClick={() => setShowPw(v => !v)} tabIndex={-1}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted hover:text-gray-600">
                {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>
          <div>
            <label className="label">Confirm password</label>
            <input type={showPw ? 'text' : 'password'} className="input-field" value={confirm}
              onChange={e => setConfirm(e.target.value)} autoComplete="new-password" />
          </div>
        </>
      )}

      <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer select-none">
        <input type="checkbox" checked={saveToOP} onChange={e => setSaveToOP(e.target.checked)} className="rounded border-gray-300" />
        Save / update in 1Password (match by username, else create in DevOps vault)
      </label>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
          <AlertTriangle size={14} className="flex-shrink-0" /> {error}
        </div>
      )}

      <div className="flex gap-3 pt-1">
        <button type="button" onClick={onClose} className="btn-secondary flex-1">Cancel</button>
        <button type="button" onClick={submit} disabled={submitting || (!generate && (!password || !confirm))}
          className="btn-primary flex-1 flex items-center justify-center gap-2">
          {submitting && <Loader2 size={15} className="animate-spin" />}
          {submitting ? 'Rotating…' : 'Rotate'}
        </button>
      </div>
    </div>
  )
}
