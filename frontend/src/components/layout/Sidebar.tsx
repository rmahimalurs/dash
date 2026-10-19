import { useState, useEffect, useRef } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Wrench, Ticket, User, LogOut, ShieldCheck, ChevronLeft, ChevronRight, Phone, Zap, BookOpen, Activity, Github, Moon, Sun } from 'lucide-react'
import { useAuth, useDarkMode } from '../../App'
import { getOncall, OncallInfo } from '../../api/client'

interface NavItem {
  to: string
  icon: React.ReactNode
  label: string
}

const navItems: NavItem[] = [
  { to: '/',            icon: <LayoutDashboard size={18} />, label: 'Dashboard'   },
  { to: '/maintenance', icon: <Wrench size={18} />,          label: 'Maintenance' },
  { to: '/jira',        icon: <Ticket size={18} />,          label: 'Jira'        },
  { to: '/automation',  icon: <Zap size={18} />,             label: 'Automation'  },
  { to: '/monitoring',  icon: <Activity size={18} />,        label: 'Monitoring'  },
  { to: '/github',      icon: <Github size={18} />,          label: 'GitHub'      },
  { to: '/manual',      icon: <BookOpen size={18} />,        label: 'Manual'      },
]

function getInitials(name: string): string {
  return name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2)
}

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { user, logout } = useAuth()
  const { isDark, toggle } = useDarkMode()
  const navigate = useNavigate()
  const [oncall, setOncall] = useState<OncallInfo | null>(null)
  const [accountOpen, setAccountOpen] = useState(false)
  const accountRef = useRef<HTMLDivElement>(null)
  const accountTriggerRef = useRef<HTMLButtonElement>(null)
  const accountMenuItemsRef = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    if (!accountOpen) return

    const focusFrame = window.requestAnimationFrame(() => {
      accountMenuItemsRef.current[0]?.focus()
    })

    function handleOutsideClick(event: MouseEvent) {
      if (accountRef.current && !accountRef.current.contains(event.target as Node)) {
        setAccountOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      const menuItems = accountMenuItemsRef.current.filter(
        (item): item is HTMLButtonElement => item !== null,
      )
      const currentIndex = menuItems.indexOf(document.activeElement as HTMLButtonElement)

      if (event.key === 'Escape') {
        event.preventDefault()
        setAccountOpen(false)
        accountTriggerRef.current?.focus()
        return
      }

      if (currentIndex < 0 || menuItems.length === 0) return

      let nextIndex = currentIndex
      if (event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % menuItems.length
      if (event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + menuItems.length) % menuItems.length
      if (event.key === 'Home') nextIndex = 0
      if (event.key === 'End') nextIndex = menuItems.length - 1

      if (nextIndex !== currentIndex) {
        event.preventDefault()
        menuItems[nextIndex].focus()
      }
    }

    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [accountOpen])

  useEffect(() => {
    if (!user) return   // don't fetch when logged out
    let cancelled = false
    function fetch() {
      getOncall().then(d => { if (!cancelled) setOncall(d) }).catch(() => {})
    }
    fetch()
    const id = setInterval(fetch, 5 * 60 * 1000)
    return () => { cancelled = true; clearInterval(id) }
  }, [user?.username])

  return (
    <aside
      className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}
    >
      {/* Logo + collapse toggle */}
      <div className="sidebar__brand">
        <div className="sidebar__brand-content">
          <img
            src="/logo.png"
            alt="CMS Logo"
            className="sidebar__logo"
          />
          {!collapsed && (
            <div className="sidebar__brand-copy">
              <p className="sidebar__brand-name">DevOps</p>
              <p className="sidebar__brand-subtitle">Dashboard</p>
            </div>
          )}
        </div>

        <button
          onClick={onToggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          className="sidebar__toggle"
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="sidebar__nav">
        {!collapsed && (
          <p className="sidebar__section-label">
            Navigation
          </p>
        )}
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) =>
              `sidebar__link ${collapsed ? 'sidebar__link--collapsed' : ''} ${isActive ? 'sidebar__link--active' : ''}`
            }
          >
            <span className="sidebar__icon">{item.icon}</span>
            {!collapsed && <span className="sidebar__link-label">{item.label}</span>}
          </NavLink>
        ))}

        {user?.role === 'admin' && (
          <>
            {!collapsed && (
              <p className="sidebar__section-label sidebar__section-label--admin">
                Admin
              </p>
            )}
            <NavLink
              to="/admin"
              title={collapsed ? 'Admin' : undefined}
              className={({ isActive }) =>
                `sidebar__link ${collapsed ? 'sidebar__link--collapsed' : ''} ${isActive ? 'sidebar__link--active' : ''}`
              }
            >
              <span className="sidebar__icon"><ShieldCheck size={18} /></span>
              {!collapsed && <span className="sidebar__link-label">Admin</span>}
            </NavLink>
          </>
        )}
      </nav>

      {/* On-Call */}
      <div className="sidebar__oncall">
        {collapsed ? (
          <div
            title={oncall ? `On-call${oncall.primary.is_override ? ' (override)' : ''}: ${oncall.primary.display_name}` : 'On-call'}
            className="sidebar__oncall-collapsed"
          >
            <Phone size={16} color="#4ade80" />
            {oncall?.primary.is_override && (
              <span className="sidebar__override-dot" />
            )}
          </div>
        ) : (
          <div className="sidebar__oncall-content">
            <p className="sidebar__oncall-title sidebar__section-label">
              <Phone size={11} /> On-Call
            </p>
            {oncall ? (
              <div>
                <div className="sidebar__oncall-item">
                  <p className="sidebar__oncall-label">Now</p>
                  <p className="sidebar__oncall-name">
                    {oncall.primary.display_name}
                    {oncall.primary.is_override && (
                      <span className="sidebar__override-badge">OVR</span>
                    )}
                  </p>
                  {oncall.primary.until && (
                    <p className="sidebar__oncall-detail">
                      until {new Date(oncall.primary.until).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </p>
                  )}
                </div>
                {oncall.secondary.username && (
                  <div>
                  <p className="sidebar__oncall-label">Next</p>
                  <p className="sidebar__oncall-name">{oncall.secondary.display_name}</p>
                    {oncall.secondary.from && (
                      <p className="sidebar__oncall-detail">
                        from {new Date(oncall.secondary.from).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="sidebar__oncall-loading">Loading…</p>
            )}
          </div>
        )}
      </div>

      {/* Bottom section */}
      <div className="sidebar__bottom">
        {user && (
          <div className={`sidebar__account ${accountOpen ? 'sidebar__account--open' : ''}`} ref={accountRef}>
            <button
              type="button"
              ref={accountTriggerRef}
              onClick={() => setAccountOpen((open) => !open)}
              title={collapsed ? `${user.display_name || user.username} account menu` : undefined}
              aria-expanded={accountOpen}
              aria-haspopup="menu"
              aria-controls="sidebar-account-menu"
              className={`sidebar__user ${collapsed ? 'sidebar__user--collapsed' : ''}`}
            >
            <div className="sidebar__avatar">
              <span>
                {getInitials(user.display_name || user.username)}
              </span>
            </div>
              {!collapsed && (
                <div className="sidebar__user-copy">
                  <p className="sidebar__user-name">{user.display_name || user.username}</p>
                  <p className="sidebar__user-email">{user.email}</p>
                </div>
              )}
              {!collapsed && (
                <ChevronRight
                  size={14}
                  className={`sidebar__account-chevron ${accountOpen ? 'sidebar__account-chevron--open' : ''}`}
                />
              )}
            </button>

            {accountOpen && (
              <div id="sidebar-account-menu" className="sidebar__account-menu" role="menu" aria-label="Account menu">
                <button
                  type="button"
                  role="menuitem"
                  ref={(element) => { accountMenuItemsRef.current[0] = element }}
                  onClick={() => { setAccountOpen(false); navigate('/profile') }}
                  className="sidebar__account-menu-item"
                >
                  <User size={16} />
                  <span>Profile</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  ref={(element) => { accountMenuItemsRef.current[1] = element }}
                  onClick={() => {
                    setAccountOpen(false)
                    accountTriggerRef.current?.focus()
                    toggle()
                  }}
                  className="sidebar__account-menu-item"
                  title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                  {isDark ? <Sun size={16} /> : <Moon size={16} />}
                  <span>{isDark ? 'Light mode' : 'Dark mode'}</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  ref={(element) => { accountMenuItemsRef.current[2] = element }}
                  onClick={logout}
                  className="sidebar__account-menu-item sidebar__account-menu-item--signout"
                >
                  <LogOut size={16} />
                  <span>Sign out</span>
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
