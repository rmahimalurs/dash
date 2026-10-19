import { useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { apiErrorMessage, getGitHubCopilotPerson, type GitHubCopilotPersonDetail } from '../../api/client'
import Modal from '../ui/Modal'

const PACING_LABEL: Record<string, string> = {
  over_budget: 'Over budget',
  ahead_of_pace: 'Ahead of pace',
  well_behind_pace: 'Well behind pace',
  behind_pace: 'Behind pace',
  on_pace: 'On pace',
}

const PACING_TONE: Record<string, string> = {
  bad: 'text-red-600',
  warn: 'text-amber-600',
  neutral: 'ds-u-color--muted',
  good: 'text-green-700',
}

export default function CopilotPersonDetail({ login, onClose }: { login: string | null; onClose: () => void }) {
  const [data, setData] = useState<GitHubCopilotPersonDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!login) return
    setData(null)
    setError('')
    setLoading(true)
    getGitHubCopilotPerson(login)
      .then(setData)
      .catch(err => setError(apiErrorMessage(err, 'Could not read this person’s activity.')))
      .finally(() => setLoading(false))
  }, [login])

  return (
    <Modal open={login !== null} onClose={onClose} title={login ?? ''} wide>
      {loading && (
        <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
          <Loader2 size={15} className="animate-spin" /> Reading activity for {login}…
        </div>
      )}

      {(error || data?.error) && !loading && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
          {error || data?.error}
        </div>
      )}

      {data && !data.error && (
        <div className="space-y-5">
          <p className="text-xs ds-u-color--muted">
            Everything recorded between {data.report_start_day} and {data.report_end_day} ({data.active_days} active days).
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
              <p className="text-xs font-semibold ds-u-color--muted mb-2">Seat</p>
              <dl className="space-y-1 text-xs">
                <div className="flex justify-between"><dt className="ds-u-color--muted">Organization</dt><dd>{data.seat?.organization ?? '—'}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Editor</dt><dd>{data.seat?.editor ?? '—'}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Idle days</dt><dd>{data.seat?.idle_days ?? '—'}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Never used</dt><dd>{data.seat?.never_used ? 'yes' : 'no'}</dd></div>
              </dl>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
              <p className="text-xs font-semibold ds-u-color--muted mb-2">Activity totals</p>
              <dl className="space-y-1 text-xs">
                <div className="flex justify-between"><dt className="ds-u-color--muted">Interactions</dt><dd>{data.interactions.toLocaleString()}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Generations</dt><dd>{data.generations.toLocaleString()}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Acceptances</dt><dd>{data.acceptances.toLocaleString()}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Acceptance rate</dt><dd>{data.acceptance_rate !== null ? `${data.acceptance_rate}%` : '—'}</dd></div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">Lines added</dt><dd>{data.lines_added.toLocaleString()}</dd></div>
                <div className="flex justify-between">
                  <dt className="ds-u-color--muted" title="Lines added / lines suggested. Can read over 100% for people whose usage is mostly chat or agent edits, since those write lines directly rather than through a suggest-then-accept flow.">
                    Line acceptance rate
                  </dt>
                  <dd>{data.line_acceptance_rate !== null ? `${data.line_acceptance_rate}%` : '—'}</dd>
                </div>
                <div className="flex justify-between"><dt className="ds-u-color--muted">AI credits used</dt><dd>{data.ai_credits_used.toLocaleString()}</dd></div>
              </dl>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
              <p className="text-xs font-semibold ds-u-color--muted mb-2">Personal AI-credit budget</p>
              {data.budget ? (
                <>
                  <p className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
                    {data.budget.pct_used !== null ? `${data.budget.pct_used}%` : '—'}
                  </p>
                  <p className="text-xs ds-u-color--muted mt-0.5">
                    {data.budget.consumed_amount?.toFixed(1) ?? '—'} / {data.budget.budget_amount} · expires {data.budget.expires_at ?? '—'}
                  </p>
                  {data.budget_pacing && (
                    <p className={`text-xs mt-2 font-medium ${PACING_TONE[data.budget_pacing.tone]}`}>
                      {PACING_LABEL[data.budget_pacing.label] ?? data.budget_pacing.label}
                      {data.budget_pacing.note && ` · ${data.budget_pacing.note}`}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-xs ds-u-color--muted">No personal budget — covered by a pooled cost-center budget, or none configured.</p>
              )}
            </div>
          </div>

          {!data.model_feature_matrix.empty && (
            <div>
              <p className="text-xs font-semibold ds-u-color--muted mb-2">
                Which model for which feature — top model: <span className="font-mono">{data.model_feature_matrix.top_model}</span>,
                top feature: {data.model_feature_matrix.top_feature}
              </p>
              <div className="overflow-x-auto rounded-lg border border-gray-100 dark:border-gray-700">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                      <th className="text-left px-3 py-2 font-medium">Model</th>
                      {data.model_feature_matrix.columns.map(col => (
                        <th key={col.id} className="text-center px-3 py-2 font-medium whitespace-nowrap">
                          {col.label}
                          <div className="text-[10px] font-normal">{col.total.toLocaleString()} {col.unit}</div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.model_feature_matrix.rows.map((row, i) => (
                      <tr key={row.model} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                        <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200 whitespace-nowrap">{row.model}</td>
                        {row.cells.map((cell, j) => (
                          <td key={j} className="px-3 py-2 text-xs text-center">
                            {cell.share !== null ? (
                              <span className={cell.share >= 50 ? 'font-semibold text-cms-blue' : 'ds-u-color--muted'}>
                                {cell.share}%
                              </span>
                            ) : (
                              <span className="ds-u-color--muted">·</span>
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.model_feature_rows.length > 0 && (
            <div>
              <p className="text-xs font-semibold ds-u-color--muted mb-2">Exact counts, most prompted first</p>
              <div className="rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                      <th className="text-left px-3 py-2 font-medium">Model</th>
                      <th className="text-left px-3 py-2 font-medium">Feature</th>
                      <th className="text-left px-3 py-2 font-medium">Prompts</th>
                      <th className="text-left px-3 py-2 font-medium">Suggestions</th>
                      <th className="text-left px-3 py-2 font-medium">Acceptances</th>
                      <th className="text-left px-3 py-2 font-medium">Lines</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.model_feature_rows.map((r, i) => (
                      <tr key={`${r.model}-${r.feature}-${i}`} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                        <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{r.model}</td>
                        <td className="px-3 py-2 text-xs ds-u-color--muted">{r.feature}</td>
                        <td className="px-3 py-2 text-xs ds-u-color--muted">{r.prompts.toLocaleString()}</td>
                        <td className="px-3 py-2 text-xs ds-u-color--muted">{r.suggestions.toLocaleString()}</td>
                        <td className="px-3 py-2 text-xs ds-u-color--muted">{r.acceptances.toLocaleString()}</td>
                        <td className="px-3 py-2 text-xs ds-u-color--muted">{r.lines.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
