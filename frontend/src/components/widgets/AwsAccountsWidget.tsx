import { ExternalLink, Cloud } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const CLOUDTAMER_BASE = 'https://cloudtamer.cms.gov'

interface AccountLink {
  label: string
  url: string
  group: string
}

const ACCOUNTS: AccountLink[] = [
  { group: 'Jenkins', label: 'Jenkins Dev',              url: `${CLOUDTAMER_BASE}/portal/project/155` },
  { group: 'Jenkins', label: 'Jenkins Prod',             url: `${CLOUDTAMER_BASE}/portal/project/156` },
  { group: 'Jenkins', label: 'Jenkins Gov Cloud Prod',   url: `${CLOUDTAMER_BASE}/portal/project/273` },
  { group: 'Jenkins', label: 'Jenkins Gov Cloud Dev',    url: `${CLOUDTAMER_BASE}/portal/project/274` },
  { group: 'JFrog / SonarQube', label: 'JFrog / SonarQube Prod', url: `${CLOUDTAMER_BASE}/portal/account/369` },
  { group: 'JFrog / SonarQube', label: 'JFrog / SonarQube Dev',  url: `${CLOUDTAMER_BASE}/portal/account/363` },
]

const GROUPS = [...new Set(ACCOUNTS.map((a) => a.group))]

export default function AwsAccountsWidget() {
  return (
    <WidgetCard
      title="AWS Accounts"
      icon={<Cloud size={14} />}
      action={
        <a
          href={CLOUDTAMER_BASE}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          CloudTamer
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-3">
        {GROUPS.map((group) => (
          <div key={group}>
            <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wider px-2.5 mb-1">
              {group}
            </p>
            {ACCOUNTS.filter((a) => a.group === group).map((account) => (
              <a
                key={account.url}
                href={account.url}
                target="_blank"
                rel="noopener noreferrer"
                className="link-card link-card--borderless"
              >
                <Cloud size={13} className="link-card__icon" />
                <span className="link-card__label">
                  {account.label}
                </span>
                <ExternalLink size={11} className="link-card__external-icon" />
              </a>
            ))}
          </div>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
