import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  BarChart3,
  ExternalLink,
  FileSpreadsheet,
  FolderGit2,
  Inbox,
  Loader2,
  Lock,
  RefreshCw,
  Ticket,
} from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCapabilities,
  getGitHubRepos,
  refreshGitHubCache,
  type GitHubCapabilities,
  type GitHubRepos,
  type GitHubRepo,
} from '../api/client'
import GitHubAccessRequests from '../components/widgets/GitHubAccessRequests'
import GitHubReporting from '../components/widgets/GitHubReporting'
import GitHubSelfServiceQueue from '../components/widgets/GitHubSelfServiceQueue'
import GitHubStatusBanner from '../components/widgets/GitHubStatusBanner'
import CopilotAnalytics from '../components/widgets/CopilotAnalytics'
import { RevealTile } from '../components/widgets/StatTile'

const AREA_LABELS: Record<string, string> = {
  repos: 'Repositories',
  members: 'Org members',
  copilot_seats: 'Copilot seats and usage',
  enterprise_audit_log: 'Enterprise audit log',
  consumed_licenses: 'Enterprise license consumption',
  dependabot_alerts: 'Dependabot alerts',
  secret_scanning: 'Secret scanning alerts',
  billing_usage: 'Actions minutes and billing',
  cost_centers: 'Cost center budgets',
  enterprise: 'Enterprise-wide reporting',
}

