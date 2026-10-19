import { ExternalLink, PhoneCall, Bell } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const VO_BASE = 'https://portal.victorops.com/client/cms-vdc'

const LINKS = [
  { label: 'Incident Console', url: `${VO_BASE}/#/incident-list`, icon: <Bell size={13} /> },
  { label: 'On-Call Schedule', url: `${VO_BASE}/#/on-call/schedule`, icon: <PhoneCall size={13} /> },
  { label: 'Escalation Policies', url: `${VO_BASE}/#/escalation-policies`, icon: <Bell size={13} /> },
  { label: 'Alerts', url: `${VO_BASE}/#/alerts`, icon: <Bell size={13} /> },
]

export default function VictorOpsWidget() {
  return (
    <WidgetCard
      title="VictorOps"
      icon={<PhoneCall size={14} />}
      action={
        <a
          href={VO_BASE}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          Open portal
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1">
        {LINKS.map((link) => (
          <a
            key={link.label}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <span className="link-card__icon">{link.icon}</span>
            <span className="link-card__label">
              {link.label}
            </span>
            <ExternalLink size={11} className="link-card__external-icon" />
          </a>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
