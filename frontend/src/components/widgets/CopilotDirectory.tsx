import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilot,
  getGitHubCopilotUsageAdoption,
  type GitHubCopilot,
  type GitHubCopilotUsageAdoption,
} from '../../api/client'

export default function CopilotDirectory() {
  const [copilot, setCopilot] = useState<GitHubCopilot | null>(null)
  const [usage, setUsage] = useState<GitHubCopilotUsageAdoption | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [cp, ua] = await Promise.all([getGitHubCopilot(), getGitHubCopilotUsageAdoption()])
      setCopilot(cp)
      setUsage(ua)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read the directory.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !copilot) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading the directory…
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

  return (
    <div className="space-y-6">
      <div>
        <h4 className="text-xs font-semibold ds-u-color--muted mb-2">Organizations</h4>
        {copilot && !copilot.error && copilot.by_org.length > 0 ? (
          <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                  <th className="text-left px-3 py-2 font-medium">Organization</th>
                  <th className="text-left px-3 py-2 font-medium">Seats</th>
                  <th className="text-left px-3 py-2 font-medium">Using it</th>
                  <th className="text-left px-3 py-2 font-medium">Idle {copilot.idle_days_threshold}d+</th>
                  <th className="text-left px-3 py-2 font-medium">Never used</th>
                </tr>
              </thead>
              <tbody>
                {copilot.by_org.map((o, i) => (
                  <tr key={o.organization} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{o.organization}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">{o.seats}</td>
                    <td className="px-3 py-2 text-xs">
                      <span className={o.active_pct >= 75 ? 'text-green-700' : 'text-amber-700'}>
                        {o.active} ({o.active_pct}%)
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{o.idle || '—'}</td>
                    <td className="px-3 py-2 text-xs">
                      {o.never_used ? <span className="text-red-600">{o.never_used}</span> : <span className="ds-u-color--muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs ds-u-color--muted">No organization breakdown available.</p>
        )}
      </div>

      <div>
        <h4 className="text-xs font-semibold ds-u-color--muted mb-2">Languages</h4>
        {usage && !usage.error && usage.by_language.length > 0 ? (
          <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                  <th className="text-left px-3 py-2 font-medium">Language</th>
                  <th className="text-left px-3 py-2 font-medium">Generations</th>
                  <th className="text-left px-3 py-2 font-medium">Acceptances</th>
                  <th className="text-left px-3 py-2 font-medium">Lines added</th>
                  <th className="text-left px-3 py-2 font-medium" title="Lines added / lines suggested. Can read far over 100% for languages mostly touched by agent edits, since those write lines directly rather than through a suggest-then-accept flow.">
                    Line acceptance rate
                  </th>
                </tr>
              </thead>
              <tbody>
                {usage.by_language.slice(0, 20).map((row, i) => (
                  <tr key={row.language} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{row.language}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{row.generations.toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{row.acceptances.toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{row.lines_added.toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">
                      {row.lines_suggested ? `${(row.lines_added / row.lines_suggested * 100).toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {usage.by_language.length > 20 && (
              <p className="px-3 py-1.5 text-[11px] ds-u-color--muted border-t border-gray-100 dark:border-gray-700">
                Showing the top 20 of {usage.by_language.length} languages.
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs ds-u-color--muted">No language breakdown available.</p>
        )}
      </div>

      <p className="text-[11px] ds-u-color--muted">
        No per-team directory: every seat in this enterprise is assigned directly to a person rather than
        through a GitHub team, so a "team that assigned the seat" breakdown would show everyone as
        unassigned. For a per-developer directory, see the People tab.
      </p>
    </div>
  )
}
