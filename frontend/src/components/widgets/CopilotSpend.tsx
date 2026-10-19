import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Download, Loader2, Wallet } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotSpend,
  type CopilotBudgetStatus,
  type GitHubCopilotSpend,
} from '../../api/client'
import { downloadCsv } from '../../utils/csv'
import { StatTile } from './StatTile'
import CopilotBillingSpend from './CopilotBillingSpend'

const STATUS: Record<CopilotBudgetStatus, { label: string; badge: string; bar: string }> = {
  over: { label: 'over cap', badge: 'bg-red-100 text-red-700', bar: 'bg-red-500' },
  near: { label: 'near cap', badge: 'bg-amber-100 text-amber-700', bar: 'bg-amber-500' },
  warning: { label: 'watch', badge: 'bg-yellow-100 text-yellow-700', bar: 'bg-yellow-400' },
  healthy: { label: 'healthy', badge: 'bg-green-100 text-green-700', bar: 'bg-green-500' },
  unknown: { label: 'unknown', badge: 'bg-gray-100 text-gray-600', bar: 'bg-gray-300' },
}

function resourceSummary(resources: { type: string; name: string }[]): string {
  if (resources.length === 0) return '—'
  if (resources.length === 1) return resources[0].name
  const first = resources[0]
  return `${first.name} +${resources.length - 1} more`
}

function UsageBar({ row }: { row: GitHubCopilotSpend['cost_centers'][number] }) {
  const total = row.users_total || 1
  const seg = (n: number) => `${(n / total) * 100}%`
  return (
    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
      {row.users_healthy > 0 && <div className="bg-green-500" style={{ width: seg(row.users_healthy) }} />}
      {row.users_warning_75 > 0 && <div className="bg-yellow-400" style={{ width: seg(row.users_warning_75) }} />}
      {row.users_near_90 > 0 && <div className="bg-amber-500" style={{ width: seg(row.users_near_90) }} />}
      {row.users_over_100 > 0 && <div className="bg-red-500" style={{ width: seg(row.users_over_100) }} />}
    </div>
  )
}

