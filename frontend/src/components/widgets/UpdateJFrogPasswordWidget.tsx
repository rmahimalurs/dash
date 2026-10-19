import { useState } from 'react'
import { KeyRound, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import RotationPanel from './RotationPanel'
import { rotateJFrogAccount } from '../../api/client'

const ACCOUNTS: Record<'dev' | 'prod', string> = {
  prod: 'jfrog-svc-prod',
  dev:  'dso-ss-jfrog-dev',
}


export default function UpdateJFrogPasswordWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<KeyRound size={20} className="text-white" />}
        label="JFrog Svc Account Password"
        description="Rotate the service-account password (dev or prod)"
        color="bg-orange-500"
        onClick={() => setOpen(true)}
      />
      <JFrogPasswordModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function JFrogPasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [env, setEnv] = useState<'dev' | 'prod'>('dev')

  function handleClose() {
    setEnv('dev')
    onClose()
  }

  const account = ACCOUNTS[env]

  return (
    <Modal open={open} onClose={handleClose} title="Rotate JFrog Service Account">
      <div className="space-y-5">
        {/* Env picker */}
        <div>
          <label className="label">Target environment</label>
          <div className="relative">
            <select
              className="input-field pr-8 appearance-none"
              value={env}
              onChange={e => setEnv(e.target.value as 'dev' | 'prod')}
            >
              <option value="dev">Dev (dso-ss-jfrog-dev)</option>
              <option value="prod">Prod (jfrog-svc-prod)</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 space-y-1">
          <p><span className="font-semibold">Account:</span> <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">{account}</code></p>
          <p><span className="font-semibold">Process:</span> reset the AD password &rarr; save to 1Password &rarr; verify the new password over LDAP &rarr; update Artifactory <strong>{env}</strong> via the Access API.</p>
        </div>

        <RotationPanel
          account={account}
          toolLabel="Artifactory's LDAP manager password"
          onRotate={(opts) => rotateJFrogAccount(env, opts)}
          onClose={handleClose}
        />
      </div>
    </Modal>
  )
}
