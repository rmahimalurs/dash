import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { FileCode2, RefreshCw, ChevronDown, ChevronRight, ExternalLink, Info } from 'lucide-react'
import {
  getCbjPodTemplateConfig,
  startCbjPodTemplateSweep,
  getCbjPodTemplateSweepStatus,
  CbjPodTemplateSweep,
  CbjPodTemplateContainer,
  CbjPodTemplateControllerResult,
  CbjPodTemplateJobRef,
} from '../../api/client'
import WidgetCard from './WidgetCard'

function fmtWhen(ts: number | null | undefined): string {
  if (!ts) return 'never'
  return new Date(ts * 1000).toLocaleString()
}

/** Compact KPI tile for the summary row. `tone` uses the app's reserved status
 * inks (red = confirmed waste, amber = leads/failures); default is neutral. */
function StatTile({ value, label, tone = 'neutral' }: { value: number | string; label: string; tone?: 'neutral' | 'red' | 'amber' }) {
  const valueCls =
    tone === 'red' ? 'text-red-700 dark:text-red-400'
    : tone === 'amber' ? 'text-amber-700 dark:text-amber-400'
    : 'text-gray-800 dark:text-gray-100'
  return (
    <div className="px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-700 min-w-[92px]">
      <div className={`text-xl font-semibold leading-none tabular-nums ${valueCls}`}>{value}</div>
      <div className="text-[10px] ds-u-color--muted uppercase tracking-wide mt-1.5 whitespace-nowrap">{label}</div>
    </div>
  )
}

