import { useEffect, useState } from 'react'
import { Loader2, Sparkles, X } from 'lucide-react'
import { acknowledgeWhatsNew, getWhatsNew, type WhatsNew } from '../../api/client'

/**
 * Shows the current release's highlights once per user, per release.
 *
 * The acknowledgment is stored server-side against the user's profile rather
 * than in localStorage, so dismissing it follows the engineer across browsers
 * and a new release brings it back on its own.
 */
export default function WhatsNewModal() {
  const [data, setData] = useState<WhatsNew | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    getWhatsNew()
      .then(d => {
        if (cancelled) return
        setData(d)
        if (!d.acknowledged) setOpen(true)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function dismiss() {
    if (!data) return
    setSaving(true)
    try {
      await acknowledgeWhatsNew(data.version)
    } catch {
      // A failed ack only means the popup returns next load; never trap the user.
    } finally {
      setSaving(false)
      setOpen(false)
    }
  }

  if (!open || !data) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-gray-100 dark:border-gray-700">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-full bg-cms-blue-light flex items-center justify-center">
              <Sparkles size={15} className="text-cms-blue" />
            </span>
            <div>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                What&apos;s new in {data.version}
              </p>
              <p className="text-xs ds-u-color--muted mt-0.5">
                {data.title} &middot; {data.date}
              </p>
            </div>
          </div>
          <button
            onClick={dismiss}
            aria-label="Dismiss"
            className="p-1 rounded ds-u-color--muted hover:text-gray-600 dark:hover:text-gray-200"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 overflow-y-auto space-y-4">
          {data.highlights.map((h, i) => (
            <div key={i} className="flex gap-3">
              <span className="flex-shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full bg-cms-blue" />
              <div>
                <p className="text-sm font-medium text-gray-800 dark:text-gray-100">{h.title}</p>
                <p className="text-xs ds-u-color--muted mt-0.5 leading-relaxed">{h.body}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="px-5 py-3.5 border-t border-gray-100 dark:border-gray-700 flex items-center justify-between gap-3">
          <p className="text-[11px] ds-u-color--muted">
            You will see this again after the next release.
          </p>
          <button
            onClick={dismiss}
            disabled={saving}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}
