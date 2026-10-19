import { useState, useEffect, useCallback } from 'react'
import { Shield, RefreshCw } from 'lucide-react'
import { getCertificates, Certificate } from '../../api/client'
import WidgetCard, { SkeletonRow } from './WidgetCard'
import { useSort, SortableTh, Accessor } from './sortable'
import { format, parseISO } from 'date-fns'
import { Badge } from '@cmsgov/design-system'

const CERT_ACCESSORS: Record<string, Accessor<Certificate>> = {
  tool: (c) => c.tool,
  env: (c) => c.env,
  domain: (c) => c.domain,
  expiry: (c) => c.expiry_date, // ISO strings sort chronologically
  days: (c) => c.days_remaining,
  status: (c) => c.status,
}

function environmentBadgeClass(environment: string): string {
  const normalized = environment.toLowerCase()
  if (normalized.includes('prod') || normalized === 'production') return 'ds-c-badge--prod'
  if (normalized.includes('dev')) return 'ds-c-badge--dev'
  return ''
}

function StatusBadge({ status, daysLeft }: { status: Certificate['status']; daysLeft: number | null }) {
  if (status === 'ok') return <Badge variation="success" className="ds-c-badge--xs">OK</Badge>
  if (status === 'warning') return <Badge variation="warn" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Warning'}</Badge>
  if (status === 'critical') return <Badge variation="alert" className="ds-c-badge--xs">{daysLeft != null ? `${daysLeft}d` : 'Critical'}</Badge>
  if (status === 'unknown') return <Badge className="ds-c-badge--xs">Unknown</Badge>
  
  return (
    <Badge className="ds-c-badge--xs">{status}</Badge>
  )
}

function DaysCell({ daysLeft }: { daysLeft: number | null }) {
  if (daysLeft == null) return <span className="ds-u-color--muted text-sm">—</span>
  const color =
    daysLeft <= 14
      ? 'text-red-600 font-semibold'
      : daysLeft <= 30
      ? 'text-yellow-600 font-semibold'
      : 'text-gray-600'
  return <span className={`text-sm ${color}`}>{daysLeft}d</span>
}

export default function CertificateWidget() {
  const [certs, setCerts] = useState<Certificate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const { sorted, sortKey, sortDir, toggle } = useSort(certs, CERT_ACCESSORS)

  const fetchCerts = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getCertificates()
      setCerts(data)
    } catch {
      setError('Failed to load certificate data.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchCerts()
  }, [fetchCerts])

  const refreshBtn = (
    <button
      onClick={() => fetchCerts(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard
      title="Certificate Expiry"
      icon={<Shield size={14} />}
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
                <SortableTh label="Tool" sortKey="tool" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Env" sortKey="env" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Domain" sortKey="domain" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden md:table-cell" />
                <SortableTh label="Expires" sortKey="expiry" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Left" sortKey="days" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Status" sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggle} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} cols={6} />)
                : certs.length === 0
                ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center ds-u-color--muted text-sm">
                      No certificate data available
                    </td>
                  </tr>
                )
                : sorted.map((cert) => (
                  <tr key={`${cert.tool}-${cert.env}`} className="hover:bg-gray-50/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-800">{cert.tool}</td>
                    <td className="px-4 py-3">
                      <Badge className={`${environmentBadgeClass(cert.env)} ds-c-badge--xs`}>
                        {cert.env}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 ds-u-color--muted font-mono text-xs hidden md:table-cell">
                      {cert.domain}
                    </td>
                    <td className="px-4 py-3 text-gray-600">
                      {cert.expiry_date ? format(parseISO(cert.expiry_date), 'MMM d, yyyy') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <DaysCell daysLeft={cert.days_remaining} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={cert.status} daysLeft={cert.days_remaining} />
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