export default function CopilotSpend() {
  const [spend, setSpend] = useState<GitHubCopilotSpend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showUnbudgeted, setShowUnbudgeted] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setSpend(await getGitHubCopilotSpend())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read Copilot spend and budgets.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !spend) {
    return (
      <section>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3 flex items-center gap-2">
          <Wallet size={14} className="ds-u-color--muted" /> Copilot spend &amp; budget
        </h3>
        <div className="flex items-center gap-2 text-sm ds-u-color--muted py-6 justify-center">
          <Loader2 size={15} className="animate-spin" /> Reading cost-center budgets…
        </div>
      </section>
    )
  }

  if (error || spend?.error) {
    return (
      <section>
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3 flex items-center gap-2">
          <Wallet size={14} className="ds-u-color--muted" /> Copilot spend &amp; budget
        </h3>
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
          {error || spend?.error}
        </div>
      </section>
    )
  }

  if (!spend || (spend.cost_centers.length === 0 && spend.people.length === 0)) return null

  const peopleAtRisk = spend.people.filter(p => p.status !== 'healthy' && p.status !== 'unknown')

  function exportCostCenters() {
    if (!spend) return
    downloadCsv(
      `copilot-spend-by-cost-center-${spend.enterprise}.csv`,
      ['Cost center', 'Team/org', 'Budget (credits)', 'Blocks at cap', 'Seats', 'Healthy', 'Warning 75%+', 'Near 90%+', 'Over 100%', 'At risk', 'Status'],
      spend.cost_centers.map(r => [
        r.cost_center, resourceSummary(r.resources), r.budget_amount, r.prevent_further_usage ? 'yes' : 'no',
        r.users_total, r.users_healthy, r.users_warning_75, r.users_near_90, r.users_over_100, r.users_at_risk, r.status,
      ]),
    )
  }

  function exportPeople() {
    if (!spend) return
    downloadCsv(
      `copilot-ai-credit-caps-${spend.enterprise}.csv`,
      ['User', 'Used', 'Budget', '% used', 'Expires', 'Status'],
      spend.people.map(p => [p.login, p.consumed_amount, p.budget_amount, p.pct_used, p.expires_at, p.status]),
    )
  }

  return (
    <section>
      <div className="flex items-center justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 flex items-center gap-2">
          <Wallet size={14} className="ds-u-color--muted" /> Copilot spend &amp; budget
          <span className="ml-1 text-xs font-normal ds-u-color--muted font-mono">{spend.enterprise}</span>
        </h3>
        <button
          onClick={exportCostCenters}
          disabled={spend.cost_centers.length === 0}
          className="inline-flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-gray-800 disabled:opacity-40"
        >
          <Download size={12} /> Export cost centers
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        <StatTile
          label="Cost centers with a budget"
          value={spend.cost_centers.length + spend.cost_centers_individual.length}
          sub={`${spend.cost_centers_individual.length} via individual member budgets · ${spend.unbudgeted_cost_centers.length} with none`}
        />
        <StatTile
          label="Cost centers near/over cap"
          value={spend.cost_centers_at_risk + spend.cost_centers_individual.filter(c => c.status !== 'healthy').length}
          tone={spend.cost_centers_at_risk > 0 ? 'text-amber-600' : 'text-gray-900 dark:text-gray-100'}
        />
        <StatTile
          label="People near/over their cap"
          value={spend.people_at_risk}
          tone={spend.people_at_risk > 0 ? 'text-red-600' : 'text-gray-900 dark:text-gray-100'}
        />
      </div>

      <div className="mb-4">
        <CopilotBillingSpend />
      </div>

      {spend.cost_centers.length > 0 && (
        <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">Cost center</th>
                <th className="text-left px-3 py-2 font-medium">Team / org</th>
                <th className="text-left px-3 py-2 font-medium">Budget (credits)</th>
                <th className="text-left px-3 py-2 font-medium">Usage across seats</th>
                <th className="text-left px-3 py-2 font-medium">At risk</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {spend.cost_centers.map((row, i) => {
                const s = STATUS[row.status]
                return (
                  <tr key={row.cost_center} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">
                      {row.cost_center}
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{resourceSummary(row.resources)}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">
                      {row.budget_amount}
                      {row.prevent_further_usage && (
                        <span className="ml-1 text-[10px] ds-u-color--muted">blocks at cap</span>
                      )}
                    </td>
                    <td className="px-3 py-2 w-40">
                      <UsageBar row={row} />
                      <p className="mt-1 text-[10px] ds-u-color--muted">{row.users_total} seat{row.users_total === 1 ? '' : 's'}</p>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.users_at_risk > 0 ? (
                        <span className="text-amber-700">{row.users_at_risk} of {row.users_total}</span>
                      ) : (
                        <span className="ds-u-color--muted">none</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
                        {s.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {spend.cost_centers_individual.length > 0 && (
        <div className="mt-4 rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700 text-xs ds-u-color--muted">
            Covered by individual budgets on their members rather than a pooled cost-center budget
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">Cost center</th>
                <th className="text-left px-3 py-2 font-medium">Team / org</th>
                <th className="text-left px-3 py-2 font-medium">Members with a budget</th>
                <th className="text-left px-3 py-2 font-medium">At risk</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {spend.cost_centers_individual.map((row, i) => {
                const s = STATUS[row.status]
                return (
                  <tr key={row.cost_center} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{row.cost_center}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{resourceSummary(row.resources)}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300" title={row.members_with_budget.join(', ')}>
                      {row.members_with_budget_count}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.members_at_risk > 0 ? (
                        <span className="text-amber-700">{row.members_at_risk} of {row.members_with_budget_count}</span>
                      ) : (
                        <span className="ds-u-color--muted">none</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
                        {s.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {spend.unbudgeted_cost_centers.length > 0 && (
        <div className="mt-2">
          <button
            onClick={() => setShowUnbudgeted(v => !v)}
            className="text-xs text-cms-blue hover:underline"
          >
            {showUnbudgeted ? 'Hide' : 'Show'} the {spend.unbudgeted_cost_centers.length} cost center
            {spend.unbudgeted_cost_centers.length === 1 ? '' : 's'} with no Copilot budget configured
          </button>
          {showUnbudgeted && (
            <ul className="mt-2 space-y-1 text-xs ds-u-color--muted">
              {spend.unbudgeted_cost_centers.map(c => (
                <li key={c.cost_center}>
                  <span className="font-medium text-gray-700 dark:text-gray-200">{c.cost_center}</span>
                  {' — '}{resourceSummary(c.resources)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {peopleAtRisk.length > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-3 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-900 font-semibold">
            <span>People closest to their personal AI-credit cap ({peopleAtRisk.length})</span>
            <button onClick={exportPeople} className="inline-flex items-center gap-1.5 font-normal hover:underline">
              <Download size={12} /> Export
            </button>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">User</th>
                <th className="text-left px-3 py-2 font-medium">Used / budget</th>
                <th className="text-left px-3 py-2 font-medium">% used</th>
                <th className="text-left px-3 py-2 font-medium">Expires</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {peopleAtRisk.map((p, i) => {
                const s = STATUS[p.status]
                return (
                  <tr key={p.login} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{p.login}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">
                      {p.consumed_amount?.toFixed(1) ?? '—'} / {p.budget_amount}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">{p.pct_used}%</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{p.expires_at ?? '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${s.badge}`}>
                        {s.label}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-[11px] ds-u-color--muted">
        Read-only: budgets are shown as GitHub reports them. Increasing a cap is not wired up yet.
      </p>
    </section>
  )
}
