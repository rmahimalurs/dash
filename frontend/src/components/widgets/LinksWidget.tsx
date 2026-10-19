import { useState, useEffect } from 'react'
import { ExternalLink, RefreshCw, Link } from 'lucide-react'
import { Badge } from '@cmsgov/design-system'
import { getLinks } from '../../api/client'
import WidgetCard from './WidgetCard'

interface LinkItem {
  name: string
  env: string
  url: string
  faviconUrl: string
  category: string
}

interface ApiEntry {
  env: string
  url: string
  name?: string
}

const TOOL_FAVICONS: Record<string, string> = {
  cloudbees:      '/jenkins-favicon.webp',
  artifactory:    '/jfrog-icon.png',
  sonarqube:      'https://sonarqube.cloud.cms.gov/favicon.ico',
  jira:           'https://jiraent.cms.gov/favicon.ico',
  confluence:     'https://confluenceent.cms.gov/favicon.ico',
  akamai:         '/akamai-favicon.webp',
  snyk:           'https://snyk.cms.gov/favicon.ico',
  splunk:         'https://splunk.cloud.cms.gov/favicon.ico',
  password_reset: 'https://cloud-pwd.cms.gov/favicon.ico',
}

const TOOL_NAMES: Record<string, string> = {
  cloudbees:   'CloudBees',
  artifactory: 'Artifactory',
  sonarqube:   'SonarQube',
  jira:        'Jira',
  confluence:  'Confluence',
}

function environmentBadgeClass(environment: string): string {
  const normalized = environment.toLowerCase()
  if (normalized.includes('prod') || normalized === 'production') return 'ds-c-badge--prod'
  if (normalized.includes('dev')) return 'ds-c-badge--dev'
  return ''
}

// Links not derived from backend settings
const STATIC_LINKS: LinkItem[] = [
  { name: 'Password Reset', env: 'All',        url: 'https://cloud-pwd.cms.gov/SecureAuth10',                                                                                                        faviconUrl: TOOL_FAVICONS.password_reset, category: 'password_reset' },
  { name: 'Akamai GTM',     env: 'Production', url: 'https://control.akamai.com/apps/auth/?TARGET_URL=Y29udHJvbC5ha2FtYWkuY29tL2FwcHMvaG9tZS1wYWdlLw==#/login',               faviconUrl: TOOL_FAVICONS.akamai,         category: 'akamai' },
  { name: 'Snyk',           env: 'Production', url: 'https://snyk.cms.gov/',                                                                                                       faviconUrl: TOOL_FAVICONS.snyk,           category: 'snyk' },
  { name: 'Splunk',         env: 'Production', url: 'https://splunk.cloud.cms.gov/en-US/account/login?return_to=%2Fen-US%2F',                                                      faviconUrl: TOOL_FAVICONS.splunk,         category: 'splunk' },
]

function ToolIcon({ src, name }: { src: string; name: string }) {
  const [errored, setErrored] = useState(false)
  if (errored) return <Link size={20} className="ds-u-color--muted" />
  return (
    <img
      src={src}
      alt={name}
      className="w-6 h-6 object-contain"
      onError={() => setErrored(true)}
    />
  )
}

export default function LinksWidget() {
  const [links, setLinks] = useState<LinkItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchLinks = async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true)
    else setLoading(true)
    try {
      const data = await getLinks() as unknown as Record<string, ApiEntry[]>
      const items: LinkItem[] = []
      for (const [tool, entries] of Object.entries(data)) {
        for (const entry of entries) {
          items.push({
            name:       entry.name ?? TOOL_NAMES[tool] ?? tool,
            env:        entry.env,
            url:        entry.url,
            faviconUrl: TOOL_FAVICONS[tool] ?? '',
            category:   tool,
          })
        }
      }
      setLinks([...items, ...STATIC_LINKS])
    } catch {
      setLinks(STATIC_LINKS)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { fetchLinks() }, [])

  const refreshBtn = (
    <button
      onClick={() => fetchLinks(true)}
      disabled={refreshing}
      className="flex items-center gap-1.5 text-xs ds-u-color--muted hover:text-cms-blue transition-colors px-2 py-1 rounded hover:bg-gray-50"
    >
      <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
      Refresh
    </button>
  )

  return (
    <WidgetCard title="Tools" icon={<ExternalLink size={14} />} action={refreshBtn}>
      {loading ? (
        <div className="grid grid-cols-2 gap-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 rounded-lg bg-gray-100 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {links.map((link) => (
            <a
              key={`${link.name}-${link.env}`}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="link-card"
            >
              <span className="flex-shrink-0 w-7 flex items-center justify-center">
                <ToolIcon src={link.faviconUrl} name={link.name} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="link-card__label font-medium truncate">
                  {link.name}
                </p>
                <Badge className={`${environmentBadgeClass(link.env)} ds-c-badge--xs mt-0.5`}>
                  {link.env}
                </Badge>
              </div>
              <ExternalLink size={12} className="link-card__external-icon" />
            </a>
          ))}
        </div>
      )}
    </WidgetCard>
  )
}
