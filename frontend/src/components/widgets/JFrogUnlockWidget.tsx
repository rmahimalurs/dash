import { useState, FormEvent } from 'react'
import { LockKeyholeOpen, Loader2, CheckCircle, AlertTriangle, ChevronDown, Info } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { unlockJFrogUser, type JFrogUnlockResult, apiErrorMessage } from '../../api/client'

export default function JFrogUnlockWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<LockKeyholeOpen size={20} className="text-white" />}
        label="Unlock Artifactory User"
        description="Clear a locked-out Artifactory account"
        color="bg-orange-500"
        onClick={() => setOpen(true)}
      />
      <JFrogUnlockModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function JFrogUnlockModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<'dev' | 'prod'>('prod')
  const [username, setUsername] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<JFrogUnlockResult | null>(null)
  const [error, setError] = useState('')

  function handleClose() {
    setEnv('prod')
    setUsername('')
    setSubmitting(false)
    setResult(null)
    setError('')
    onClose()
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setResult(null)
    if (!username.trim()) { setError('Enter a username.'); return }
    setSubmitting(true)
    try {
      const r = await unlockJFrogUser(env, username.trim())
      setResult(r)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Unlock request failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Unlock Artifactory User">
      {result ? (
        <div className="text-center space-y-4 py-4">
          <div className="w-14 h-14 bg-green-100 rounded-full flex items-center justify-center mx-auto">
            <CheckCircle size={28} className="text-green-600" />
          </div>
          <div>
            <p className="font-semibold text-gray-900 dark:text-gray-100">Unlock processed</p>
            <p className="text-sm ds-u-color--muted mt-1">
              Artifactory <span className="font-medium">{result.env}</span> user{' '}
              <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{result.username}</code> has been unlocked.
            </p>
          </div>
          <button onClick={handleClose} className="btn-secondary w-full">Close</button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="label">Target environment</label>
            <div className="relative">
              <select
                className="input-field pr-8 appearance-none"
                value={env}
                onChange={e => setEnv(e.target.value as 'dev' | 'prod')}
              >
                <option value="prod">Prod (artifactory.cloud.cms.gov)</option>
                <option value="dev">Dev (artifactory-dev.cloud.cms.gov)</option>
              </select>
              <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
            </div>
          </div>

          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 flex items-start gap-2">
            <Info size={13} className="flex-shrink-0 mt-0.5" />
            <span>
              Calls <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">unlockUsers</code> on the Artifactory security API with the admin token. Idempotent — safe to run on an account that isn't locked.
            </span>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label className="label">Username</label>
            <input
              type="text"
              className="input-field font-mono"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="oeda-eppe-jfrog-rw"
              autoComplete="off"
              autoFocus
              required
            />
          </div>

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button
              type="submit"
              disabled={submitting || !username.trim()}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
            >
              {submitting && <Loader2 size={15} className="animate-spin" />}
              {submitting ? 'Unlocking…' : 'Unlock'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
