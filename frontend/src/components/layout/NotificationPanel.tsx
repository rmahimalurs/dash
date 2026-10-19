import { useState, useEffect, useRef } from 'react'
import {
  Bell, X, AlertTriangle, AlertCircle, Info,
  ShieldAlert, KeyRound, FileWarning, PartyPopper, Compass, HardDrive, CalendarClock, Gauge, Github,
} from 'lucide-react'
import { getCertificates, getLicenses, getServiceAccounts, getPvcControllers, getTicketReadiness, getSonarQubeLoc, getCldsptQueue, getJFrogTokenExpiry, type TicketReadiness, type CldsptQueue, type JFrogTokenExpiry } from '../../api/client'
import { useAuth } from '../../App'
import type { Certificate, License, ServiceAccount, PvcControllerList, SonarQubeLoc } from '../../api/client'

interface Notification {
  id: string
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
  icon: React.ReactNode
}

const SEVERITY_ORDER = { critical: 0, warning: 1, info: 2 }

const STATIC_NOTIFICATIONS: Notification[] = [
  {
    id: 'static-welcome',
    severity: 'info',
    title: 'Welcome to DevOps Dashboard',
    description: 'Your central hub for CMS Cloud Platform tooling, certs, and on-call management.',
    icon: <PartyPopper size={14} />,
  },
  {
    id: 'static-tour',
    severity: 'info',
    title: 'Take a tour',
    description: 'Explore widgets for certificates, licenses, Jira, CloudWatch, Datadog, and more.',
    icon: <Compass size={14} />,
  },
]

// Scoped to the signed-in engineer. A reminder about someone else's queue is
// noise, so this returns nothing when the user is not in the swept roster.
function buildCldsptNotifications(queue: CldsptQueue, username: string | undefined): Notification[] {
  if (!username) return []
  const me = (queue.engineers ?? []).find(
    (e) => e.username.toUpperCase() === username.toUpperCase(),
  )
  if (!me || !me.open) return []
  const needsBo = me.bo_approval?.required ?? 0
  const tail = needsBo
    ? ` ${needsBo} still need${needsBo === 1 ? 's' : ''} a Business Owner approval request.`
    : ''
  const pending = me.buckets?.pending_approval ?? 0
  return [{
    id: `cldspt-open-${me.username}`,
    severity: pending > 0 ? 'warning' : 'info',
    title: `You have ${me.open} open GitHub access request${me.open === 1 ? '' : 's'}`,
    description:
      `${pending} of them ${pending === 1 ? 'is' : 'are'} waiting for approval.${tail}`.trim(),
    icon: <Github size={14} />,
  }]
}

function buildCertNotifications(certs: Certificate[]): Notification[] {
  return certs
    .filter((c) => c.status === 'warning' || c.status === 'critical')
    .map((c) => ({
      id: `cert-${c.tool}-${c.env}`,
      severity: c.status as 'warning' | 'critical',
      title: `${c.tool} certificate expiring${c.status === 'critical' ? ' soon' : ''}`,
      description: `${c.domain} (${c.env}) — ${c.days_remaining != null ? `${c.days_remaining}d remaining` : 'check expiry date'}`,
      icon: <FileWarning size={14} />,
    }))
}

function buildLicenseNotifications(licenses: License[]): Notification[] {
  return licenses
    .filter((l) => l.status === 'warning' || l.status === 'critical')
    .map((l) => ({
      id: `license-${l.tool}-${l.env}`,
      severity: l.status as 'warning' | 'critical',
      title: `${l.tool} license expiring${l.status === 'critical' ? ' critically soon' : ' soon'}`,
      description: `${l.env} — ${l.days_remaining != null ? `${l.days_remaining}d remaining` : l.notes ?? 'check expiry'}`,
      icon: <ShieldAlert size={14} />,
    }))
}

function buildSonarQubeLocNotifications(locs: SonarQubeLoc[]): Notification[] {
  return locs
    .filter((l) => l.status === 'warning' || l.status === 'critical')
    .map((l) => ({
      id: `sonarqube-loc-${l.tool}-${l.env}`,
      severity: l.status as 'warning' | 'critical',
      title: `SonarQube licensed LOC ${l.status === 'critical' ? 'critically high' : 'nearing cap'}`,
      description: `${l.env} — ${l.percent_used != null ? `${l.percent_used}% of ${l.cap?.toLocaleString() ?? 'the'} line cap` : 'check usage'}`,
      icon: <Gauge size={14} />,
    }))
}

