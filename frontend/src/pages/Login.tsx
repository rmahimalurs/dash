import { useState, FormEvent, type ReactElement } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { AlertCircle, Loader2, LockKeyhole } from 'lucide-react'
import { Dropdown, type DropdownProps } from '@cmsgov/design-system'
import { login, apiErrorMessage } from '../api/client'
import { useAuth } from '../App'

const CmsDropdown = Dropdown as unknown as (props: DropdownProps) => ReactElement | null

// Restore alongside the area-card block in the markup below.
// const appAreas = [
//   { name: 'Build', description: 'Pipelines and source delivery', icon: Hammer },
//   { name: 'Deploy', description: 'Releases and environments', icon: Rocket },
//   { name: 'Monitor', description: 'Health and service visibility', icon: Activity },
//   { name: 'Secure', description: 'Access and platform controls', icon: ShieldCheck },
// ]

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [application, setApplication] = useState('DevOps')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setUser } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? '/'

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setError('')
    setLoading(true)
    try {
      const user = await login(username.trim(), password)
      setUser(user)
      navigate(from, { replace: true })
    } catch (err: unknown) {
      const response = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { status?: number; data?: { detail?: string } } }).response
        : undefined
      if (response?.status === 403) setError(apiErrorMessage({ response }, 'You are not authorized to access this application.'))
      // The server says more than "wrong password" on a 401 when AD named a
      // reason (locked, expired, disabled); hardcoding the generic text here
      // threw that away and sent people looking for a password problem.
      else if (response?.status === 401) setError(apiErrorMessage({ response }, 'Invalid username or password.'))
      else setError('Unable to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell login-shell min-h-screen bg-gray-50 dark:bg-gray-900">
      <main className="login-page">
        <div className="app-wave-lines" aria-hidden="true" />
        <div className="mx-auto flex w-full max-w-[1180px] flex-col items-stretch justify-center gap-8 md:flex-row md:gap-12">
        <section className="theme-card theme-card--login flex flex-1 flex-col justify-between rounded-[22px] px-8 py-10 sm:px-12 sm:py-12">
          <div>
            <img src="/logo.png" alt="CMS Cloud DevOps" className="mx-auto h-auto w-full max-w-none object-contain" />
            <div className="mt-9">
              <span className="rounded-full bg-white/10 px-4 py-2 text-xs font-semibold tracking-wide">Secure platform access</span>
              <h1 className="mt-7 max-w-xl text-5xl font-light leading-[1.05] tracking-tight sm:text-6xl">CMS DevOps <br/> Dashboard</h1>
              <p className="mt-6 max-w-xl text-base leading-7">
                Use your authorized CMS account to access platform operations, delivery workflows, monitoring, and security tools.
              </p>
            </div>
          </div>

        </section>

        <section className="theme-card theme-card--login flex w-full max-w-none flex-col rounded-[22px] px-8 py-10 sm:px-10 sm:py-12 md:max-w-[430px]">
          <div className="flex items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-[#0b2863]"><LockKeyhole size={20} /></span>
            <div>
              <h2 className="login-page__title text-2xl font-bold">Log in</h2>
              <p className="login-page__description mt-1 text-sm leading-6">Authentication is required before opening CMS Cloud DevOps workspaces.</p>
            </div>
          </div>

          {error && (
            <div className="login-page__error mt-6 flex items-start gap-2.5 rounded-lg border px-4 py-3">
              <AlertCircle size={16} className="mt-0.5 shrink-0" />
              <p className="text-sm">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <div>
              <label htmlFor="username" className="login-page__label mb-1 block text-sm font-medium">CMS User ID</label>
              <input id="username" type="text" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} className="login-page__input w-full rounded-md border px-3 py-2 text-sm outline-none transition" placeholder="Your EUA ID" disabled={loading} />
            </div>
            <div>
              <label htmlFor="password" className="login-page__label mb-1 block text-sm font-medium">Password</label>
              <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="login-page__input w-full rounded-md border px-3 py-2 text-sm outline-none transition" placeholder="••••••••" disabled={loading} />
            </div>
            <div>
              <CmsDropdown
                id="application"
                name="application"
                label="Select application"
                className="dropdown--compact"
                value={application}
                onChange={({ target }) => setApplication(target.value)}
                disabled={loading}
                options={[
                  { label: 'DevOps', value: 'DevOps' },
                  { label: 'Cloud AD', value: 'Cloud AD' },
                  { label: 'Github', value: 'Github' },
                ]}
              />
            </div>
            <button type="submit" disabled={loading || !username.trim() || !password} className="login-page__button mt-3 flex w-full items-center justify-center gap-2 rounded-full px-4 py-3 font-medium transition disabled:cursor-not-allowed disabled:opacity-50">
              {loading ? <><Loader2 size={16} className="animate-spin" /> Signing in...</> : 'Sign in'}
            </button>
          </form>

          {/* Build, Deploy, Monitor and Secure are design only: picking one
              changes the submit label and nothing else, so they are hidden
              until each area has somewhere to go. Restoring them needs this
              block, the appAreas constant, the lucide icon imports and the
              selectedArea state that drove the submit label. */}
          {/*
          <div className="mt-8 grid w-full grid-cols-1 gap-3">
            {appAreas.map(({ name, description, icon: Icon }) => (
              <button
                key={name}
                type="button"
                onClick={() => setSelectedArea(name)}
                className={`login-page__area-card w-full rounded-xl border px-3 py-3 text-left transition ${selectedArea === name ? 'is-selected' : ''}`}
              >
                <span className="flex items-center gap-2.5">
                  <Icon size={24} className="text-blue-200" />
                  <span>
                    <span className="block  font-semibold">{name}</span>
                    <span className="mt-1 block text-xs leading-4 text-blue-100/65">{description}</span>
                  </span>
                </span>
              </button>
            ))}
          </div>
          */}

          <p className="login-page__footer mt-8 text-center text-xs">Internal use only · CMS Cloud DevOps Team</p>
        </section>
        </div>
      </main>
    </div>
  )
}
