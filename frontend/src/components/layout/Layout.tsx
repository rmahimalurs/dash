import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { UsaBanner } from '@cmsgov/design-system'
import Sidebar from './Sidebar'
import NotificationPanel from './NotificationPanel'
import WhatsNewModal from './WhatsNewModal'
import { getHealth } from '../../api/client'

const PAGE_TITLES: Record<string, string> = {
  '/':            'Dashboard',
  '/maintenance': 'Maintenance',
  '/jira':        'Jira',
  '/automation':  'Automation',
  '/monitoring':  'Monitoring',
  '/github':      'GitHub',
  '/manual':      'Manual',
  '/profile':     'Profile',
}

export default function Layout() {
  const location = useLocation()
  const pageTitle = PAGE_TITLES[location.pathname] ?? 'DevOps Dashboard'

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem('sidebar-collapsed') === 'true' }
    catch { return false }
  })

  // From the backend rather than the build, so the footer shows the version the
  // release notes belong to.
  const [version, setVersion] = useState('')
  useEffect(() => {
    let cancelled = false
    getHealth()
      .then(h => { if (!cancelled && h.version) setVersion(h.version) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  const toggleSidebar = () => {
    setCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem('sidebar-collapsed', String(next)) } catch {}
      return next
    })
  }

  return (
    <div className="app-shell min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="app-wave-lines" aria-hidden="true" />
      <UsaBanner className="cms-banner cms-banner--compact" />

      {/* Main content — shifts with sidebar */}
      <div className="flex min-h-[calc(100vh-2.25rem)]">
        <Sidebar collapsed={collapsed} onToggle={toggleSidebar} />

        <div className="flex min-w-0 flex-1 flex-col">

        {/* Top bar */}
        <header className="sticky top-0 z-20 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{pageTitle}</h1>
            <p className="text-xs ds-u-color--muted mt-0.5">CMS Cloud Platform — DevOps Team</p>
          </div>

          <div className="flex items-center gap-3">
            <NotificationPanel />
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>

        <WhatsNewModal />

        <footer className="relative z-10 px-6 py-3 border-t border-gray-100/70 dark:border-gray-700/70 bg-white/50 dark:bg-gray-800/50 backdrop-blur-sm">
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs ds-u-color--muted">
              CMS DevOps Dashboard &mdash; Internal Use Only
            </p>
            {version && (
              <p className="text-xs ds-u-color--muted font-mono" title={`Deployed version ${version}`}>
                v{version}
              </p>
            )}
          </div>
        </footer>
      </div>
    </div>
    </div>
  )
}