const SOURCE_STYLE: Record<string, { label: string; cls: string }> = {
  'console-log': { label: 'console log', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300' },
  'replay-yaml': { label: 'replay yaml', cls: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' },
  'containerTemplate-dsl': { label: 'containerTemplate', cls: 'bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300' },
}

function sourceBadge(source: string) {
  const s = SOURCE_STYLE[source] ?? { label: source, cls: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' }
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium whitespace-nowrap ${s.cls}`}>
      {s.label}
    </span>
  )
}

// Reasonable-CI-job bars, generous on purpose (CloudBees' own docs call 4
// CPU / 4GB "recommended" for a busy CONTROLLER, not a single build agent
// container) — anything at or above these is worth a second look.
const LARGE_CPU_CORES = 8
const LARGE_MEM_GIB = 16
const LARGE_EPHEMERAL_GIB = 20

function toGiB(v: string | null | undefined): number | null {
  if (!v) return null
  const m = v.match(/^([\d.]+)\s*(Ki|Mi|Gi|Ti|K|M|G|T)?$/i)
  if (!m) return null
  const num = parseFloat(m[1])
  const unit = (m[2] || '').toLowerCase()
  const factors: Record<string, number> = {
    '': 1 / 1024 ** 3,
    k: 1000 / 1024 ** 3,
    m: 1000 ** 2 / 1024 ** 3,
    g: 1000 ** 3 / 1024 ** 3,
    t: 1000 ** 4 / 1024 ** 3,
    ki: 1 / 1024 ** 2,
    mi: 1 / 1024,
    gi: 1,
    ti: 1024,
  }
  return num * (factors[unit] ?? 1)
}

// CloudWatch reports memory in base-10 GB (backend divides bytes by 1e9); the
// rest of this widget works in GiB (base-1024). Convert so the "used %" (vs a
// GiB request) and the "Gi" display label stay consistent — otherwise memory
// used reads ~7% low.
function cwGbToGiB(gb: number | null | undefined): number | null {
  return gb == null ? null : (gb * 1e9) / 1024 ** 3
}

function toCores(v: string | null | undefined): number {
  if (!v) return 0
  const m = v.match(/^([\d.]+)(m)?$/i)
  if (!m) return 0
  const num = parseFloat(m[1])
  return m[2] ? num / 1000 : num
}

function isLargeEphemeral(v: string | null | undefined): boolean {
  const gib = toGiB(v)
  return gib != null && gib >= LARGE_EPHEMERAL_GIB
}
function isLargeCpu(v: string | null | undefined): boolean {
  return toCores(v) >= LARGE_CPU_CORES
}
function isLargeMem(v: string | null | undefined): boolean {
  const gib = toGiB(v)
  return gib != null && gib >= LARGE_MEM_GIB
}

// jnlp is Jenkins' own agent-connector sidecar, present on essentially every
// pod — not something an ADO configures or can change. Pure noise here.
const NOISE_CONTAINERS = new Set(['jnlp'])

// Two genuinely different kinds of finding, not one blended "flagged" pile:
// confirmed waste has CloudWatch evidence behind it (ready for outreach
// today); a large request with no CloudWatch data is a lead worth checking,
// not proof of anything — CloudWatch simply hasn't seen that container run
// recently, which is exactly the gap this whole tool exists to surface.
function isConfirmedWaste(c: CbjPodTemplateContainer): boolean {
  return c.cw_status === 'critical' || c.cw_status === 'warning'
}
function isLargeNoData(c: CbjPodTemplateContainer): boolean {
  const hasData = c.cw_status && c.cw_status !== 'unknown'
  return !hasData && (isLargeCpu(c.cpu_request) || isLargeMem(c.mem_request) || isLargeEphemeral(c.ephemeral_request))
}
function isFlagged(c: CbjPodTemplateContainer): boolean {
  return isConfirmedWaste(c) || isLargeNoData(c)
}

function cpuWasted(c: CbjPodTemplateContainer): number {
  const req = toCores(c.cpu_request)
  if (!req || c.cw_cpu_used_at_peak_cores == null) return 0
  return Math.max(0, req - c.cw_cpu_used_at_peak_cores)
}

// Combined severity across all three dimensions, normalized so no single
// resource dominates just by having bigger raw numbers (100Gi vs 16 cores).
function severity(c: CbjPodTemplateContainer): number {
  const cpuScore = toCores(c.cpu_request) / LARGE_CPU_CORES
  const memScore = (toGiB(c.mem_request) ?? 0) / LARGE_MEM_GIB
  const ephScore = (toGiB(c.ephemeral_request) ?? 0) / LARGE_EPHEMERAL_GIB
  return cpuScore + memScore + ephScore
}

// Same wasteful/low-use/ok convention as CbjResourceAnalysisWidget (10%/30%
// thresholds) — one severity language across the whole Monitoring page,
// instead of a second, competing "large request" system. The large-request
// flags below are the FALLBACK signal only, for rows CloudWatch has no data
// for at all (which is most of them — that's the point of this tool).
const STATUS_STYLE: Record<string, { label: string; text: string; bg: string }> = {
  critical: { label: 'wasteful', text: 'text-red-700 dark:text-red-400', bg: 'bg-red-50/60 dark:bg-red-900/10' },
  warning: { label: 'low use', text: 'text-yellow-700 dark:text-yellow-400', bg: 'bg-yellow-50/60 dark:bg-yellow-900/10' },
  ok: { label: 'ok', text: 'ds-u-color--muted', bg: '' },
}

function pct(used: number | null | undefined, req: number): number | null {
  if (used == null || !req) return null
  return Math.round((used / req) * 100)
}

/** Compact "req/limit → used (pct%)" cell for one resource, colored by
 * CloudWatch status when known, else by the large-request fallback flag. */
function ResourceCell({
  req, limit, used, pctVal, large, status,
}: {
  req: string | null; limit: string | null; used: string | null; pctVal: number | null; large: boolean; status?: string | null
}) {
  const knownStatus = status && status !== 'unknown' ? STATUS_STYLE[status] : null
  const valueCls = knownStatus ? knownStatus.text : large ? 'text-amber-700 dark:text-amber-400' : 'text-gray-700 dark:text-gray-200'
  return (
    <div className="whitespace-nowrap">
      <span className={`font-medium ${large && !knownStatus ? 'font-semibold' : ''} ${large ? 'text-amber-700 dark:text-amber-400' : 'text-gray-700 dark:text-gray-200'}`}>
        {req ?? '—'} / {limit ?? '—'}
      </span>
      {used != null ? (
        <div className={`text-[11px] ${valueCls}`}>
          → {used} used {pctVal != null && `(${pctVal}%)`}
          {knownStatus && <span className="ml-1">· {knownStatus.label}</span>}
        </div>
      ) : (
        <div className="text-[11px] ds-u-color--muted italic">no recent data</div>
      )}
    </div>
  )
}

/** One short evidence link (last path segment, not the full nested job
 * path — that's what made this column unreadable) plus a plain "+N more". */
function JobLinks({ jobs }: { jobs: CbjPodTemplateJobRef[] }) {
  if (jobs.length === 0) return <span className="text-xs ds-u-color--muted">—</span>
  const first = jobs[0]
  const shortName = first.job.split('/').pop() || first.job
  const rest = jobs.length - 1
  return (
    <span className="text-xs ds-u-color--muted whitespace-nowrap">
      {first.url ? (
        <a
          href={first.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-cms-blue hover:underline inline-flex items-center gap-0.5"
          title={`Evidence: ${first.job} build #${first.build} console output`}
        >
          {shortName}
          {first.build != null && <span className="ds-u-color--muted"> #{first.build}</span>}
          <ExternalLink size={10} />
        </a>
      ) : (
        <>{shortName}</>
      )}
      {rest > 0 && <span className="ds-u-color--muted"> +{rest} more</span>}
    </span>
  )
}

/**
 * DMSC-479 — podTemplate config sweep. Configured CPU/memory/ephemeral-
 * storage request/limit read from the resolved pod YAML in each job's last
 * build (Pipeline, Multibranch, and Freestyle all covered; console log
 * primary, Replay fallback) — not CloudWatch, so it still catches jobs that
 * haven't run recently.
 *
 * Two distinct sections, not one blended list: "Confirmed wasteful" is a
 * flat, cross-validated leaderboard (CloudWatch has actually measured this
 * container's usage) — the real outreach target list. "Large requests, no
 * CloudWatch data" is a per-team browse of leads only — flagged by size
 * alone, because CloudWatch hasn't seen that container run recently.
 */
export default function CbjPodTemplateConfigWidget() {
  const [data, setData] = useState<CbjPodTemplateSweep | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sweeping, setSweeping] = useState(false)
  const [sweepProgress, setSweepProgress] = useState<{ done: number; total: number } | null>(null)
  const [showNoise, setShowNoise] = useState(false)
  const [flaggedOnly, setFlaggedOnly] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [confirmedExpanded, setConfirmedExpanded] = useState<Set<string>>(new Set())
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await getCbjPodTemplateConfig()
      setData(d)
    } catch {
      setError('Failed to load podTemplate config data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchData])

  const runSweep = async () => {
    const res = await startCbjPodTemplateSweep()
    if (!res.started && res.already_running) {
      setSweeping(true)
    } else if (res.started) {
      setSweeping(true)
      setSweepProgress({ done: 0, total: 0 })
    }

    pollRef.current = setInterval(async () => {
      const status = await getCbjPodTemplateSweepStatus()
      setSweepProgress({ done: status.done, total: status.total })
      if (!status.running) {
        if (pollRef.current) clearInterval(pollRef.current)
        setSweeping(false)
        setSweepProgress(null)
        fetchData()
      }
    }, 3000)
  }

  const toggle = (controller: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(controller)) next.delete(controller)
      else next.add(controller)
      return next
    })
  }

  const toggleConfirmed = (controller: string) => {
    setConfirmedExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(controller)) next.delete(controller)
      else next.add(controller)
      return next
    })
  }

  const results = data?.results ?? []
  const withErrors = results.filter((r) => r.error)
  const ok = results.filter((r) => !r.error)
  const withData = ok.filter((r) => r.containers.length > 0)
  const totalConfigs = withData.reduce((n, r) => n + r.containers.length, 0)
  const totalJobsMatched = withData.reduce((n, r) => n + (r.jobs_with_podtemplate ?? 0), 0)

  type Row = CbjPodTemplateContainer & { controller: string }
  const confirmedRows: Row[] = useMemo(
    () =>
      withData
        .flatMap((r) => r.containers.filter(isConfirmedWaste).map((c) => ({ ...c, controller: r.controller })))
        .filter((c) => showNoise || !NOISE_CONTAINERS.has((c.container || '').toLowerCase()))
        .sort((a, b) => (b.cw_status === 'critical' ? 1 : 0) - (a.cw_status === 'critical' ? 1 : 0) || cpuWasted(b) - cpuWasted(a)),
    [withData, showNoise],
  )
  const largeNoDataCount = withData.reduce((n, r) => n + r.containers.filter(isLargeNoData).length, 0)

  // Master-detail rollup: one row per team (total CPU wasted summed across
  // its confirmed-wasteful containers), not one row per container — the flat
  // per-container list ballooned to 800+ rows dominated by near-duplicate
  // configs (same container name, slightly different limits per job), which
  // buried the actual signal instead of surfacing it.
  interface TeamRollup { controller: string; totalWasted: number; criticalCount: number; warningCount: number; containers: Row[] }
  const confirmedByTeam: TeamRollup[] = useMemo(() => {
    const groups = new Map<string, Row[]>()
    for (const c of confirmedRows) {
      if (!groups.has(c.controller)) groups.set(c.controller, [])
      groups.get(c.controller)!.push(c)
    }
    return Array.from(groups.entries())
      .map(([controller, containers]) => ({
        controller,
        totalWasted: containers.reduce((sum, c) => sum + cpuWasted(c), 0),
        criticalCount: containers.filter((c) => c.cw_status === 'critical').length,
        warningCount: containers.filter((c) => c.cw_status === 'warning').length,
        containers: containers.sort((a, b) => cpuWasted(b) - cpuWasted(a)),
      }))
      .sort((a, b) => b.totalWasted - a.totalWasted)
  }, [confirmedRows])

  const controllerSeverity = (r: CbjPodTemplateControllerResult) => {
    const flagCount = r.containers.filter(isFlagged).length
    const maxSev = r.containers.reduce((m, c) => Math.max(m, severity(c)), 0)
    return flagCount * 10000 + maxSev
  }
  const sortedControllers = useMemo(() => [...withData].sort((a, b) => controllerSeverity(b) - controllerSeverity(a)), [withData])

  const refreshBtn = (
    <button
      onClick={runSweep}
      disabled={sweeping}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-60"
    >
      <RefreshCw size={13} className={sweeping ? 'animate-spin' : ''} />
      {sweeping
        ? sweepProgress && sweepProgress.total > 0
          ? `Sweeping ${sweepProgress.done}/${sweepProgress.total}...`
          : 'Sweeping...'
        : 'Run sweep'}
    </button>
  )

  return (
    <WidgetCard title="CBJ podTemplate Config — Prod East" icon={<FileCode2 size={14} />} action={refreshBtn} noPadding>
      <div className="px-5 pt-4 pb-3 border-b border-gray-100 dark:border-gray-700">
        {data?.swept_at ? (
          <div className="flex flex-wrap gap-2">
            <StatTile value={data.controller_count} label="Controllers" />
            <StatTile value={withData.length} label="With config" />
            <StatTile value={totalConfigs} label="Configs" />
            <StatTile value={totalJobsMatched} label="Jobs matched" />
            <StatTile value={confirmedRows.length} label="Confirmed wasteful" tone="red" />
            <StatTile value={largeNoDataCount} label="Large, no data" tone="amber" />
            {withErrors.length > 0 && <StatTile value={withErrors.length} label="Controllers failed" tone="amber" />}
          </div>
        ) : (
          <p className="text-xs ds-u-color--muted">Configured podTemplate CPU / memory / disk per prod-east controller, cross-checked against CloudWatch. Run a sweep to populate.</p>
        )}
        <div className="flex items-center gap-4 mt-2.5 text-[11px] ds-u-color--muted">
          <span>Last swept: <span className="text-gray-600 dark:text-gray-300">{fmtWhen(data?.swept_at)}</span></span>
          <button
            onClick={() => setShowHelp((v) => !v)}
            className="inline-flex items-center gap-1 hover:text-cms-blue transition-colors"
          >
            <Info size={12} /> How it works
            {showHelp ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        </div>
        {showHelp && (
          <div className="mt-3 space-y-2 text-xs ds-u-color--muted border-l-2 border-gray-100 dark:border-gray-700 pl-3">
            <p>
              <span className="font-semibold text-gray-600 dark:text-gray-300">Methodology</span> — configured CPU, memory, and
              ephemeral-storage request/limit, read from the resolved pod YAML the Kubernetes plugin logs to each build's console
              output — so it covers Pipeline, Multibranch, and Freestyle alike, and jobs that haven't run recently. Falls back to
              the Jenkinsfile text only when a build's console log has no such block.
            </p>
            <p>
              <span className="font-semibold text-gray-600 dark:text-gray-300">Cross-validation</span> — every row is checked live
              against CloudWatch's Used at Peak (same 7-day window as Build/Agent Containers).{' '}
              <span className="text-red-700 dark:text-red-400 font-medium">Confirmed wasteful</span> = CloudWatch has actually
              measured it running (real evidence). <span className="text-amber-700 dark:text-amber-400 font-medium">Large requests,
              no CloudWatch data</span> = flagged by size alone (CPU ≥{LARGE_CPU_CORES} cores, mem ≥{LARGE_MEM_GIB}Gi, or disk
              ≥{LARGE_EPHEMERAL_GIB}Gi) — a lead, not proof.
            </p>
            <p>
              <span className="font-semibold text-gray-600 dark:text-gray-300">Evidence</span> — every row links to the exact build
              and console output the numbers came from, so any finding can be verified in Jenkins before it goes to a team.
            </p>
          </div>
        )}
      </div>

      {error ? (
        <div className="p-5 text-sm text-red-600 text-center">{error}</div>
      ) : !data?.swept_at ? (
        loading ? (
          <div className="p-5 text-sm ds-u-color--muted text-center">Loading...</div>
        ) : (
          <div className="p-8 text-sm ds-u-color--muted text-center">
            No sweep has run yet. Click "Run sweep" above — this checks every prod-east controller and can
            take a few minutes.
          </div>
        )
      ) : (
        <>
          {confirmedByTeam.length > 0 && (
            <div className="border-b border-gray-100 dark:border-gray-700">
              <div className="px-5 pt-3 pb-1">
                <h3 className="text-xs font-semibold text-red-700 dark:text-red-400 uppercase tracking-wide">
                  Confirmed wasteful — cross-validated against CloudWatch ({confirmedByTeam.length} teams, {confirmedRows.length} containers)
                </h3>
                <p className="text-[11px] ds-u-color--muted mt-0.5">
                  One row per team, total CPU wasted summed across its confirmed-wasteful containers — worst
                  team first. Click to see the individual containers.
                </p>
              </div>
              <div className="divide-y divide-gray-50 dark:divide-gray-700">
                {confirmedByTeam.map((team) => {
                  const isOpen = confirmedExpanded.has(team.controller)
                  return (
                    <div key={team.controller}>
                      <button
                        onClick={() => toggleConfirmed(team.controller)}
                        className="w-full flex items-center justify-between px-5 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          {isOpen ? <ChevronDown size={14} className="ds-u-color--muted" /> : <ChevronRight size={14} className="ds-u-color--muted" />}
                          <span className="font-medium text-sm text-gray-800 dark:text-gray-100">{team.controller}</span>
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                            {team.totalWasted.toFixed(1)} cores wasted
                          </span>
                        </div>
                        <span className="text-xs ds-u-color--muted">
                          {team.containers.length} container{team.containers.length !== 1 ? 's' : ''}
                          {team.criticalCount > 0 && <span className="text-red-600 dark:text-red-400"> · {team.criticalCount} wasteful</span>}
                          {team.warningCount > 0 && <span className="text-yellow-600 dark:text-yellow-400"> · {team.warningCount} low use</span>}
                        </span>
                      </button>
                      {isOpen && (
                        <div className="px-5 pb-3 overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="text-left text-xs ds-u-color--muted border-b border-gray-100 dark:border-gray-700">
                                <th className="py-1.5 pr-3 font-medium">Container</th>
                                <th className="py-1.5 pr-3 font-medium">CPU (req/limit → used)</th>
                                <th className="py-1.5 pr-3 font-medium">Mem (req/limit → used)</th>
                                <th className="py-1.5 pr-3 font-medium">Disk req/limit</th>
                                <th className="py-1.5 pr-3 font-medium">Source</th>
                                <th className="py-1.5 pr-3 font-medium">Evidence</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                              {team.containers.map((c, i) => (
                                <tr key={i} className={STATUS_STYLE[c.cw_status as string]?.bg ?? ''}>
                                  <td className="py-2 pr-3 font-mono text-xs text-gray-700 dark:text-gray-200 whitespace-nowrap align-top">{c.container ?? '—'}</td>
                                  <td className="py-2 pr-3 align-top">
                                    <ResourceCell
                                      req={c.cpu_request} limit={c.cpu_limit}
                                      used={c.cw_cpu_used_at_peak_cores != null ? c.cw_cpu_used_at_peak_cores.toFixed(2) : null}
                                      pctVal={pct(c.cw_cpu_used_at_peak_cores, toCores(c.cpu_request))}
                                      large={isLargeCpu(c.cpu_request)}
                                      status={c.cw_status}
                                    />
                                  </td>
                                  <td className="py-2 pr-3 align-top">
                                    <ResourceCell
                                      req={c.mem_request} limit={c.mem_limit}
                                      used={c.cw_mem_used_at_peak_gb != null ? `${cwGbToGiB(c.cw_mem_used_at_peak_gb)!.toFixed(1)}Gi` : null}
                                      pctVal={pct(cwGbToGiB(c.cw_mem_used_at_peak_gb), toGiB(c.mem_request) ?? 0)}
                                      large={isLargeMem(c.mem_request)}
                                    />
                                  </td>
                                  <td className={`py-2 pr-3 whitespace-nowrap align-top ${isLargeEphemeral(c.ephemeral_request) ? 'text-amber-700 dark:text-amber-400 font-semibold' : 'text-gray-600 dark:text-gray-300'}`}>
                                    {c.ephemeral_request ?? '—'} / {c.ephemeral_limit ?? '—'}
                                  </td>
                                  <td className="py-2 pr-3 align-top">{sourceBadge(c.source)}</td>
                                  <td className="py-2 pr-3 align-top"><JobLinks jobs={c.jobs} /></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className="px-5 pt-3 pb-1">
            <h3 className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wide">
              Large requests, no CloudWatch data — browse by team
            </h3>
            <p className="text-[11px] ds-u-color--muted mt-0.5">
              These containers haven't run in CloudWatch's lookback window, so there's nothing to cross-check
              yet — leads worth a look, not confirmed waste.
            </p>
          </div>
          <div className="px-5 py-2 flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-gray-100 dark:border-gray-700">
            <label className="flex items-center gap-2 text-xs ds-u-color--muted">
              <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
              Only teams with a lead
            </label>
            <label className="flex items-center gap-2 text-xs ds-u-color--muted">
              <input type="checkbox" checked={showNoise} onChange={(e) => setShowNoise(e.target.checked)} />
              Show jnlp / system sidecars
            </label>
          </div>

          <div className="divide-y divide-gray-50 dark:divide-gray-700">
            {sortedControllers
              .filter((r) => !flaggedOnly || r.containers.some(isLargeNoData))
              .map((r) => {
                const isOpen = expanded.has(r.controller)
                const flagCount = r.containers.filter(isLargeNoData).length
                // Exclude anything already confirmed via CloudWatch — those
                // belong exclusively to the section above. Without this, a
                // container like terragrunt (confirmed wasteful) leaked into
                // both sections showing the identical numbers twice.
                const visibleContainers = r.containers
                  .filter((c) => !isConfirmedWaste(c))
                  .filter((c) => showNoise || !NOISE_CONTAINERS.has((c.container || '').toLowerCase()))
                  .sort((a, b) => severity(b) - severity(a))
                return (
                  <div key={r.controller}>
                    <button
                      onClick={() => toggle(r.controller)}
                      className="w-full flex items-center justify-between px-5 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        {isOpen ? <ChevronDown size={14} className="ds-u-color--muted" /> : <ChevronRight size={14} className="ds-u-color--muted" />}
                        <span className="font-medium text-sm text-gray-800 dark:text-gray-100">{r.controller}</span>
                        {flagCount > 0 && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                            {flagCount} lead{flagCount !== 1 ? 's' : ''}
                          </span>
                        )}
                      </div>
                      <span className="text-xs ds-u-color--muted">
                        {r.containers.length} config{r.containers.length !== 1 ? 's' : ''} ·{' '}
                        {r.jobs_with_podtemplate ?? 0} jobs matched
                        {r.jobs_unresolved && r.jobs_unresolved.length > 0 && (
                          <span className="text-amber-600 dark:text-amber-400"> · {r.jobs_unresolved.length} unresolved</span>
                        )}
                        {r.jobs_library_delegated && r.jobs_library_delegated.length > 0 && (
                          <span className="text-amber-600 dark:text-amber-400"> · {r.jobs_library_delegated.length} delegated, no log</span>
                        )}
                      </span>
                    </button>
                    {isOpen && (
                      <div className="px-5 pb-3 overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-xs ds-u-color--muted border-b border-gray-100 dark:border-gray-700">
                              <th className="py-1.5 pr-3 font-medium">Container</th>
                              <th className="py-1.5 pr-3 font-medium">CPU (req/limit → used)</th>
                              <th className="py-1.5 pr-3 font-medium">Mem (req/limit → used)</th>
                              <th className="py-1.5 pr-3 font-medium">Disk req/limit</th>
                              <th className="py-1.5 pr-3 font-medium">Source</th>
                              <th className="py-1.5 pr-3 font-medium">Evidence</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                            {visibleContainers.map((c, i) => {
                              const rowBg = c.cw_status && c.cw_status !== 'unknown'
                                ? STATUS_STYLE[c.cw_status]?.bg ?? ''
                                : isFlagged(c) ? 'bg-amber-50/40 dark:bg-amber-900/10' : ''
                              return (
                                <tr key={i} className={rowBg}>
                                  <td className="py-2 pr-3 font-mono text-xs text-gray-700 dark:text-gray-200 whitespace-nowrap align-top">{c.container ?? '—'}</td>
                                  <td className="py-2 pr-3 align-top">
                                    <ResourceCell
                                      req={c.cpu_request} limit={c.cpu_limit}
                                      used={c.cw_cpu_used_at_peak_cores != null ? c.cw_cpu_used_at_peak_cores.toFixed(2) : null}
                                      pctVal={pct(c.cw_cpu_used_at_peak_cores, toCores(c.cpu_request))}
                                      large={isLargeCpu(c.cpu_request)}
                                      status={c.cw_status}
                                    />
                                  </td>
                                  <td className="py-2 pr-3 align-top">
                                    <ResourceCell
                                      req={c.mem_request} limit={c.mem_limit}
                                      used={c.cw_mem_used_at_peak_gb != null ? `${cwGbToGiB(c.cw_mem_used_at_peak_gb)!.toFixed(1)}Gi` : null}
                                      pctVal={pct(cwGbToGiB(c.cw_mem_used_at_peak_gb), toGiB(c.mem_request) ?? 0)}
                                      large={isLargeMem(c.mem_request)}
                                    />
                                  </td>
                                  <td className={`py-2 pr-3 whitespace-nowrap align-top ${isLargeEphemeral(c.ephemeral_request) ? 'text-amber-700 dark:text-amber-400 font-semibold' : 'text-gray-600 dark:text-gray-300'}`}>
                                    {c.ephemeral_request ?? '—'} / {c.ephemeral_limit ?? '—'}
                                  </td>
                                  <td className="py-2 pr-3 align-top">{sourceBadge(c.source)}</td>
                                  <td className="py-2 pr-3 align-top"><JobLinks jobs={c.jobs} /></td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                        {r.jobs_unresolved && r.jobs_unresolved.length > 0 && (
                          <p className="text-xs ds-u-color--muted mt-2">
                            Unresolved (had a source but no explicit resources set — often relying on the
                            cluster default): {r.jobs_unresolved.slice(0, 5).join(', ')}
                            {r.jobs_unresolved.length > 5 ? `, and ${r.jobs_unresolved.length - 5} more` : ''}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
          </div>
        </>
      )}
    </WidgetCard>
  )
}
