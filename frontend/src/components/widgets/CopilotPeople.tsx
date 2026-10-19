import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Download, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotPeople,
  type GitHubCopilotPeople,
} from '../../api/client'
import { downloadCsv } from '../../utils/csv'
import CopilotPersonDetail from './CopilotPersonDetail'

export default function CopilotPeople() {
  const [data, setData] = useState<GitHubCopilotPeople | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await getGitHubCopilotPeople())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read per-person Copilot activity.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading the per-person usage report…
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

  function exportCsv() {
    if (!data) return
    downloadCsv(
      `copilot-people-${data.enterprise}.csv`,
      ['User', 'Interactions', 'Generations', 'Acceptances', 'Acceptance rate %', 'Lines added', 'Lines suggested', 'Line acceptance rate %', 'Active days', 'AI credits used', 'Top model', 'All models used'],
      data.people.map(p => [p.login, p.interactions, p.generations, p.acceptances, p.acceptance_rate, p.lines_added, p.lines_suggested, p.line_acceptance_rate, p.active_days, p.ai_credits_used, p.top_model, p.models_used.join('; ')]),
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs ds-u-color--muted">
          {data.report_start_day} to {data.report_end_day} · {data.total_users.toLocaleString()} people with
          activity, most active first (showing top {data.people.length}), {data.total_ai_credits_used.toLocaleString()}{' '}
          AI credits used in total. This app's own aggregation of GitHub's per-user 28-day report — not a
          reproduction of any other tool's numbers.{' '}
          <span title="GitHub's ai_credits_used field runs at a much finer granularity than the $-denominated budgets on the Spend & Budget tab (one person at their $39 cap shows thousands of these credits) — they are not the same scale, so this column isn't a % of that budget.">
            AI credits here use GitHub's own units, which don't line up 1:1 with the dollar budgets on Spend &amp; Budget.
          </span>
        </p>
        <button onClick={exportCsv} className="flex-shrink-0 inline-flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-gray-800">
          <Download size={12} /> Export
        </button>
      </div>

      <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
              <th className="text-left px-3 py-2 font-medium">User</th>
              <th className="text-left px-3 py-2 font-medium">Model</th>
              <th className="text-left px-3 py-2 font-medium">Interactions</th>
              <th className="text-left px-3 py-2 font-medium">Generations</th>
              <th className="text-left px-3 py-2 font-medium">Acceptances</th>
              <th className="text-left px-3 py-2 font-medium">Acceptance rate</th>
              <th className="text-left px-3 py-2 font-medium">Lines added</th>
              <th className="text-left px-3 py-2 font-medium" title="Lines added / lines suggested. Can read over 100% for people whose usage is mostly chat or agent edits, since those write lines directly rather than through a suggest-then-accept flow.">
                Line acceptance rate
              </th>
              <th className="text-left px-3 py-2 font-medium">Active days</th>
              <th className="text-left px-3 py-2 font-medium">AI credits used</th>
            </tr>
          </thead>
          <tbody>
            {data.people.map((p, i) => (
              <tr
                key={p.login}
                onClick={() => setSelected(p.login)}
                className={`cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 ${i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}`}
              >
                <td className="px-3 py-2 text-xs font-medium text-cms-blue hover:underline">{p.login}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted" title={p.models_used.join(', ')}>
                  {p.top_model ?? '—'}
                  {p.models_used.length > 1 && <span className="ml-1 text-[10px]">+{p.models_used.length - 1}</span>}
                </td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.interactions.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.generations.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.acceptances.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.acceptance_rate !== null ? `${p.acceptance_rate}%` : '—'}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.lines_added.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.line_acceptance_rate !== null ? `${p.line_acceptance_rate}%` : '—'}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.active_days}</td>
                <td className="px-3 py-2 text-xs ds-u-color--muted">{p.ai_credits_used.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <CopilotPersonDetail login={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
