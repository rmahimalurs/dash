import { ExternalLink, Cloud, Activity } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const AWS_REGION = 'us-east-1'
const CW_BASE = `https://console.aws.amazon.com/cloudwatch/home?region=${AWS_REGION}`

const DASHBOARDS = [
  { label: 'JFrog Artifactory — Dev', url: `${CW_BASE}#dashboards:name=JFrog-Dev` },
  { label: 'JFrog Artifactory — Prod', url: `${CW_BASE}#dashboards:name=JFrog-Prod` },
  { label: 'SonarQube — Dev', url: `${CW_BASE}#dashboards:name=SonarQube-Dev` },
  { label: 'SonarQube — Prod', url: `${CW_BASE}#dashboards:name=SonarQube-Prod` },
  { label: 'CloudBees CI — Dev', url: `${CW_BASE}#dashboards:name=CloudBees-Dev` },
  { label: 'CloudBees CI — Prod', url: `${CW_BASE}#dashboards:name=CloudBees-Prod` },
  { label: 'EKS Cluster Health', url: `${CW_BASE}#dashboards:name=EKS-Platform` },
  { label: 'All Dashboards', url: `${CW_BASE}#dashboards` },
]

export default function CloudWatchWidget() {
  return (
    <WidgetCard
      title="CloudWatch Dashboards"
      icon={<Cloud size={14} />}
      action={
        <a
          href={`${CW_BASE}#dashboards`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          All dashboards
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1">
        {DASHBOARDS.map((d) => (
          <a
            key={d.label}
            href={d.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <Activity size={13} className="link-card__icon" />
            <span className="link-card__label">
              {d.label}
            </span>
            <ExternalLink size={11} className="link-card__external-icon" />
          </a>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
