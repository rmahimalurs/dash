import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotBillingSpend,
  type GitHubCopilotBillingSpend,
} from '../../api/client'

const MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function CopilotBillingSpend() {
  const [data, setData] = useState<GitHubCopilotBillingSpend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await getGitHubCopilotBillingSpend())
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not read metered billing spend.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-xs ds-u-color--muted py-4 justify-center">
        <Loader2 size={13} className="animate-spin" /> Reading metered billing usage…
      </div>
    )
  }

  if (error || data?.error) {
    return (
      <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs">
        <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" /> {error || data?.error}
      </div>
    )
  }

  if (!data || data.monthly.length === 0) return null

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 dark:bg-amber-900/10 overflow-hidden">
      <div className="px-3 py-2 border-b border-amber-200 text-xs text-amber-900">
        <strong>Metered billing usage, not total Copilot cost.</strong> This is GitHub's enhanced billing
        usage report — real dollars, but for {data.enterprise} it comes back far below list price for
        ~350 Copilot Business seats, which means the bulk seat licensing here is almost certainly invoiced
        through a separate enterprise agreement, not this metered report. Treat this as incidental/overage
        usage only.
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-3">
        <div>
          <p className="text-xs ds-u-color--muted mb-2">Metered spend by month</p>
          <table className="w-full text-sm">
            <tbody>
              {data.monthly.map(m => (
                <tr key={`${m.year}-${m.month}`} className="border-t border-amber-100 first:border-t-0">
                  <td className="py-1 text-xs text-gray-700 dark:text-gray-300">{MONTH_NAMES[m.month]} {m.year}</td>
                  <td className="py-1 text-xs text-right text-gray-900 dark:text-gray-100 font-medium">${m.net_amount.toFixed(2)}</td>
                  <td className="py-1 pl-3 text-[10px] ds-u-color--muted text-right">{m.line_items} line items</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <p className="text-xs ds-u-color--muted mb-2">By SKU (all months shown)</p>
          <table className="w-full text-sm">
            <tbody>
              {data.by_sku.map(s => (
                <tr key={s.sku} className="border-t border-amber-100 first:border-t-0">
                  <td className="py-1 text-xs text-gray-700 dark:text-gray-300">{s.sku}</td>
                  <td className="py-1 text-xs text-right text-gray-900 dark:text-gray-100 font-medium">${s.net_amount.toFixed(2)}</td>
                  <td className="py-1 pl-3 text-[10px] ds-u-color--muted text-right">{s.quantity.toFixed(2)} units</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
