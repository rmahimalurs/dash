import { useState, useEffect, useCallback } from 'react'
import { KeyRound, RefreshCw } from 'lucide-react'
import { getServiceAccounts, ServiceAccount } from '../../api/client'
import WidgetCard, { SkeletonRow } from './WidgetCard'
import { useSort, SortableTh, Accessor } from './sortable'
import { format, parseISO } from 'date-fns'
import { Badge } from '@cmsgov/design-system'

const ACCOUNT_ACCESSORS: Record<string, Accessor<ServiceAccount>> = {
  service: (a) => a.label,
  account: (a) => a.username,
  // never-expires rows have null expiry/days and sort last automatically
  expiry: (a) => a.expiry_date,
  days: (a) => a.days_remaining,
  status: (a) => a.status,
}

function StatusBadge({ status, daysLeft }: { status: ServiceAccount['status']; daysLeft: number | null }) {
  if (status === 'ok') return <Badge variation="success" className="ds-c-badge--xs">OK</Badge>
  if (status === 'warning') return <Badge variation="warn" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Warning'}</Badge>
  if (status === 'critical') return <Badge variation="alert" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Critical'}</Badge>
  if (status === 'unknown') return <Badge className="ds-c-badge--xs">Unknown</Badge>
  const map: Record<string, { label: string; cls: string }> = {
    expired:       { label: 'Expired',      cls: 'status-expired' },
    never_expires: { label: 'Never',        cls: 'status-never-expires' },
  }
  const { label, cls } = map[status] ?? { label: status, cls: '' }
  return <Badge className={`ds-c-badge--xs ${cls}`}>{label}</Badge>
}

function DaysCell({ daysLeft, neverExpires }: { daysLeft: number | null; neverExpires: boolean }) {
  if (neverExpires) return <span className="text-blue-600 text-sm">Never</span>
  if (daysLeft == null) return <span className="ds-u-color--muted text-sm">—</span>
  const color =
    daysLeft <= 0
      ? 'text-red-700 font-bold'
      : daysLeft <= 14
      ? 'text-red-600 font-semibold'
      : daysLeft <= 30
      ? 'text-yellow-600 font-semibold'
      : 'text-gray-600'
  return <span className={`text-sm ${color}`}>{daysLeft <= 0 ? 'Expired' : `${daysLeft}d`}</span>
}

export default function ServiceAccountWidget() {
  const [accounts, setAccounts] = useState<ServiceAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const { sorted, sortKey, sortDir, toggle } = useSort(accounts, ACCOUNT_ACCESSORS)

  const fetchAccounts = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getServiceAccounts()
      setAccounts(data)
    } catch {
      setError('Failed to load service account data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchAccounts()
  }, [fetchAccounts])

  const refreshBtn = (
    <button
      onClick={() => fetchAccounts(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard
      title="Service Account Password Expiry"
      icon={<KeyRound size={14} />}
      action={refreshBtn}
      noPadding
    >
      {error ? (
        <div className="p-5 text-sm text-red-600 text-center">{error}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <SortableTh label="Service" sortKey="service" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Account" sortKey="account" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Expires" sortKey="expiry" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Left" sortKey="days" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Status" sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggle} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 11 }).map((_, i) => <SkeletonRow key={i} cols={5} />)
                : accounts.length === 0
                ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center ds-u-color--muted text-sm">
                      No service account data available
                    </td>
                  </tr>
                )
                : sorted.map((acct) => {
                  const [service, env] = acct.label.includes(' / ')
                    ? acct.label.split(' / ', 2)
                    : [acct.label, null]
                  return (
                  <tr key={acct.label} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-4 py-3">
                      <span className="font-medium text-gray-800">{service}</span>
                      {env && (
                        <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 ds-u-color--muted">
                          {env}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs ds-u-color--muted">{acct.username}</td>
                    <td className="px-4 py-3 text-gray-600">
                      {acct.never_expires
                        ? <span className="text-blue-600 text-sm">Never</span>
                        : acct.expiry_date
                        ? format(parseISO(acct.expiry_date), 'MMM d, yyyy')
                        : <span className="ds-u-color--muted">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <DaysCell daysLeft={acct.days_remaining} neverExpires={acct.never_expires} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={acct.status} daysLeft={acct.days_remaining} />
                    </td>
                  </tr>
                  )
                })}
            </tbody>
          </table>
          {!loading && accounts.some(a => a.error && !a.never_expires) && (
            <div className="px-4 py-2 border-t border-gray-100 space-y-1">
              {accounts.filter(a => a.error && !a.never_expires).map(a => (
                <p key={a.label} className="text-xs ds-u-color--muted">
                  <span className="font-medium ds-u-color--muted">{a.label}:</span> {a.error}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </WidgetCard>
  )
}
