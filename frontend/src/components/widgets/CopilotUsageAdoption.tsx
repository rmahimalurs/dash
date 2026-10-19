import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Loader2, TrendingUp } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotUsageAdoption,
  type GitHubCopilotUsageAdoption,
} from '../../api/client'
import { StatTile } from './StatTile'

export default function CopilotUsageAdoption() {
  const [data, setData] = useState<GitHubCopilotUsageAdoption | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await getGitHubCopilotUsageAdoption())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read Copilot usage & adoption.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading the enterprise usage report…
      </div>
    )
  }

  if (error || data?.error) {
    return (
      <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        {error || data?.error}
      </div>
    )
  }

  if (!data) return null

  const maxDau = Math.max(1, ...data.daily_active_users_trend.map(d => d.active_users))

  return (
    <div className="space-y-4">
      <p className="text-xs ds-u-color--muted">
        {data.report_start_day} to {data.report_end_day} · enterprise-wide, from GitHub's own
        28-day Copilot metrics report
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatTile label="Daily active users" value={data.daily_active_users} sub={`as of ${data.latest_day}`} />
        <StatTile label="Weekly active users" value={data.weekly_active_users} />
        <StatTile label="Monthly active users" value={data.monthly_active_users} />
        <StatTile
          label="Acceptance rate"
          value={data.acceptance_rate !== null ? `${data.acceptance_rate}%` : '—'}
          sub={`${data.total_acceptances.toLocaleString()} of ${data.total_generations.toLocaleString()} generations accepted`}
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatTile label="Monthly active chat users" value={data.monthly_active_chat_users} />
        <StatTile label="Monthly active agent users" value={data.monthly_active_agent_users} />
        <StatTile label="Chat interactions" value={data.chat_interactions.toLocaleString()} />
        <StatTile
          label="Chat acceptance rate"
          value={data.chat_acceptance_rate !== null ? `${data.chat_acceptance_rate}%` : '—'}
          sub={`${data.chat_acceptances.toLocaleString()} of ${data.chat_generations.toLocaleString()} chat generations`}
        />
      </div>

      <div>
        <h4 className="text-xs font-semibold ds-u-color--muted mb-2 flex items-center gap-1.5">
          <TrendingUp size={12} /> Daily active users, last {data.daily_active_users_trend.length} days
        </h4>
        <div className="flex items-end gap-0.5 h-20 rounded-lg border border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-800 p-2">
          {data.daily_active_users_trend.map(d => (
            <div key={d.day} className="flex-1 bg-cms-blue/70 hover:bg-cms-blue rounded-t"
                 style={{ height: `${Math.max(4, (d.active_users / maxDau) * 100)}%` }}
                 title={`${d.day}: ${d.active_users} active users`} />
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
              <th className="text-left px-3 py-2 font-medium">IDE / client</th>
              <th className="text-left px-3 py-2 font-medium">Interactions</th>
              <th className="text-left px-3 py-2 font-medium">Generations</th>
              <th className="text-left px-3 py-2 font-medium">Acceptances</th>
              <th className="text-left px-3 py-2 font-medium">Lines added</th>
            </tr>
          </thead>
          <tbody>
            {data.by_ide.map((row, i) => (
              <tr key={row.ide} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{row.ide}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.interactions.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.generations.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.acceptances.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.lines_added.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700 text-xs ds-u-color--muted">
          Which model developers are using for chat and agent requests
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
              <th className="text-left px-3 py-2 font-medium">Model</th>
              <th className="text-left px-3 py-2 font-medium">Interactions</th>
              <th className="text-left px-3 py-2 font-medium">Generations</th>
              <th className="text-left px-3 py-2 font-medium">Acceptances</th>
              <th className="text-left px-3 py-2 font-medium">Lines added</th>
            </tr>
          </thead>
          <tbody>
            {data.by_model.map((row, i) => (
              <tr key={row.model} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{row.model}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.interactions.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.generations.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.acceptances.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.lines_added.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
        <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700 text-xs ds-u-color--muted">
          Which Copilot feature developers are reaching for
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
              <th className="text-left px-3 py-2 font-medium">Feature</th>
              <th className="text-left px-3 py-2 font-medium">Interactions</th>
              <th className="text-left px-3 py-2 font-medium">Generations</th>
              <th className="text-left px-3 py-2 font-medium">Acceptances</th>
            </tr>
          </thead>
          <tbody>
            {data.by_feature.map((row, i) => (
              <tr key={row.feature} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{row.label}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.interactions.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.generations.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{row.acceptances.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
