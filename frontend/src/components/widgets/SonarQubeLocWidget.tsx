import { useState, useEffect, useCallback } from 'react'
import { Gauge, RefreshCw } from 'lucide-react'
import { getSonarQubeLoc, SonarQubeLoc } from '../../api/client'
import WidgetCard from './WidgetCard'
import { Badge } from '@cmsgov/design-system'

function barColor(status: SonarQubeLoc['status']): string {
  switch (status) {
    case 'critical': return 'bg-red-600'
    case 'warning': return 'bg-yellow-500'
    case 'ok': return 'bg-green-600'
    default: return 'bg-gray-300'
  }
}

function StatusBadge({ status }: { status: SonarQubeLoc['status'] }) {
  if (status === 'ok') return <Badge variation="success" className="ds-c-badge--xs">OK</Badge>
  if (status === 'warning') return <Badge variation="warn" className="ds-c-badge--xs">Warning</Badge>
  if (status === 'critical') return <Badge variation="alert" className="ds-c-badge--xs">Critical</Badge>
  if (status === 'check_manually') return <Badge variation="info" className="ds-c-badge--xs">Check Manually</Badge>
  if (status === 'unknown') return <Badge className="ds-c-badge--xs">Unknown</Badge>
  return <Badge className="ds-c-badge--xs">{status}</Badge>
}

function LocRow({ loc }: { loc: SonarQubeLoc }) {
  const pct = loc.percent_used
  const width = pct != null ? Math.min(pct, 100) : 0

  return (
    <div className="py-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium text-gray-800">{loc.env}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs ds-u-color--muted">
            {loc.total_ncloc != null && loc.cap != null
              ? `${loc.total_ncloc.toLocaleString()} / ${loc.cap.toLocaleString()}`
              : '—'}
          </span>
          <StatusBadge status={loc.status} />
        </div>
      </div>
      <div className="w-full h-2 rounded-full bg-gray-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor(loc.status)}`}
          style={{ width: `${width}%` }}
        />
      </div>
      {loc.error && <p className="text-xs ds-u-color--muted mt-1">{loc.error}</p>}
    </div>
  )
}

export default function SonarQubeLocWidget() {
  const [locs, setLocs] = useState<SonarQubeLoc[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const fetchLocs = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getSonarQubeLoc()
      setLocs(data)
    } catch {
      setError('Failed to load SonarQube LOC data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchLocs()
  }, [fetchLocs])

  const refreshBtn = (
    <button
      onClick={() => fetchLocs(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard title="SonarQube Licensed Lines of Code (LOC)" icon={<Gauge size={14} />} action={refreshBtn}>
      <p className="text-xs ds-u-color--muted mb-3">
        Server-wide code volume counted against SonarQube's license cap — not a per-project count.
        Past the cap, new analyses are rejected outright.
      </p>
      {error ? (
        <div className="text-sm text-red-600 text-center py-4">{error}</div>
      ) : loading ? (
        <div className="text-sm ds-u-color--muted text-center py-4">Loading…</div>
      ) : locs.length === 0 ? (
        <div className="text-sm ds-u-color--muted text-center py-4">No data available</div>
      ) : (
        <div className="divide-y divide-gray-50">
          {locs.map((loc) => (
            <LocRow key={`${loc.tool}-${loc.env}`} loc={loc} />
          ))}
        </div>
      )}
    </WidgetCard>
  )
}
