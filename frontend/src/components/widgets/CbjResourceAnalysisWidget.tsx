import { useState, useEffect, useCallback } from 'react'
import { Gauge, RefreshCw, Info, ChevronDown, ChevronRight } from 'lucide-react'
import { getCbjResourceAnalysis, CbjResourceAnalysisRow, CbjAnalysisTarget, CbjEnv } from '../../api/client'
import WidgetCard, { SkeletonRow } from './WidgetCard'
import { useSort, SortableTh, Accessor } from './sortable'
import { Badge } from '@cmsgov/design-system'

const ANALYSIS_ACCESSORS: Record<string, Accessor<CbjResourceAnalysisRow>> = {
  namespace: (r) => r.namespace,
  container: (r) => r.container,
  cpu_reserved: (r) => r.cpu_reserved_cores,
  cpu_used: (r) => r.cpu_used_at_peak_cores,
  cpu_wasted: (r) => r.cpu_wasted_cores,
  cpu_pct: (r) => r.cpu_pct_used,
  mem_reserved: (r) => r.mem_reserved_gb,
  mem_used: (r) => r.mem_used_at_peak_gb,
  mem_wasted: (r) => r.mem_wasted_gb,
  mem_pct: (r) => r.mem_pct_used,
  status: (r) => r.status,
}

function StatusBadge({ status }: { status: CbjResourceAnalysisRow['status'] }) {
  if (status === 'ok') return <Badge variation="success" className="ds-c-badge--xs">OK</Badge>
  if (status === 'warning') return <Badge variation="warn" className="ds-c-badge--xs">Low Use</Badge>
  if (status === 'critical') return <Badge variation="alert" className="ds-c-badge--xs">Wasteful</Badge>
  if (status === 'unknown') return <Badge className="ds-c-badge--xs">Unknown</Badge>
  return <Badge className="ds-c-badge--xs">{status}</Badge>
}

function rowTint(status: CbjResourceAnalysisRow['status']): string {
  const map: Record<string, string> = {
    critical: 'bg-red-50 hover:bg-red-100 dark:bg-red-900/20 dark:hover:bg-red-900/30',
    warning: 'bg-yellow-50 hover:bg-yellow-100 dark:bg-yellow-900/20 dark:hover:bg-yellow-900/30',
    ok: 'hover:bg-gray-50/50 dark:hover:bg-gray-800/40',
    unknown: 'hover:bg-gray-50/50 dark:hover:bg-gray-800/40',
  }
  return map[status] ?? 'hover:bg-gray-50/50 dark:hover:bg-gray-800/40'
}

function wastedColor(status: CbjResourceAnalysisRow['status']): string {
  const map: Record<string, string> = {
    critical: 'text-red-700 dark:text-red-400',
    warning: 'text-yellow-700 dark:text-yellow-400',
    ok: 'text-gray-800 dark:text-gray-200',
    unknown: 'text-gray-800 dark:text-gray-200',
  }
  return map[status] ?? 'text-gray-800 dark:text-gray-200'
}

function num(v: number | null, digits = 2): string {
  return v == null ? '—' : v.toFixed(digits)
}

function pct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

/**
 * CBJ Resource Analysis — compares what a container asked Kubernetes for
 * (Reserved) against what it actually used at its busiest moment recently
 * (Used at Peak), sourced live from CloudWatch Container Insights. High
 * Reserved + low % Used = that team's ADO can safely shrink their request.
 *
 * `target` picks agents (ephemeral build containers) or controllers (the
 * always-on `jenkins` container, one per team) — same table, same math,
 * different underlying query, to avoid duplicating this whole component.
 *
 * Rendered for one environment at a time (the Monitoring page picks it from a
 * dropdown) — prod-east and gc-prod-west are never combined into one table
 * (different AWS accounts/partitions).
 */
