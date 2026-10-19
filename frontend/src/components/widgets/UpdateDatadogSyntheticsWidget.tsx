import { useState } from 'react'
import { KeyRound, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import RotationPanel from './RotationPanel'
import { rotateDatadogSyntheticsAccount } from '../../api/client'

const ACCOUNTS: Record<'a' | 'b', { account: string; variable: string }> = {
  a: { account: 'dso-synthetics-a', variable: 'DSO_SYNTHETICS_A_PASSWORD' },
  b: { account: 'dso-synthetics-b', variable: 'DSO_SYNTHETICS_B_PASSWORD' },
}


export default function UpdateDatadogSyntheticsWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<KeyRound size={20} className="text-white" />}
        label="Datadog Synthetics Password"
        description="Rotate a synthetics service-account password (a or b)"
        color="bg-purple-600"
        onClick={() => setOpen(true)}
      />
      <DatadogSyntheticsModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function DatadogSyntheticsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [sel, setSel] = useState<'a' | 'b'>('b')

  function handleClose() {
    setSel('b')
    onClose()
  }

  const { account, variable } = ACCOUNTS[sel]

  return (
    <Modal open={open} onClose={handleClose} title="Rotate Datadog Synthetics Service Account">
      <div className="space-y-5">
        {/* Account picker */}
        <div>
          <label className="label">Synthetics account</label>
          <div className="relative">
            <select
              className="input-field pr-8 appearance-none"
              value={sel}
              onChange={e => setSel(e.target.value as 'a' | 'b')}
            >
              <option value="a">dso-synthetics-a (DSO_SYNTHETICS_A_PASSWORD)</option>
              <option value="b">dso-synthetics-b (DSO_SYNTHETICS_B_PASSWORD)</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
          </div>
        </div>

        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg px-3 py-2.5 text-xs text-blue-800 dark:text-blue-300 space-y-1">
          <p><span className="font-semibold">Account:</span> <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">{account}</code></p>
          <p><span className="font-semibold">Process:</span> reset the AD password &rarr; save to 1Password &rarr; verify the new password over LDAP (informational) &rarr; write it into the Datadog global variable <code className="bg-blue-100 dark:bg-blue-800/40 px-1 rounded">{variable}</code> (Synthetic Tests &rsaquo; Global Variables).</p>
        </div>

        <RotationPanel
          account={account}
          toolLabel={`the ${variable} Datadog global variable`}
          onRotate={(opts) => rotateDatadogSyntheticsAccount(sel, opts)}
          onClose={handleClose}
        />
      </div>
    </Modal>
  )
}
