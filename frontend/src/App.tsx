import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { getMe, logout as apiLogout, getMaintenanceMode, User } from './api/client'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Maintenance from './pages/Maintenance'
import Profile from './pages/Profile'
import Admin from './pages/Admin'
import Jira from './pages/Jira'
import Automation from './pages/Automation'
import Monitoring from './pages/Monitoring'
import GitHubPage from './pages/GitHub'
import Manual from './pages/Manual'
import UnderMaintenance from './pages/UnderMaintenance'

// ─── Dark Mode Context ────────────────────────────────────────────────────────

interface DarkModeContextValue {
  isDark: boolean
  toggle: () => void
}

export const DarkModeContext = createContext<DarkModeContextValue>({ isDark: false, toggle: () => {} })
export function useDarkMode() { return useContext(DarkModeContext) }

function DarkModeProvider({ children }: { children: React.ReactNode }) {
  const [isDark, setIsDark] = useState(() => {
    try {
      const stored = localStorage.getItem('dark-mode')
      if (stored !== null) return stored === 'true'
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    } catch { return false }
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    try { localStorage.setItem('dark-mode', String(isDark)) } catch {}
  }, [isDark])

  const toggle = useCallback(() => setIsDark((d) => !d), [])
  const value = useMemo(() => ({ isDark, toggle }), [isDark, toggle])

  return <DarkModeContext.Provider value={value}>{children}</DarkModeContext.Provider>
}

// ─── Auth Context ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  user: User | null
  setUser: (user: User | null) => void
  loading: boolean
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue>({
  user: null,
  setUser: () => {},
  loading: true,
  logout: async () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

// ─── Protected Route ──────────────────────────────────────────────────────────

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-cms-blue border-t-transparent rounded-full animate-spin" />
          <p className="text-sm ds-u-color--muted">Loading...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()

  if (loading) return null

  if (!user) return <Navigate to="/login" replace />

  if (user.role !== 'admin') return <Navigate to="/" replace />

  return <>{children}</>
}

// ─── Auth Provider ────────────────────────────────────────────────────────────

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getMe()
      .then((userData) => setUser(userData))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiLogout()
    } finally {
      setUser(null)
      window.location.href = '/login'
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, setUser, loading, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

// ─── Maintenance Gate ─────────────────────────────────────────────────────────
// When site maintenance mode is on, everyone except admins sees the Under
// Maintenance page. Admins pass through with a banner so they can turn it off.
// The /login route always renders so an admin can sign in during maintenance.

function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  const [maint, setMaint] = useState<{ enabled: boolean; message: string } | null>(null)

  useEffect(() => {
    getMaintenanceMode()
      .then(setMaint)
      .catch(() => setMaint({ enabled: false, message: '' }))
  }, [])

  if (maint === null || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Loader2 className="animate-spin ds-u-color--muted" size={22} />
      </div>
    )
  }

  const isAdmin = user?.role === 'admin'
  if (maint.enabled && !isAdmin && location.pathname !== '/login') {
    return <UnderMaintenance message={maint.message} />
  }

  return (
    <>
      {maint.enabled && isAdmin && (
        <div className="bg-amber-500 text-white text-center text-xs py-1.5 px-4 font-medium">
          Maintenance mode is ON — only admins can access the site. Turn it off in Admin.
        </div>
      )}
      {children}
    </>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      <DarkModeProvider>
      <AuthProvider>
        <MaintenanceGate>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="maintenance" element={<Maintenance />} />
            <Route path="jira" element={<Jira />} />
            <Route path="automation" element={<Automation />} />
            <Route path="monitoring" element={<Monitoring />} />
            <Route path="github" element={<GitHubPage />} />
            <Route path="manual" element={<Manual />} />
            <Route path="profile" element={<Profile />} />
            <Route
              path="admin"
              element={
                <AdminRoute>
                  <Admin />
                </AdminRoute>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </MaintenanceGate>
      </AuthProvider>
      </DarkModeProvider>
    </BrowserRouter>
  )
}
