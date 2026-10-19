import { useState, useEffect } from 'react'
import { CheckCircle, ExternalLink, Loader2, XCircle, Lock } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { useAuth } from '../../App'
import { getXocEocPreview, closeItcTicket, apiErrorMessage } from '../../api/client'


export default function CloseItcWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<CheckCircle size={20} className="text-white" />}
        label="Close ITC"
        description="Mark ITC ticket Implemented with completion comment"
        color="bg-green-600"
        onClick={() => setOpen(true)}
      />
      <CloseItcModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function CloseItcModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const isAuthorized = !!user?.jira_authorized
  const [ticket, setTicket] = useState<{ key: string; url: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [closing, setClosing] = useState(false)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [result, setResult] = useState<{ key: string; url: string } | null>(null)

  useEffect(() => {
    if (!open || !isAuthorized) return
    setLoading(true)
    setError('')
    setTicket(null)
    setConfirmed(false)
    setResult(null)
    getXocEocPreview()
      .then(data => setTicket(data.itc))
      .catch(() => setError('Could not look up this month\'s ITC ticket.'))
      .finally(() => setLoading(false))
  }, [open])

  async function handleClose() {
    if (!ticket) return
    setError('')
    setClosing(true)
    try {
      const res = await closeItcTicket(ticket.key)
      setResult(res.ticket)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Failed to close ITC ticket.'))
    } finally {
      setClosing(false)
    }
  }

  function handleDismiss() {
    setResult(null)
    setTicket(null)
    setError('')
    setConfirmed(false)
    onClose()
  }

  return (
    <Modal open={open} onClose={handleDismiss} title="Close ITC Ticket">
      {!isAuthorized ? (
        <div className="text-center space-y-4 py-6">
          <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <Lock size={24} className="ds-u-color--muted" />
          </div>
          <div>
            <p className="font-semibold text-gray-800">Restricted Action</p>
            <p className="text-sm ds-u-color--muted mt-1">
              This action is restricted to Patrick Hendren.
            </p>
          </div>
          <button onClick={handleDismiss} className="btn-secondary">Close</button>
        </div>
      ) : result ? (
        <div className="space-y-4 py-1">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">ITC ticket closed.</p>
              <p className="text-sm text-green-700 mt-0.5">
                Comment added and status transitioned to <strong>Implemented</strong>.
              </p>
            </div>
          </div>
          <a
            href={result.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-cms-blue hover:underline"
          >
            {result.key} <ExternalLink size={13} />
          </a>
          <button onClick={handleDismiss} className="btn-secondary w-full">Done</button>
        </div>
      ) : (
        <div className="space-y-4">
          {loading && (
            <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" /> Looking up this month's ITC ticket…
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <XCircle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}
          {!loading && !error && !ticket && (
            <p className="text-sm ds-u-color--muted">No ITC maintenance ticket found for this month.</p>
          )}
          {ticket && (
            <>
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
                <p className="text-xs ds-u-color--muted mb-1">ITC ticket to close</p>
                <a
                  href={ticket.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-sm font-mono font-medium text-cms-blue hover:underline"
                >
                  {ticket.key} <ExternalLink size={12} />
                </a>
              </div>
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800 space-y-1">
                <p className="font-semibold">This will:</p>
                <ul className="list-disc list-inside space-y-0.5 text-amber-700">
                  <li>Add comment: <em>"Maintenance Successfully Completed"</em></li>
                  <li>Transition ticket to <strong>Implemented</strong></li>
                </ul>
              </div>
              <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-lg px-3 py-3">
                <input
                  type="checkbox"
                  id="itc-confirm"
                  className="mt-0.5 flex-shrink-0 accent-red-600"
                  checked={confirmed}
                  onChange={e => setConfirmed(e.target.checked)}
                />
                <label htmlFor="itc-confirm" className="text-sm text-red-800 cursor-pointer">
                  I confirm maintenance is complete and this ticket should be closed.
                </label>
              </div>
              <div className="flex gap-3 pt-1">
                <button onClick={handleDismiss} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleClose}
                  disabled={!confirmed || closing}
                  className="btn-primary flex-1 flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:opacity-50"
                >
                  {closing && <Loader2 size={14} className="animate-spin" />}
                  Close ITC
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
