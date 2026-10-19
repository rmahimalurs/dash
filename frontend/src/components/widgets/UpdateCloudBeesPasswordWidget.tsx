import { useState, useEffect } from 'react'
import { KeyRound, Loader2, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import RotationPanel from './RotationPanel'
import {
  getCloudBeesEnvs,
  getCloudBeesAccount,
  rotateCloudBeesAccount,
  type CloudBeesEnv,
  type CloudBeesAccountInfo, apiErrorMessage } from '../../api/client'


export default function UpdateCloudBeesPasswordWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<KeyRound size={20} className="text-white" />}
        label="CBJ Svc Account Password"
        description="Rotate the LDAP manager password (4 CJOCs)"
        color="bg-blue-600"
        onClick={() => setOpen(true)}
      />
      <CloudBeesPasswordModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function CloudBeesPasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [envs, setEnvs] = useState<CloudBeesEnv[]>([])
  const [env, setEnv] = useState<string>('')
  const [account, setAccount] = useState<CloudBeesAccountInfo | null>(null)
  const [accountLoading, setAccountLoading] = useState(false)
  const [error, setError] = useState('')

  // Load env list once
  useEffect(() => {
    if (!open) return
    getCloudBeesEnvs()
      .then(list => {
        setEnvs(list)
        if (list.length > 0 && !env) setEnv(list[0].key)
      })
      .catch(() => setError('Could not load environment list.'))
  }, [open])

  // Fetch the account whenever env changes
  useEffect(() => {
    if (!open || !env) return
    setAccountLoading(true)
    setAccount(null)
    getCloudBeesAccount(env)
      .then(setAccount)
      .catch((e: any) => {
        setAccount({
          account: null,
          ldap_url: null,
          error: apiErrorMessage(e, 'Could not discover account.'),
        })
      })
      .finally(() => setAccountLoading(false))
  }, [open, env])

  function handleClose() {
    setEnv(envs[0]?.key || '')
    setAccount(null)
    setError('')
    onClose()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Rotate CloudBees Service Account">
      <div className="space-y-5">
        {/* Env picker */}
        <div>
          <label className="label">Target environment</label>
          <div className="relative">
            <select
              className="input-field pr-8 appearance-none"
              value={env}
              onChange={e => setEnv(e.target.value)}
              disabled={envs.length === 0}
            >
              {envs.map(e => (
                <option key={e.key} value={e.key}>{e.label}</option>
              ))}
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 space-y-2">
          <p className="flex items-center gap-2">
            <span className="font-semibold">Account:</span>
            {accountLoading && <Loader2 size={11} className="animate-spin" />}
            {!accountLoading && account?.account && (
              <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">{account.account}</code>
            )}
            {!accountLoading && !account?.account && (
              <span className="text-amber-700 dark:text-amber-400">(could not discover)</span>
            )}
          </p>
          {account?.account_full && account.account_full !== account.account && (
            <p className="text-[10px] text-blue-700 dark:text-blue-300 break-all">DN: {account.account_full}</p>
          )}
          {account?.ldap_url && (
            <p className="text-[10px] text-blue-700 dark:text-blue-300 break-all">LDAP: {account.ldap_url}</p>
          )}
          {account?.error && (
            <p className="text-[11px] text-amber-700 dark:text-amber-400">{account.error}</p>
          )}
          <p><span className="font-semibold">Process:</span> reset the AD password &rarr; save to 1Password &rarr; verify over LDAP &rarr; update the <strong>{env}</strong> CJOC only if the check passes.</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            {error}
          </div>
        )}

        <RotationPanel
          account={account?.account || env}
          toolLabel={`the ${env} CJOC LDAP manager password`}
          onRotate={(opts) => rotateCloudBeesAccount(env, opts)}
          onClose={handleClose}
        />
      </div>
    </Modal>
  )
}