export default function CbjResourceAnalysisWidget({
  env,
  target = 'agents',
  title,
}: {
  env: CbjEnv
  target?: CbjAnalysisTarget
  title: string
}) {
  const [rows, setRows] = useState<CbjResourceAnalysisRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const { sorted, sortKey, sortDir, toggle } = useSort(rows, ANALYSIS_ACCESSORS, {
    key: 'cpu_wasted',
    dir: 'desc',
  })

  const fetchRows = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    setError('')
    try {
      const data = await getCbjResourceAnalysis(env, target)
      setRows(data)
    } catch {
      setError(`Failed to load CBJ resource analysis data for ${env}.`)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [env, target])

  useEffect(() => {
    fetchRows()
  }, [fetchRows])

  const refreshBtn = (
    <button
      onClick={() => fetchRows(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-800"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard title={title} icon={<Gauge size={14} />} action={refreshBtn} noPadding>
      <div className="px-5 pt-3 pb-2 border-b border-gray-100 dark:border-gray-800">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] ds-u-color--muted">
          <span>
            Sorted by CPU Wasted, worst first · <span className="text-red-700 dark:text-red-400 font-medium">red = wasteful</span>{' '}
            (&lt;10% used), <span className="text-yellow-700 dark:text-yellow-400 font-medium">yellow = low use</span> (10–30%).
          </span>
          <button
            onClick={() => setShowHelp((v) => !v)}
            className="inline-flex items-center gap-1 hover:text-cms-blue transition-colors"
          >
            <Info size={12} /> How it works
            {showHelp ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        </div>
      </div>
      {showHelp && (
      <div className="px-5 pt-3 pb-1 text-xs ds-u-color--muted space-y-2.5 border-b border-gray-100 dark:border-gray-800">
        <p>
          <span className="font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide text-[11px]">Methodology</span>
          {' — '}
          <span className="font-medium text-gray-700 dark:text-gray-300">Reserved</span> and{' '}
          <span className="font-medium text-gray-700 dark:text-gray-300">Used at Peak</span> both use the same rolling
          7-day window, sourced from CloudWatch Container Insights. Reserved is only re-reported when a{' '}
          {target === 'controllers' ? 'controller restarts' : 'pod starts'}, so the 7-day window is what keeps a{' '}
          {target === 'controllers' ? 'controller' : 'container'} visible with its current configuration even if it
          hasn't {target === 'controllers' ? 'restarted' : 'run'} in the past few days. Used at Peak is the busiest
          moment observed in that same window, wide enough to catch bursty or infrequent activity.
        </p>
        <p>
          <span className="font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide text-[11px]">Why it matters</span>
          {' — '}
          Karpenter sizes and provisions nodes off Reserved, not actual usage — it has no visibility into how little
          a container uses what it asked for, it just finds capacity to fit the request. A container reserving 8
          cores but using 0.1 is directly forcing Karpenter into a bigger (or an extra) node, regardless of how busy
          it actually is. Shrinking Reserved is the lever that lets Karpenter pack more workloads onto fewer, smaller
          nodes — this is a real infrastructure cost, not a tidiness metric.
        </p>
        <p>
          <span className="font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide text-[11px]">Reading this table</span>
          {' — '}
          Sorted by CPU Wasted, worst first.{' '}
          <span className="text-red-700 dark:text-red-400 font-medium">Red = wasteful</span> (under 10% of Reserved
          actually used), <span className="text-yellow-700 dark:text-yellow-400 font-medium">yellow = low use</span> (10–30%),
          white = within normal range.
        </p>
        <p className="italic">
          Treat rows here as leads to verify, not a final verdict — a container that hasn't run in the last 7 days
          won't appear at all. The podTemplate Config tab covers that gap with configured-intent data that doesn't
          depend on recent activity.
        </p>
        {target === 'controllers' && (
          <p className="border-t border-gray-100 dark:border-gray-800 pt-2">
            <span className="font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide text-[11px]">Sizing guidance</span>
            {' — '}
            CloudBees'{' '}
            <a href="https://docs.cloudbees.com/docs/cloudbees-ci/latest/cloud-reference-architecture/ra-for-eks/" target="_blank" rel="noopener noreferrer" className="text-cms-blue hover:underline">reference architecture</a>{' '}
            lists 1 CPU / 3GB as the documented minimum and 4 CPU / 4GB heap as recommended for a realistically
            active controller (~20 weekly users, up to 50 concurrent builds) — there is no hard cutoff below that,
            only a performance gradient (increased GC pressure, slower response). Downsize incrementally (8→4 before
            4→2, for example) and monitor for degradation after each change, since reduced performance is easy to
            miss if nobody checks immediately afterward.
          </p>
        )}
      </div>
      )}
      {error ? (
        <div className="p-5 text-sm text-red-600 dark:text-red-400 text-center">{error}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800">
                <SortableTh label="Team" sortKey="namespace" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Container" sortKey="container" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="CPU Reserved" sortKey="cpu_reserved" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="CPU Used" sortKey="cpu_used" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden md:table-cell" />
                <SortableTh label="CPU Wasted" sortKey="cpu_wasted" activeKey={sortKey} dir={sortDir} onSort={toggle} />
                <SortableTh label="Mem Reserved" sortKey="mem_reserved" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden lg:table-cell" />
                <SortableTh label="Mem Used" sortKey="mem_used" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden lg:table-cell" />
                <SortableTh label="Mem Wasted" sortKey="mem_wasted" activeKey={sortKey} dir={sortDir} onSort={toggle} className="hidden lg:table-cell" />
                <SortableTh label="Status" sortKey="status" activeKey={sortKey} dir={sortDir} onSort={toggle} />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
              {loading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} cols={9} />)
                : sorted.length === 0
                ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center ds-u-color--muted text-sm">
                      No resource data available for {env}
                    </td>
                  </tr>
                )
                : sorted.map((r) => (
                  <tr key={`${r.namespace}-${r.container}`} className={`transition-colors ${rowTint(r.status)}`}>
                    <td className="px-4 py-3 font-medium text-gray-800 dark:text-gray-200">{r.namespace}</td>
                    <td className="px-4 py-3 text-gray-600">{r.container}</td>
                    <td className="px-4 py-3 text-gray-600">{num(r.cpu_reserved_cores)} cores</td>
                    <td className="px-4 py-3 text-gray-600 hidden md:table-cell">
                      {num(r.cpu_used_at_peak_cores)} cores ({pct(r.cpu_pct_used)})
                    </td>
                    <td className={`px-4 py-3 font-semibold ${wastedColor(r.status)}`}>{num(r.cpu_wasted_cores)} cores</td>
                    <td className="px-4 py-3 text-gray-600 hidden lg:table-cell">{num(r.mem_reserved_gb)} GB</td>
                    <td className="px-4 py-3 text-gray-600 hidden lg:table-cell">
                      {num(r.mem_used_at_peak_gb)} GB ({pct(r.mem_pct_used)})
                    </td>
                    <td className={`px-4 py-3 hidden lg:table-cell ${wastedColor(r.status)}`}>{num(r.mem_wasted_gb)} GB</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={r.status} />
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
