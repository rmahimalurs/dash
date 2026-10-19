import { useState, useEffect } from 'react'
import { FileText, ExternalLink, Loader2, XCircle, Lock, CheckCircle, AlertCircle } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { useAuth } from '../../App'
import {
  getRetroPreview,
  createMaintenanceRetroPage,
  type RetroPreviewSection,
  type RetroCreateResult, apiErrorMessage } from '../../api/client'


export default function MaintRetroWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<FileText size={20} className="text-white" />}
        label="Maintenance Retro"
        description="Create Confluence retro page for the latest maintenance"
        color="bg-indigo-600"
        onClick={() => setOpen(true)}
      />
      <MaintRetroModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function MaintRetroModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const isAuthorized = !!user?.jira_authorized
  const [preview, setPreview] = useState<RetroPreviewSection | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<RetroCreateResult | null>(null)

  useEffect(() => {
    if (!open || !isAuthorized) return
    setLoading(true)
    setError('')
    setResult(null)
    setPreview(null)
    getRetroPreview()
      .then(data => {
        if (data.maintenance.error) setError(data.maintenance.error)
        else setPreview(data.maintenance)
      })
      .catch(e => setError(apiErrorMessage(e, 'Could not look up latest maintenance.')))
      .finally(() => setLoading(false))
  }, [open, isAuthorized])

  async function handleCreate() {
    setError('')
    setCreating(true)
    try {
      const res = await createMaintenanceRetroPage()
      setResult(res)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to create retro page.'))
    } finally {
      setCreating(false)
    }
  }

  function handleDismiss() {
    setPreview(null)
    setResult(null)
    setError('')
    onClose()
  }

  return (
    <Modal open={open} onClose={handleDismiss} title="Create Maintenance Retro Page">
      {!isAuthorized ? (
        <RestrictedNotice onClose={handleDismiss} />
      ) : result ? (
        <ResultPanel result={result} onClose={handleDismiss} kind="maintenance" />
      ) : (
        <div className="space-y-4">
          {loading && (
            <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" /> Looking up latest maintenance date…
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <XCircle size={14} className="flex-shrink-0" /> {error}
            </div>
          )}
          {preview && (
            <>
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 space-y-1">
                <p className="text-xs ds-u-color--muted">Page title</p>
                <p className="text-sm font-semibold text-gray-800">{preview.title}</p>
                <p className="text-xs ds-u-color--muted pt-1">
                  Maintenance date: <span className="font-mono">{preview.date}</span>
                </p>
              </div>

              {preview.already_exists && preview.existing_url && (
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-sm text-amber-800">
                  <AlertCircle size={15} className="flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold">Page already exists.</p>
                    <a
                      href={preview.existing_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-amber-900 hover:underline"
                    >
                      Open existing page <ExternalLink size={11} />
                    </a>
                  </div>
                </div>
              )}

              <div className="rounded-lg bg-blue-50 border border-blue-100 px-3 py-2 text-xs text-blue-800 space-y-1">
                <p className="font-semibold">This will:</p>
                <ul className="list-disc list-inside space-y-0.5 text-blue-700">
                  <li>Create a child page under <em>Maintenance Retros</em></li>
                  <li>Use the standard retro template (tasks + 4-column table)</li>
                  <li>Add a row to the parent page's listing table</li>
                </ul>
              </div>

              <div className="flex gap-3 pt-1">
                <button onClick={handleDismiss} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleCreate}
                  disabled={creating || preview.already_exists}
                  className="btn-primary flex-1 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
                >
                  {creating && <Loader2 size={14} className="animate-spin" />}
                  Create Page
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}


function RestrictedNotice({ onClose }: { onClose: () => void }) {
  return (
    <div className="text-center space-y-4 py-6">
      <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
        <Lock size={24} className="ds-u-color--muted" />
      </div>
      <div>
        <p className="font-semibold text-gray-800">Restricted Action</p>
        <p className="text-sm ds-u-color--muted mt-1">
          Retro page creation is restricted to authorized users.
        </p>
      </div>
      <button onClick={onClose} className="btn-secondary">Close</button>
    </div>
  )
}


function ResultPanel({
  result,
  onClose,
  kind,
}: {
  result: RetroCreateResult
  onClose: () => void
  kind: 'maintenance' | 'sprint'
}) {
  const wasAlready = result.already_existed
  return (
    <div className="space-y-4 py-1">
      <div className={`flex items-start gap-3 rounded-lg p-4 border ${
        wasAlready ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'
      }`}>
        {wasAlready ? (
          <AlertCircle size={20} className="text-amber-600 flex-shrink-0 mt-0.5" />
        ) : (
          <CheckCircle size={20} className="text-green-600 flex-shrink-0 mt-0.5" />
        )}
        <div>
          <p className={`text-sm font-semibold ${wasAlready ? 'text-amber-800' : 'text-green-800'}`}>
            {wasAlready ? 'Page already exists.' : `${kind === 'maintenance' ? 'Maintenance' : 'Sprint'} retro page created.`}
          </p>
          <p className={`text-sm mt-0.5 ${wasAlready ? 'text-amber-700' : 'text-green-700'}`}>
            {result.title}
          </p>
        </div>
      </div>
      <a
        href={result.url}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-2 text-sm text-cms-blue hover:underline"
      >
        Open page <ExternalLink size={13} />
      </a>
      <button onClick={onClose} className="btn-secondary w-full">Done</button>
    </div>
  )
}

export { ResultPanel, RestrictedNotice }
