import { useState, useEffect, useCallback } from 'react'
import { Key, RefreshCw } from 'lucide-react'
import { getLicenses, License } from '../../api/client'
import WidgetCard, { SkeletonRow } from './WidgetCard'
import { useSort, SortableTh, Accessor } from './sortable'
import { format, parseISO } from 'date-fns'
import { Badge } from '@cmsgov/design-system'

const LICENSE_ACCESSORS: Record<string, Accessor<License>> = {
  tool: (l) => l.tool,
  env: (l) => l.env,
  type: (l) => l.notes,
  expiry: (l) => l.expiry_date, // ISO strings sort chronologically
  days: (l) => l.days_remaining,
  status: (l) => l.status,
}

function environmentBadgeClass(environment: string): string {
  const normalized = environment.toLowerCase()
  if (normalized.includes('prod') || normalized === 'production') return 'ds-c-badge--prod'
  if (normalized.includes('dev')) return 'ds-c-badge--dev'
  return ''
}

function StatusBadge({ status, daysLeft }: { status: License['status']; daysLeft: number | null }) {
  if (status === 'ok') return <Badge variation="success" className="ds-c-badge--xs">OK</Badge>
  if (status === 'warning') return <Badge variation="warn" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Warning'}</Badge>
  if (status === 'critical') return <Badge variation="alert" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Critical'}</Badge>
  if (status === 'manual') return <Badge variation="info" className="ds-c-badge--xs">Manual Check</Badge>
  if (status === 'check_manually') return <Badge variation="info" className="ds-c-badge--xs">Check Manually</Badge>
  if (status === 'unknown') return <Badge className="ds-c-badge--xs">Unknown</Badge>
  return <Badge className="ds-c-badge--xs">{status}</Badge>
}

function DaysCell({ daysLeft }: { daysLeft: number | null }) {
  if (daysLeft == null) return <span className="ds-u-color--muted text-sm">—</span>
  const color =
    daysLeft <= 0    ? 'text-red-700 font-bold' :
    daysLeft <= 14   ? 'text-red-600 font-semibold' :
    daysLeft <= 30   ? 'text-yellow-600 font-semibold' :
                       'text-gray-600'
  return <span className={`text-sm ${color}`}>{daysLeft <= 0 ? 'Expired' : `${daysLeft}d`}</span>
}

export default function LicenseWidget() {
  const [licenses, setLicenses] = useState<License[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const { sorted, sortKey, sortDir, toggle } = useSort(licenses, LICENSE_ACCESSORS)

  const fetchLicenses = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getLicenses()
      setLicenses(data)
    } catch {
      setError('Failed to load license data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchLicenses()
  }, [fetchLicenses])

  const refreshBtn = (
    <button
      onClick={() => fetchLicenses(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard title="License Expiry" icon={<Key size={14} />} action={refreshBtn} noPadding>
      {error ? (
        <div className="p-5 text-sm text-red-600 text-center">{error}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <SortableTh label="Tool" sortKey="tool" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Env" sortKey="env" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Type" sortKey="type" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden md:table-cell" />
                <SortableTh label="Expires" sortKey="expiry" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Left" sortKey="days" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Status" sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggle} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} cols={6} />)
                : licenses.length === 0
                ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center ds-u-color--muted text-sm">
                      No license data available
                    </td>
                  </tr>
                )
                : sorted.map((lic) => (
                  <tr key={`${lic.tool}-${lic.env}`} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-800">{lic.tool}</td>
                    <td className="px-4 py-3">
                      <Badge className={`${environmentBadgeClass(lic.env)} ds-c-badge--xs`}>
                        {lic.env}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 ds-u-color--muted text-xs hidden md:table-cell">
                      {lic.notes || '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {lic.expiry_date ? format(parseISO(lic.expiry_date), 'MMM d, yyyy') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <DaysCell daysLeft={lic.days_remaining} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={lic.status} daysLeft={lic.days_remaining} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {!loading && licenses.some(l => l.error) && (
            <div className="px-4 py-2 border-t border-gray-100 space-y-1">
              {licenses.filter(l => l.error).map(l => (
                <p key={`${l.tool}-${l.env}`} className="text-xs ds-u-color--muted">
                  <span className="font-medium ds-u-color--muted">{l.tool} / {l.env}:</span> {l.error}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </WidgetCard>
  )
}
