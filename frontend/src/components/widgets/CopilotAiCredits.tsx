import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Download, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotPeople,
  getGitHubCopilotPowerUsers,
  type GitHubCopilotPeople,
  type GitHubCopilotPowerUsers,
} from '../../api/client'
import { downloadCsv } from '../../utils/csv'
import { StatTile } from './StatTile'

function activityLabel(u: { has_seat: boolean; never_used: boolean; idle_days: number | null }) {
  if (!u.has_seat) return { text: 'no Copilot seat', tone: 'text-red-600 font-medium' }
  if (u.never_used) return { text: 'never used', tone: 'text-red-600 font-medium' }
  if (u.idle_days === null) return { text: 'unknown', tone: 'ds-u-color--muted' }
  if (u.idle_days === 0) return { text: 'today', tone: 'text-green-700' }
  return { text: `${u.idle_days}d ago`, tone: u.idle_days >= 30 ? 'text-amber-700' : 'text-gray-600' }
}

export default function CopilotAiCredits() {
  const [power, setPower] = useState<GitHubCopilotPowerUsers | null>(null)
  const [people, setPeople] = useState<GitHubCopilotPeople | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [p, ppl] = await Promise.all([getGitHubCopilotPowerUsers(), getGitHubCopilotPeople()])
      setPower(p)
      setPeople(ppl)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read AI-credit budgets.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !power) {
    return (
      <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
        <Loader2 size={15} className="animate-spin" /> Reading AI-credit budgets…
      </div>
    )
  }

  if (error || power?.error) {
    return (
      <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
        <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
        {error || power?.error}
      </div>
    )
  }

  function exportCsv() {
    if (!power) return
    downloadCsv(
      `copilot-ai-credits-${power.enterprise}.csv`,
      ['User', 'Org', 'Credit budget', 'Blocks at cap', 'Credits used', 'Idle days', 'Never used', 'Editor', 'Downgrade candidate'],
      power.users.map(u => [
        u.login, u.organization, u.budget_amount, u.blocks_at_cap ? 'yes' : 'no',
        u.credits_used, u.idle_days, u.never_used ? 'yes' : 'no', u.editor, u.downgrade_candidate ? 'yes' : 'no',
      ]),
    )
  }

  return (
    <div className="space-y-4">
      {people && !people.error && (
        <div>
          <p className="text-xs font-semibold ds-u-color--muted mb-2">Enterprise-wide consumption</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <StatTile label="Total AI credits used" value={people.total_ai_credits_used.toLocaleString()}
                       sub={`${people.report_start_day} to ${people.report_end_day}, GitHub's own units`} />
            <StatTile label="People with recorded usage" value={people.total_users.toLocaleString()} />
          </div>
        </div>
      )}

      {power && power.total > 0 ? (
        <div>
          <p className="text-xs font-semibold ds-u-color--muted mb-2">People with their own explicit budget</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <StatTile label="People with their own budget" value={power.total} />
            <StatTile
              label="Worth a conversation"
              value={power.downgrade_candidates}
              tone={power.downgrade_candidates > 0 ? 'text-amber-600' : 'text-gray-900 dark:text-gray-100'}
              sub="not using Copilot at all"
            />
            {power.pools.length > 0 && (
              <StatTile label="Shared pools" value={power.pools.length}
                         sub={power.pools.map(p => `${p.name} ${p.budget_amount}`).join(', ')} />
            )}
          </div>

          {power.usage_note && (
            <p className="text-[11px] ds-u-color--muted bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-lg px-3 py-2 mt-3">
              {power.usage_note}
            </p>
          )}

          <div className="flex justify-end mt-3">
            <button onClick={exportCsv} className="inline-flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-gray-800">
              <Download size={12} /> Export
            </button>
          </div>

          <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden mt-2">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                  <th className="text-left px-3 py-2 font-medium">User</th>
                  <th className="text-left px-3 py-2 font-medium">Org</th>
                  <th className="text-left px-3 py-2 font-medium">Credit budget</th>
                  <th className="text-left px-3 py-2 font-medium">Credits used</th>
                  <th className="text-left px-3 py-2 font-medium">Last Copilot activity</th>
                  <th className="text-left px-3 py-2 font-medium">Editor</th>
                </tr>
              </thead>
              <tbody>
                {power.users.map((u, i) => {
                  const act = activityLabel(u)
                  return (
                    <tr key={u.login} className={`${i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''} ${u.downgrade_candidate ? 'bg-red-50/40' : ''}`}>
                      <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">
                        {u.login}
                        {u.downgrade_candidate && (
                          <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">review</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs ds-u-color--muted">{u.organization || '—'}</td>
                      <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">
                        {u.budget_amount}
                        {u.blocks_at_cap && <span className="ml-1 text-[10px] ds-u-color--muted">blocks at cap</span>}
                      </td>
                      <td className="px-3 py-2 text-xs ds-u-color--muted">{u.credits_used ?? <span className="ds-u-color--muted">none yet</span>}</td>
                      <td className={`px-3 py-2 text-xs ${act.tone}`}>{act.text}</td>
                      <td className="px-3 py-2 text-xs ds-u-color--muted">{u.editor || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="text-sm ds-u-color--muted">Nobody holds their own explicit AI-credit budget right now.</p>
      )}
    </div>
  )
}