function buildJFrogTokenNotifications(e: JFrogTokenExpiry): Notification[] {
  if (e.status === 'ok' || e.status === 'unknown') return []
  const days = e.days_remaining
  // Refreshing is one click, so the reminder says exactly which one.
  const action = e.can_refresh
    ? 'Open JFrog Automation and click Request and rotate'
    : 'Regenerate it on the JFrog user page, the refresh token is not configured'
  return [{
    id: `jfrog-entitlement-${e.expires_at ?? 'unknown'}`,
    severity: e.status === 'warning' ? 'warning' : 'critical',
    title: e.status === 'expired'
      ? 'JFrog entitlement token has expired'
      : 'JFrog entitlement token expiring',
    description: `${
      e.status === 'expired'
        ? 'Artifactory and Xray cannot pull images until it is replaced'
        : `${days}d remaining (${e.expires_at})`
    } — ${action}`,
    icon: <KeyRound size={14} />,
  }]
}

function buildServiceAccountNotifications(accounts: ServiceAccount[]): Notification[] {
  return accounts
    .filter((a) => a.status === 'warning' || a.status === 'critical' || a.status === 'expired')
    .map((a) => ({
      id: `sa-${a.username}`,
      severity: a.status === 'expired' ? 'critical' : (a.status as 'warning' | 'critical'),
      title: a.status === 'expired'
        ? `Service account password expired`
        : `Service account password expiring`,
      description: `${a.label} (${a.username}) — ${
        a.status === 'expired' ? 'expired' : a.days_remaining != null ? `${a.days_remaining}d remaining` : 'check expiry'
      }`,
      icon: <KeyRound size={14} />,
    }))
}

function buildMaintNotifications(r: TicketReadiness): Notification[] {
  if (!r.due) return []
  const when = `${r.days_until} day${r.days_until === 1 ? '' : 's'} to maintenance (${r.maint_date_str})`
  return [{
    id: `maint-tickets-${r.maint_date}`,
    severity: 'warning',
    title: r.prep_all_created ? 'Create the ITC & MGGD tickets' : 'Create the maintenance tickets',
    description: r.prep_all_created
      ? `Prep tickets are done — ${when}. Create the ITC and MGGD tickets.`
      : `${when}. Create the tool Prep tickets, then ITC/MGGD.`,
    icon: <CalendarClock size={14} />,
  }]
}

function buildPvcNotifications(list: PvcControllerList): Notification[] {
  if (list.error) return []
  const critPct = Math.round((list.thresholds?.crit ?? 0.8) * 100)
  const warnPct = Math.round((list.thresholds?.warn ?? 0.75) * 100)
  const over = (list.over ?? []).map((c) => ({
    id: `pvc-${c.namespace}`,
    severity: 'critical' as const,
    title: 'Controller PVC over threshold',
    description: `${c.controller} (${c.namespace}) — over ${critPct}% disk on its PVC`,
    icon: <HardDrive size={14} />,
  }))
  const approaching = (list.approaching ?? []).map((c) => ({
    id: `pvc-${c.namespace}`,
    severity: 'warning' as const,
    title: 'Controller PVC approaching threshold',
    description: `${c.controller} (${c.namespace}) — approaching ${warnPct}%`,
    icon: <HardDrive size={14} />,
  }))
  return [...over, ...approaching]
}

const SEVERITY_STYLES: Record<string, { row: string; icon: string; badge: string; label: string }> = {
  critical: {
    row:   'border-l-2 border-red-400 bg-red-50/60',
    icon:  'text-red-500',
    badge: 'bg-red-100 text-red-600',
    label: 'Critical',
  },
  warning: {
    row:   'border-l-2 border-amber-400 bg-amber-50/60',
    icon:  'text-amber-500',
    badge: 'bg-amber-100 text-amber-600',
    label: 'Warning',
  },
  info: {
    row:   'border-l-2 border-blue-300 bg-blue-50/40',
    icon:  'text-blue-400',
    badge: 'bg-blue-100 text-blue-600',
    label: 'Info',
  },
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'critical') return <AlertCircle size={13} className="text-red-500 flex-shrink-0" />
  if (severity === 'warning')  return <AlertTriangle size={13} className="text-amber-500 flex-shrink-0" />
  return <Info size={13} className="text-blue-400 flex-shrink-0" />
}