function RepoTable({ rows }: { rows: GitHubRepo[] }) {
  return (
    <div className="mt-4 rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
            <th className="text-left px-3 py-2 font-medium">Repository</th>
            <th className="text-left px-3 py-2 font-medium">Language</th>
            <th className="text-left px-3 py-2 font-medium">Open issues</th>
            <th className="text-left px-3 py-2 font-medium">Last push</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.name} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
              <td className="px-3 py-2">
                <a href={r.url} target="_blank" rel="noopener noreferrer"
                   className="text-xs font-medium text-cms-blue hover:underline">{r.name}</a>
                {r.is_team_repo && (
                  <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700">
                    ours
                  </span>
                )}
                {r.private && <span className="ml-1.5 text-[10px] ds-u-color--muted">private</span>}
              </td>
              <td className="px-3 py-2 text-xs ds-u-color--muted">{r.language || '—'}</td>
              <td className="px-3 py-2 text-xs ds-u-color--muted">{r.open_issues}</td>
              <td className="px-3 py-2 text-xs ds-u-color--muted">
                {r.pushed_days === 0 ? 'today' : `${r.pushed_days}d ago`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type TabId = 'requests' | 'tracker' | 'copilot' | 'repos' | 'reporting'

const TABS: { id: TabId; label: string; icon: ReactNode }[] = [
  { id: 'requests',  label: 'Access requests', icon: <Ticket size={14} /> },
  { id: 'tracker',   label: 'Ticket Tracker',  icon: <Inbox size={14} /> },
  { id: 'copilot',   label: 'Copilot',         icon: <BarChart3 size={14} /> },
  { id: 'repos',     label: 'Repositories',    icon: <FolderGit2 size={14} /> },
  { id: 'reporting', label: 'Reporting',       icon: <FileSpreadsheet size={14} /> },
]

export default function GitHubPage() {
  const [caps, setCaps] = useState<GitHubCapabilities | null>(null)
  const [repos, setRepos] = useState<GitHubRepos | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<TabId>('requests')
  const [showRecent, setShowRecent] = useState(false)
  const [showStale, setShowStale] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [c, r] = await Promise.all([
        getGitHubCapabilities(),
        getGitHubRepos(15),
      ])
      setCaps(c)
      setRepos(r)
    } catch (err: any) {
      setError(apiErrorMessage(err, 'Could not load GitHub data.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function hardRefresh() {
    setRefreshing(true)
    try {
      await refreshGitHubCache()
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  const locked = (caps?.locked ?? []).filter(k => k !== 'repos')

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 border-b border-gray-100 dark:border-gray-700">
        <div className="flex gap-1 overflow-x-auto">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
                tab === t.id
                  ? 'border-cms-blue text-cms-blue'
                  : 'border-transparent ds-u-color--muted hover:text-gray-800 dark:hover:text-gray-200'
              }`}
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>
        <button
          onClick={hardRefresh}
          disabled={refreshing || loading}
          className="mb-1.5 flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-gray-800 disabled:opacity-50"
        >
          <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Diagnostics and the status banner sit outside the tabs: they apply regardless of which one is open. */}
      <GitHubStatusBanner />

      {caps?.sso?.required && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-900">
          <AlertTriangle size={14} className="flex-shrink-0 mt-0.5 text-red-500" />
          <span>
            <strong>The token is not SSO-authorized for {caps.org}.</strong> Every private repository
            read fails with a 403 that names no scope, so the maintenance cards and this board cannot
            see anything.{' '}
            {caps.sso.authorization_url && (
              <a href={caps.sso.authorization_url} target="_blank" rel="noopener noreferrer"
                 className="underline font-medium">
                Authorize it
              </a>
            )}
          </span>
        </div>
      )}

      {locked.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900 space-y-2">
          <p className="flex items-center gap-2 font-semibold">
            <Lock size={13} /> Locked by token scope
          </p>
          <p>
            <span className="font-mono">{caps?.login}</span> holds enterprise owner rights, but the
            token configured here was granted only{' '}
            <span className="font-mono">{(caps?.scopes ?? []).join(', ') || 'no scopes'}</span>, so
            these areas return 403 or 404 rather than data:
          </p>
          <ul className="space-y-1">
            {locked.map(k => (
              <li key={k} className="flex items-baseline gap-2">
                <span className="text-amber-500">•</span>
                <span>
                  <strong>{AREA_LABELS[k] ?? k}</strong>
                  <span className="text-amber-700"> needs </span>
                  <span className="font-mono">{(caps?.areas?.[k]?.scopes_needed ?? []).join(' or ')}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="pt-1">
            Add{' '}
            <span className="font-mono">{(caps?.missing_scopes ?? []).join(', ')}</span>{' '}
            to the PAT and these sections light up with no further changes.
          </p>
        </div>
      )}

      {tab === 'requests' && <GitHubAccessRequests />}

      {tab === 'tracker' && <GitHubSelfServiceQueue />}

      {tab === 'copilot' && <CopilotAnalytics />}

      {tab === 'reporting' && <GitHubReporting />}

      {tab === 'repos' && (
        <>
          {loading && !repos && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-10 justify-center">
              <Loader2 size={15} className="animate-spin" /> Reading GitHub…
            </div>
          )}

          {repos && !repos.error && (repos.repos.length > 0 || (repos.stale_count ?? 0) > 0) && (
            <section>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <RevealTile
                  label={`Pushed in the last ${repos.recent_days_threshold ?? 30} days`}
                  value={repos.recent_count ?? repos.repos.length}
                  revealLabel={repos.repos.length > 0 ? `show the ${repos.repos.length} newest` : 'nothing pushed'}
                  disabled={repos.repos.length === 0}
                  open={showRecent}
                  onToggle={() => setShowRecent(v => !v)}
                />
                <RevealTile
                  label={`Stale (no push in ${Math.round((repos.stale_days_threshold ?? 365) / 365)}y+)`}
                  value={repos.stale_count ?? 0}
                  tone={(repos.stale_count ?? 0) > 0 ? 'text-amber-600' : 'text-gray-900 dark:text-gray-100'}
                  revealLabel={(repos.stale_count ?? 0) > 0 ? 'show the stale repositories' : 'nothing stale'}
                  disabled={(repos.stale_count ?? 0) === 0}
                  open={showStale}
                  onToggle={() => setShowStale(v => !v)}
                />
              </div>

              {showRecent && <RepoTable rows={repos.repos} />}
              {showStale && (
                <>
                  <RepoTable rows={repos.stale ?? []} />
                  {(repos.stale ?? []).length < (repos.stale_count ?? 0) && (
                    <p className="mt-1 text-[11px] ds-u-color--muted">
                      Showing the {(repos.stale ?? []).length} most abandoned of {repos.stale_count}.
                    </p>
                  )}
                </>
              )}
            </section>
          )}

          {repos?.error && (
            <p className="text-xs ds-u-color--muted">{repos.error}</p>
          )}
        </>
      )}

      <p className="text-[11px] ds-u-color--muted">
        Reads are cached for 5 minutes; Refresh clears the cache. The GitHub search API allows 30
        queries a minute, which the cache keeps us well inside.{' '}
        <a href={`https://github.com/${caps?.org ?? ''}`} target="_blank" rel="noopener noreferrer"
           className="text-cms-blue hover:underline inline-flex items-center gap-1">
          Open the org <ExternalLink size={10} />
        </a>
      </p>
    </div>
  )
}
