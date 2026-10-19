import { useState, FormEvent } from 'react'
import { LockKeyholeOpen, Lock, ShieldCheck, Loader2, CheckCircle, AlertTriangle, Info, Eye, EyeOff, KeyRound } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  unlockAdAccount,
  resetAdPassword,
  getAdAccountStatus,
  type AdUnlockResult,
  type AdResetResult,
  type AdAccountStatus, apiErrorMessage } from '../../api/client'

type Mode = 'unlock' | 'reset'

export default function ActiveDirectoryUnlockWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<LockKeyholeOpen size={20} className="text-white" />}
        label="Unlock / Reset AD Account"
        description="Clear a lockout or reset an AD account password"
        color="bg-indigo-500"
        onClick={() => setOpen(true)}
      />
      <AdModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function AdModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [mode, setMode] = useState<Mode>('unlock')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [generate, setGenerate] = useState(false)
  const [saveToOP, setSaveToOP] = useState(true)
  const [copied, setCopied] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<AdUnlockResult | AdResetResult | null>(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState<AdAccountStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)

  function handleClose() {
    setMode('unlock')
    setAccount(''); setPassword(''); setConfirm(''); setShowPw(false)
    setGenerate(false); setSaveToOP(true); setCopied(false)
    setSubmitting(false); setResult(null); setError('')
    setStatus(null); setStatusLoading(false)
    onClose()
  }

  function switchMode(m: Mode) {
    setMode(m); setResult(null); setError('')
  }

  // Read-only lockout-status check (single LDAP bind on the backend; safe to call on blur).
  async function checkStatus() {
    const acct = account.trim()
    if (!acct) { setStatus(null); return }
    setStatusLoading(true)
    try {
      setStatus(await getAdAccountStatus(acct))
    } catch {
      setStatus(null)
    } finally {
      setStatusLoading(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(''); setResult(null)
    if (!account.trim()) { setError('Enter an account name.'); return }
    if (mode === 'reset' && !generate) {
      if (password !== confirm) { setError('Passwords do not match.'); return }
      if (password.length < 12) { setError('Password must be at least 12 characters.'); return }
    }
    setSubmitting(true)
    try {
      const r = mode === 'unlock'
        ? await unlockAdAccount(account.trim())
        : await resetAdPassword(account.trim(), {
            password: generate ? undefined : password,
            generate,
            save_to_1password: saveToOP,
          })
      setResult(r)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Request failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  const ok = result && result.status !== 'not_found'
  const resetRes = result as AdResetResult | null

  // In unlock mode, if the checked account is confirmed not locked, there's nothing to do.
  const alreadyUnlocked =
    mode === 'unlock' && !statusLoading &&
    status?.status === 'found' && status.is_locked === false &&
    status.account === account.trim()

  return (
    <Modal open={open} onClose={handleClose} title="Active Directory Account">
      {result ? (
        <div className="text-center space-y-4 py-4">
          <div className={`w-14 h-14 rounded-full flex items-center justify-center mx-auto ${ok ? 'bg-green-100' : 'bg-amber-100'}`}>
            {ok ? <CheckCircle size={28} className="text-green-600" /> : <AlertTriangle size={28} className="text-amber-600" />}
          </div>
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">
              {ok ? (mode === 'unlock' ? 'Unlock processed' : 'Password reset') : 'Account not found'}
            </p>
            <p className="text-sm ds-u-color--muted mt-1">{result.message}</p>
            {result.dn && <p className="text-xs ds-u-color--muted font-mono mt-2 break-all">{result.dn}</p>}
          </div>

          {/* Generated password (shown once) */}
          {ok && resetRes?.generated_password && (
            <div className="text-left bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-lg px-3 py-2.5">
              <p className="text-xs font-semibold text-amber-800 dark:text-amber-300 mb-1">Generated password (shown once — copy it now)</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs font-mono bg-white dark:bg-gray-800 border border-amber-200 dark:border-amber-700 rounded px-2 py-1 break-all">{resetRes.generated_password}</code>
                <button type="button" onClick={() => { navigator.clipboard.writeText(resetRes.generated_password || ''); setCopied(true) }}
                  className="text-xs px-2 py-1 rounded bg-amber-100 dark:bg-amber-800/40 text-amber-800 dark:text-amber-300 font-semibold hover:bg-amber-200">
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>
          )}

          {/* 1Password outcome */}
          {ok && resetRes?.onepassword && (
            resetRes.onepassword.error ? (
              <p className="text-left text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
                1Password not updated: {resetRes.onepassword.error}
              </p>
            ) : (
              <p className="text-left text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
                1Password {resetRes.onepassword.action} — <span className="font-mono">{resetRes.onepassword.title}</span> in {resetRes.onepassword.vault}
              </p>
            )
          )}

          <button onClick={handleClose} className="btn-secondary w-full">Close</button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Mode toggle */}
          <div className="flex rounded-lg bg-gray-100 dark:bg-gray-700 p-1 text-sm font-medium">
            <button type="button" onClick={() => switchMode('unlock')}
              className={`flex-1 py-1.5 rounded-md transition-colors ${mode === 'unlock' ? 'bg-white dark:bg-gray-800 shadow-sm text-cms-blue' : 'ds-u-color--muted'}`}>
              Unlock
            </button>
            <button type="button" onClick={() => switchMode('reset')}
              className={`flex-1 py-1.5 rounded-md transition-colors ${mode === 'reset' ? 'bg-white dark:bg-gray-800 shadow-sm text-cms-blue' : 'ds-u-color--muted'}`}>
              Reset Password
            </button>
          </div>

          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2">
            <Info size={13} className="flex-shrink-0 mt-0.5" />
            <span>
              {mode === 'unlock'
                ? <>Clears the AD lockout (<code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">lockoutTime</code>) via the delegated service account.</>
                : <>Sets a new AD password (<code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">unicodePwd</code>) over LDAPS. Must satisfy the domain password policy (complexity + history).</>}
              {' '}Enter the <strong>sAMAccountName</strong>.
            </span>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="label">Account name (sAMAccountName)</label>
            <input
              type="text" className="input-field font-mono" value={account}
              onChange={e => { setAccount(e.target.value); setStatus(null) }}
              onBlur={checkStatus}
              placeholder="dso-jenkins-sandbox"
              autoComplete="off" autoFocus required
            />

            {/* Current lockout status (read-only pre-check) */}
            {statusLoading && (
              <p className="flex items-center gap-1.5 text-xs ds-u-color--muted mt-2">
                <Loader2 size={12} className="animate-spin" /> Checking lockout status…
              </p>
            )}
            {!statusLoading && status && (
              status.status === 'not_found' ? (
                <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400 mt-2">
                  <AlertTriangle size={12} className="flex-shrink-0" /> Not found in AD
                </p>
              ) : (
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  {status.is_locked ? (
                    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-700">
                      <Lock size={12} /> Locked
                      {typeof status.bad_pwd_count === 'number' && status.bad_pwd_count > 0 && (
                        <span className="font-normal">· {status.bad_pwd_count} bad pwd attempts</span>
                      )}
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-700">
                      <ShieldCheck size={12} /> Not locked
                    </span>
                  )}
                  <PasswordExpiryPill status={status} />
                </div>
              )
            )}
          </div>

          {mode === 'reset' && (
            <>
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer select-none">
                <input type="checkbox" checked={generate} onChange={e => setGenerate(e.target.checked)} className="rounded border-gray-300" />
                Auto-generate a strong password
              </label>

              {!generate && (
                <>
                  <div>
                    <label className="label">New password</label>
                    <div className="relative">
                      <input
                        type={showPw ? 'text' : 'password'} className="input-field pr-10" value={password}
                        onChange={e => setPassword(e.target.value)} autoComplete="new-password" required={!generate}
                      />
                      <button type="button" onClick={() => setShowPw(v => !v)} tabIndex={-1}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted hover:text-gray-600">
                        {showPw ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </div>
                  <div>
                    <label className="label">Confirm password</label>
                    <input
                      type={showPw ? 'text' : 'password'} className="input-field" value={confirm}
                      onChange={e => setConfirm(e.target.value)} autoComplete="new-password" required={!generate}
                    />
                  </div>
                </>
              )}

              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer select-none">
                <input type="checkbox" checked={saveToOP} onChange={e => setSaveToOP(e.target.checked)} className="rounded border-gray-300" />
                Save / update in 1Password (match by username, else create in DevOps vault)
              </label>
            </>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button
              type="submit"
              disabled={submitting || !account.trim() || alreadyUnlocked || (mode === 'reset' && !generate && (!password || !confirm))}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
            >
              {submitting && <Loader2 size={15} className="animate-spin" />}
              {submitting
                ? (mode === 'unlock' ? 'Unlocking…' : 'Resetting…')
                : alreadyUnlocked ? 'Already unlocked' : (mode === 'unlock' ? 'Unlock' : 'Reset Password')}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

// Password-expiry status pill, shown next to the lock pill once an account is
// found. Colour tracks urgency: red = expired, amber = expiring soon, green =
// valid, gray = never expires. Hidden when the state is unknown.
function PasswordExpiryPill({ status }: { status: AdAccountStatus }) {
  const st = status.password_status
  if (!st || st === 'unknown') return null
  const base = 'inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-semibold border'
  const days = status.password_days_remaining

  if (st === 'expired') {
    return (
      <span className={`${base} bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-200 dark:border-red-700`}>
        <KeyRound size={12} /> Password expired
      </span>
    )
  }
  if (st === 'never_expires') {
    return (
      <span className={`${base} bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-600`}>
        <KeyRound size={12} /> Password never expires
      </span>
    )
  }
  if (st === 'critical' || st === 'warning') {
    return (
      <span className={`${base} bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-700`}>
        <KeyRound size={12} /> Password expires in {days}d
      </span>
    )
  }
  return (
    <span className={`${base} bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700`}>
      <KeyRound size={12} /> Password valid{typeof days === 'number' ? ` · ${days}d left` : ''}
    </span>
  )
}