export default function NotificationPanel() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('dismissed-notifications') ?? '[]')) }
    catch { return new Set() }
  })
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    Promise.allSettled([getCertificates(), getLicenses(), getServiceAccounts(), getPvcControllers(), getTicketReadiness(), getSonarQubeLoc(), getCldsptQueue(), getJFrogTokenExpiry()])
      .then(([certsResult, licensesResult, accountsResult, pvcResult, readinessResult, locResult, cldsptResult, jfrogResult]) => {
        const certNotifs   = certsResult.status    === 'fulfilled' ? buildCertNotifications(certsResult.value)            : []
        const licenseNotifs = licensesResult.status === 'fulfilled' ? buildLicenseNotifications(licensesResult.value)      : []
        const saNotifs     = accountsResult.status  === 'fulfilled' ? buildServiceAccountNotifications(accountsResult.value) : []
        const pvcNotifs    = pvcResult.status       === 'fulfilled' ? buildPvcNotifications(pvcResult.value)              : []
        const maintNotifs  = readinessResult.status === 'fulfilled' ? buildMaintNotifications(readinessResult.value)      : []
        const locNotifs    = locResult.status       === 'fulfilled' ? buildSonarQubeLocNotifications(locResult.value)     : []

        const cldsptNotifs = cldsptResult.status === 'fulfilled' ? buildCldsptNotifications(cldsptResult.value, user?.username) : []
        const jfrogNotifs  = jfrogResult.status  === 'fulfilled' ? buildJFrogTokenNotifications(jfrogResult.value)          : []

        const all = [...cldsptNotifs, ...certNotifs, ...licenseNotifs, ...saNotifs, ...pvcNotifs, ...maintNotifs, ...locNotifs, ...jfrogNotifs, ...STATIC_NOTIFICATIONS]
          .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])

        setNotifications(all)
      })
  }, [user?.username])

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    if (open) document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  function dismiss(id: string) {
    setDismissed((prev) => {
      const next = new Set(prev).add(id)
      try { localStorage.setItem('dismissed-notifications', JSON.stringify([...next])) } catch {}
      return next
    })
  }

  function dismissAll() {
    const allIds = notifications.map((n) => n.id)
    setDismissed((prev) => {
      const next = new Set([...prev, ...allIds])
      try { localStorage.setItem('dismissed-notifications', JSON.stringify([...next])) } catch {}
      return next
    })
  }

  const visible   = notifications.filter((n) => !dismissed.has(n.id))
  const alertCount = visible.filter((n) => n.severity === 'critical' || n.severity === 'warning').length

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-full hover:bg-gray-100 transition-colors"
        aria-label="Notifications"
      >
        <Bell size={18} className="ds-u-color--muted" />
        {alertCount > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500">
            <span className="text-white text-[10px] font-bold leading-none px-0.5">{alertCount}</span>
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 w-96 bg-white rounded-xl shadow-lg border border-gray-200 z-50 flex flex-col max-h-[480px]">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <Bell size={14} className="ds-u-color--muted" />
              <span className="text-sm font-semibold text-gray-800">Notifications</span>
              {visible.length > 0 && (
                <span className="text-xs bg-gray-100 ds-u-color--muted rounded-full px-2 py-0.5 font-medium">
                  {visible.length}
                </span>
              )}
            </div>
            {visible.length > 0 && (
              <button
                onClick={dismissAll}
                className="text-xs ds-u-color--muted hover:text-gray-600 transition-colors"
              >
                Dismiss all
              </button>
            )}
          </div>

          {/* List */}
          <div className="overflow-y-auto flex-1">
            {visible.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center px-6">
                <Bell size={28} className="text-gray-200 mb-3" />
                <p className="text-sm font-medium ds-u-color--muted">All clear</p>
                <p className="text-xs text-gray-300 mt-1">No active notifications</p>
              </div>
            ) : (
              visible.map((n) => {
                const s = SEVERITY_STYLES[n.severity]
                return (
                  <div
                    key={n.id}
                    className={`flex items-start gap-3 px-4 py-3 ${s.row} border-b border-gray-100/80 last:border-b-0`}
                  >
                    <div className={`mt-0.5 flex-shrink-0 ${s.icon}`}>{n.icon}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <SeverityIcon severity={n.severity} />
                        <p className="text-xs font-semibold text-gray-800 truncate">{n.title}</p>
                      </div>
                      <p className="text-xs ds-u-color--muted leading-snug">{n.description}</p>
                    </div>
                    <button
                      onClick={() => dismiss(n.id)}
                      className="flex-shrink-0 text-gray-300 hover:ds-u-color--muted transition-colors mt-0.5"
                      aria-label="Dismiss"
                    >
                      <X size={13} />
                    </button>
                  </div>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
