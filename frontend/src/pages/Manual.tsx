import { useMemo, useState } from 'react'
import {
  LayoutDashboard, Wrench, Ticket, Zap, ShieldCheck, User, BookOpen,
  Search, Info, HelpCircle,
} from 'lucide-react'
import { MANUAL, type ManualPage, type ManualTile } from '../data/manual'

// Page id → header icon. Mirrors the sidebar so the manual reads as a map of
// the app the engineer is already looking at.
const PAGE_ICONS: Record<string, React.ReactNode> = {
  dashboard: <LayoutDashboard size={18} />,
  maintenance: <Wrench size={18} />,
  jira: <Ticket size={18} />,
  automation: <Zap size={18} />,
  admin: <ShieldCheck size={18} />,
  profile: <User size={18} />,
}

const STATUS_BADGE: Record<NonNullable<ManualTile['status']>, { label: string; cls: string }> = {
  live: { label: 'Live', cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  'coming-soon': { label: 'Coming soon', cls: 'bg-gray-100 ds-u-color--muted dark:bg-gray-700' },
  admin: { label: 'Admin only', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
}

function tileMatches(t: ManualTile, q: string): boolean {
  const hay = `${t.name} ${t.what} ${t.why}`.toLowerCase()
  return hay.includes(q)
}

function filterManual(pages: ManualPage[], q: string): ManualPage[] {
  if (!q.trim()) return pages
  const needle = q.trim().toLowerCase()
  return pages
    .map(p => ({
      ...p,
      sections: p.sections
        .map(s => ({ ...s, tiles: s.tiles.filter(t => tileMatches(t, needle)) }))
        .filter(s => s.tiles.length > 0),
    }))
    .filter(p => p.sections.length > 0)
}

export default function Manual() {
  const [query, setQuery] = useState('')
  const pages = useMemo(() => filterManual(MANUAL, query), [query])
  const totalTiles = useMemo(
    () => MANUAL.reduce((n, p) => n + p.sections.reduce((m, s) => m + s.tiles.length, 0), 0),
    [],
  )

  return (
    <div className="max-w-4xl space-y-8">
      {/* Intro */}
      <div className="rounded-xl border border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-800 p-6">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-cms-blue/10 flex items-center justify-center shrink-0">
            <BookOpen size={20} className="text-cms-blue" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">DevOps Dashboard Manual</h2>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1 leading-relaxed">
              A reference to every page, section, and tile in the dashboard — what each one does and
              why it exists. The dashboard centralizes the DevOps team's recurring operations across
              JFrog Artifactory, CloudBees Jenkins, SonarQube, Active Directory, and Jira so they can
              be run safely and consistently from one place.
            </p>
            <p className="text-xs ds-u-color--muted mt-2">
              {totalTiles} tiles across {MANUAL.length} pages · use the search or the quick links below to jump.
            </p>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 ds-u-color--muted" />
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search tiles by name or what they do…"
          className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-cms-blue/40"
        />
      </div>

      {/* Quick links */}
      {!query.trim() && (
        <div className="flex flex-wrap gap-2">
          {MANUAL.map(p => (
            <a
              key={p.id}
              href={`#${p.id}`}
              className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:border-cms-blue/40 hover:text-cms-blue transition-colors"
            >
              <span className="ds-u-color--muted">{PAGE_ICONS[p.id]}</span>
              {p.title}
            </a>
          ))}
        </div>
      )}

      {/* Content */}
      {pages.length === 0 ? (
        <div className="text-center py-12 text-sm ds-u-color--muted">
          No tiles match “{query}”.
        </div>
      ) : (
        pages.map(page => (
          <section key={page.id} id={page.id} className="scroll-mt-24 space-y-5">
            <div className="flex items-center gap-2.5 pb-2 border-b border-gray-200 dark:border-gray-700">
              <span className="w-8 h-8 rounded-lg bg-cms-blue/10 text-cms-blue flex items-center justify-center">
                {PAGE_ICONS[page.id]}
              </span>
              <div className="flex items-baseline gap-2 flex-wrap">
                <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">{page.title}</h3>
                <code className="text-[11px] ds-u-color--muted">{page.route}</code>
              </div>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-300 -mt-2">{page.blurb}</p>

            {page.sections.map(section => (
              <div key={section.title} className="space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wide ds-u-color--muted">
                  {section.title}
                </h4>
                <div className="space-y-3">
                  {section.tiles.map(tile => (
                    <div
                      key={tile.name}
                      className="rounded-lg border border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-800 p-4"
                    >
                      <div className="flex items-center gap-2 flex-wrap mb-2">
                        <p className="text-sm font-semibold text-gray-800 dark:text-gray-100">{tile.name}</p>
                        {tile.status && (
                          <span className={`text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${STATUS_BADGE[tile.status].cls}`}>
                            {STATUS_BADGE[tile.status].label}
                          </span>
                        )}
                      </div>
                      <div className="space-y-2">
                        <p className="text-xs text-gray-600 dark:text-gray-300 flex gap-2">
                          <Info size={14} className="shrink-0 mt-0.5 text-cms-blue/70" />
                          <span><span className="font-medium text-gray-700 dark:text-gray-200">What it does — </span>{tile.what}</span>
                        </p>
                        <p className="text-xs text-gray-600 dark:text-gray-300 flex gap-2">
                          <HelpCircle size={14} className="shrink-0 mt-0.5 ds-u-color--muted" />
                          <span><span className="font-medium text-gray-700 dark:text-gray-200">Why — </span>{tile.why}</span>
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>
        ))
      )}
    </div>
  )
}
