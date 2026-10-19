import { ExternalLink, BarChart2, Monitor } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const DD_BASE = 'https://app.ddog-gov.com'

const MONITORS = [
  { label: 'JFrog Monitors', url: `${DD_BASE}/monitors/manage?q=team%3Adevops+service%3A%22jfrog%22` },
  { label: 'SonarQube Monitors', url: `${DD_BASE}/monitors/manage?q=team%3Adevops+service%3A%22sonarqube%22` },
  { label: 'CloudBees CI Monitors', url: `${DD_BASE}/monitors/manage?q=team%3Adevops+service%3A%22jenkins%22` },
]

export default function DatadogWidget() {
  return (
    <WidgetCard
      title="Datadog Monitors"
      icon={<BarChart2 size={14} />}
      action={
        <a
          href={`${DD_BASE}/monitors/manage`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          Open Datadog
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1">
        {MONITORS.map((m) => (
          <a
            key={m.label}
            href={m.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <Monitor size={13} className="link-card__icon" />
            <span className="link-card__label">
              {m.label}
            </span>
            <ExternalLink size={11} className="link-card__external-icon" />
          </a>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
