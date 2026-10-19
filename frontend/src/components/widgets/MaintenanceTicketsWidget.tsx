import { useState, useEffect, useCallback } from 'react'
import { ClipboardList, RefreshCw, ExternalLink } from 'lucide-react'
import { getMaintenanceOverview, getTicketReadiness, MaintenanceOverview } from '../../api/client'
import WidgetCard, { SkeletonRow } from './WidgetCard'
import { Badge } from '@cmsgov/design-system'

const PREP_LABELS: Record<string, string> = {
  jfrog: 'JFrog Prep',
  cloudbees: 'CloudBees Prep',
  sonarqube: 'SonarQube Prep',
}

function StatusBadge({ status, isClosed }: { status: string | null; isClosed: boolean }) {
  if (!status) {
    return <Badge className="ds-c-badge--xs">Not created</Badge>
  }
  if (isClosed) return <Badge variation="success" className="ds-c-badge--xs">{status}</Badge>
  return <Badge variation="warn" className="ds-c-badge--xs">{status}</Badge>
}

interface Row {
  label: string
  key: string | null
  url: string | null
  status: string | null
  isClosed: boolean
  detail?: string | null
}

function toRows(overview: MaintenanceOverview): Row[] {
  const rows: Row[] = []

  for (const [tool, label] of Object.entries(PREP_LABELS)) {
    const t = overview.prep.tools[tool]
    rows.push({
      label,
      key: t?.key ?? null,
      url: t?.url ?? null,
      status: t?.status ?? null,
      isClosed: false, // prep tickets are tracked as "created" not open/closed
      detail: t?.assignee_name ?? null,
    })
  }

  rows.push({
    label: 'ITC Ticket',
    key: overview.itc?.key ?? null,
    url: overview.itc?.url ?? null,
    status: overview.itc?.status ?? null,
    isClosed: overview.itc?.is_closed ?? false,
  })

  rows.push({
    label: 'MGGD Ticket',
    key: overview.mggd?.key ?? null,
    url: overview.mggd?.url ?? null,
    status: overview.mggd?.status ?? null,
    isClosed: overview.mggd?.is_closed ?? false,
  })

  return rows
}

export default function MaintenanceTicketsWidget() {
  const [overview, setOverview] = useState<MaintenanceOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [maintDateStr, setMaintDateStr] = useState('')

  const fetchOverview = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getMaintenanceOverview()
      setOverview(data)
    } catch {
      setError('Failed to load maintenance ticket status.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    getTicketReadiness().then((r) => setMaintDateStr(r.maint_date_str)).catch(() => {})
    fetchOverview()
  }, [fetchOverview])

  const refreshBtn = (
    <button
      onClick={() => fetchOverview(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  const rows = overview ? toRows(overview) : []

  return (
    <WidgetCard
      title={maintDateStr ? `Maintenance Tickets — ${maintDateStr}` : 'Maintenance Tickets'}
      icon={<ClipboardList size={14} />}
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
                <th className="px-4 py-2 text-left text-xs font-semibold ds-u-color--muted uppercase tracking-wide">Ticket</th>
                <th className="px-4 py-2 text-left text-xs font-semibold ds-u-color--muted uppercase tracking-wide">Key</th>
                <th className="px-4 py-2 text-left text-xs font-semibold ds-u-color--muted uppercase tracking-wide hidden md:table-cell">Assignee</th>
                <th className="px-4 py-2 text-left text-xs font-semibold ds-u-color--muted uppercase tracking-wide">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} cols={4} />)
                : rows.map((r) => (
                  <tr key={r.label} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-800">{r.label}</td>
                    <td className="px-4 py-3">
                      {r.key && r.url ? (
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs font-mono font-medium text-cms-blue hover:underline"
                        >
                          {r.key}
                          <ExternalLink size={10} className="text-gray-300" />
                        </a>
                      ) : (
                        <span className="ds-u-color--muted text-sm">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 ds-u-color--muted text-xs hidden md:table-cell">
                      {r.detail || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} isClosed={r.isClosed} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </WidgetCard>
  )
}
