import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2 } from 'lucide-react'
import { getGitHubStatus, type GitHubStatus } from '../../api/client'

const POLL_MS = 5 * 60 * 1000

export default function GitHubStatusBanner() {
  const [status, setStatus] = useState<GitHubStatus | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const s = await getGitHubStatus()
        if (!cancelled) { setStatus(s); setFailed(false) }
      } catch {
        if (!cancelled) setFailed(true)
      }
    }
    load()
    const id = setInterval(load, POLL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  if (!status && !failed) {
    return (
      <div className="flex items-center gap-1.5 text-xs ds-u-color--muted">
        <Loader2 size={12} className="animate-spin" /> Checking githubstatus.com…
      </div>
    )
  }

  if (failed || !status || status.error) {
    return (
      <p className="text-xs ds-u-color--muted">
        Could not reach{' '}
        <a href="https://www.githubstatus.com" target="_blank" rel="noopener noreferrer" className="underline">
          githubstatus.com
        </a> just now — this page isn't currently tracking a GitHub outage, but that's a check failure, not a report that GitHub is down.
      </p>
    )
  }

  const allClear = status.indicator === 'none'
  const tone = allClear
    ? 'bg-green-50 border-green-200 text-green-800'
    : status.indicator === 'critical' || status.indicator === 'major'
      ? 'bg-red-50 border-red-200 text-red-900'
      : 'bg-amber-50 border-amber-200 text-amber-900'

  if (allClear) {
    return (
      <div className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${tone}`}>
        <CheckCircle2 size={13} className="flex-shrink-0" />
        <span>
          GitHub status: <strong>{status.description}</strong> — checked every 5 min, alerts to{' '}
          <span className="font-mono">#cms-cloud-devops-internal</span> on any change.
        </span>
        <a href={status.url} target="_blank" rel="noopener noreferrer" className="underline inline-flex items-center gap-0.5 ml-auto">
          githubstatus.com <ExternalLink size={10} />
        </a>
      </div>
    )
  }

  return (
    <div className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-xs ${tone}`}>
      <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
      <div className="space-y-1">
        <p className="font-semibold">
          GitHub: {status.description}
        </p>
        {status.degraded.length > 0 && (
          <p>{status.degraded.map(c => `${c.name} (${c.label})`).join(', ')}</p>
        )}
        {status.incidents.length > 0 && (
          <ul className="space-y-0.5">
            {status.incidents.map(i => (
              <li key={i.shortlink}>
                <a href={i.shortlink} target="_blank" rel="noopener noreferrer"
                   className="underline font-medium inline-flex items-center gap-1">
                  {i.name} <ExternalLink size={10} />
                </a>
              </li>
            ))}
          </ul>
        )}
        <a href={status.url} target="_blank" rel="noopener noreferrer"
           className="underline inline-flex items-center gap-1">
          githubstatus.com <ExternalLink size={10} />
        </a>
      </div>
    </div>
  )
}
