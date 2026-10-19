import { useState, useEffect } from 'react'
import { FileText, ExternalLink, Loader2, XCircle, AlertCircle } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { useAuth } from '../../App'
import {
  getRetroPreview,
  createSprintRetroPage,
  type RetroPreviewSection,
  type RetroCreateResult, apiErrorMessage } from '../../api/client'
import { ResultPanel, RestrictedNotice } from './MaintRetroWidget'


export default function SprintRetroWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<FileText size={20} className="text-white" />}
        label="Sprint Retro"
        description="Create Confluence retro page for the current sprint"
        color="bg-purple-600"
        onClick={() => setOpen(true)}
      />
      <SprintRetroModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}


function SprintRetroModal({ open, onClose }: { open: boolean; onClose: () => void }) {
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
        if (data.sprint.error) setError(data.sprint.error)
        else setPreview(data.sprint)
      })
      .catch(e => setError(apiErrorMessage(e, 'Could not detect the active DMSC sprint.')))
      .finally(() => setLoading(false))
  }, [open, isAuthorized])

  async function handleCreate() {
    setError('')
    setCreating(true)
    try {
      const res = await createSprintRetroPage()
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
    <Modal open={open} onClose={handleDismiss} title="Create Sprint Retro Page">
      {!isAuthorized ? (
        <RestrictedNotice onClose={handleDismiss} />
      ) : result ? (
        <ResultPanel result={result} onClose={handleDismiss} kind="sprint" />
      ) : (
        <div className="space-y-4">
          {loading && (
            <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
              <Loader2 size={15} className="animate-spin" /> Detecting current DMSC sprint…
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
                  Sprint {preview.sprint_number} ends <span className="font-mono">{preview.end_date}</span>
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
                  <li>Create a child page under <em>DevOps Sprint Retros</em></li>
                  <li>Use the standard retro template (3-column table + closing notes)</li>
                  <li>Add a row to the parent page's listing table</li>
                </ul>
              </div>

              <div className="flex gap-3 pt-1">
                <button onClick={handleDismiss} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleCreate}
                  disabled={creating || preview.already_exists}
                  className="btn-primary flex-1 flex items-center justify-center gap-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50"
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
