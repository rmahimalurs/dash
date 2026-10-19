import { ExternalLink, Github, GitFork } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const GH_ENT = 'https://github.com/CMS-Enterprise'
const GH_ORG = 'https://github.com/CMSgov'

const REPOS = [
  { label: 'cmscloud-devops', url: `${GH_ENT}/cmscloud-devops`, desc: 'Platform infrastructure and deployments' },
  { label: 'dso-cjoc-casc', url: `${GH_ENT}/dso-cjoc-casc`, desc: 'CloudBees CJOC configuration as code' },
  { label: 'dso-contrl-casc', url: `${GH_ENT}/dso-contrl-casc`, desc: 'CloudBees Controller configuration as code' },
  { label: 'cms-cloud-devops-observibility', url: `${GH_ENT}/cms-cloud-devops-observibility`, desc: 'Datadog and CloudWatch observability' },
  { label: 'cmscloud-infra-jenkins-automation', url: `${GH_ORG}/cmscloud-infra-jenkins-automation`, desc: 'Jenkins infrastructure automation' },
  { label: 'snyk', url: `${GH_ORG}/snyk`, desc: 'Snyk security scanning configuration' },
]

export default function GithubWidget() {
  return (
    <WidgetCard
      title="GitHub Repos"
      icon={<Github size={14} />}
      action={
        <a
          href={GH_ENT}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          CMS-Enterprise org
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1">
        {REPOS.map((repo) => (
          <a
            key={repo.label}
            href={repo.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <GitFork size={13} className="link-card__icon" />
            <div className="link-card__label">
              <p className="font-medium font-mono truncate">
                {repo.label}
              </p>
              <p className="text-xs ds-u-color--muted truncate">{repo.desc}</p>
            </div>
            <ExternalLink size={11} className="link-card__external-icon" />
          </a>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
