import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilot,
  getGitHubLicenses,
  type GitHubCopilot,
  type GitHubLicenses,
} from '../../api/client'
import EnterpriseLicenses from './EnterpriseLicenses'
import CopilotAiCredits from './CopilotAiCredits'
import CopilotSpend from './CopilotSpend'
import CopilotUsageAdoption from './CopilotUsageAdoption'
import CopilotPeople from './CopilotPeople'
import CopilotDirectory from './CopilotDirectory'

type ViewId = 'licenses' | 'credits' | 'spend' | 'usage' | 'people' | 'directory'

const VIEWS: { id: ViewId; label: string }[] = [
  { id: 'licenses', label: 'Licenses & Seats' },
  { id: 'credits', label: 'AI Credits' },
  { id: 'spend', label: 'Spend & Budget' },
  { id: 'usage', label: 'Usage & Adoption' },
  { id: 'people', label: 'People' },
  { id: 'directory', label: 'Directory' },
]

function LicensesView() {
  const [copilot, setCopilot] = useState<GitHubCopilot | null>(null)
  const [licenses, setLicenses] = useState<GitHubLicenses | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [cp, lic] = await Promise.all([getGitHubCopilot(), getGitHubLicenses()])
      setCopilot(cp); setLicenses(lic)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read licenses and seats.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !copilot && !licenses) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading licenses and seats…
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" /> {error}
      </div>
    )
  }
  return <EnterpriseLicenses copilot={copilot} licenses={licenses} />
}

/** Copilot usage, licenses and spend across the enterprise.
 *
 *  Nested one level inside the GitHub page's tabs, so the view picker is a
 *  segmented control rather than a second row of underlined tabs. Each view
 *  loads its own data when it is first opened; the heavier reports are cached
 *  server-side and shared, so moving between them does not refetch.
 */
export default function CopilotAnalytics() {
  const [view, setView] = useState<ViewId>('licenses')

  return (
    <div className="space-y-4">
      <div className="inline-flex flex-wrap gap-1 rounded-lg bg-gray-100 dark:bg-gray-800 p-1">
        {VIEWS.map(v => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-colors ${
              view === v.id
                ? 'bg-white dark:bg-gray-700 text-cms-blue shadow-sm'
                : 'ds-u-color--muted hover:text-gray-800 dark:hover:text-gray-200'
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div>
        {view === 'licenses' && <LicensesView />}
        {view === 'credits' && <CopilotAiCredits />}
        {view === 'spend' && <CopilotSpend />}
        {view === 'usage' && <CopilotUsageAdoption />}
        {view === 'people' && <CopilotPeople />}
        {view === 'directory' && <CopilotDirectory />}
      </div>
    </div>
  )
}
