import { ExternalLink, UserPlus, BookOpen, Key, Users } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const LINKS = [
  {
    label: 'Onboarding Guide',
    url: 'https://confluenceent.cms.gov/spaces/COM/pages/1398776431/CMS+Cloud+DevOps+-+New+Engineer+Onboarding',
    icon: <BookOpen size={13} />,
    desc: 'New team member setup',
  },
  {
    label: 'Access Request',
    url: 'https://eua.cms.gov',
    icon: <Key size={13} />,
    desc: 'Tool access provisioning',
  },
  {
    label: 'Team Directory',
    url: 'https://confluenceent.cms.gov/spaces/COM/pages/896286750/Task+Area+9+DevSecOps+Tooling+MAG+Support',
    icon: <Users size={13} />,
    desc: 'DMSC team contacts',
  },
]

export default function OnboardingWidget() {
  return (
    <WidgetCard
      title="Onboarding"
      icon={<UserPlus size={14} />}
      action={
        <a
          href="https://confluenceent.cms.gov/spaces/COM/pages/1398776431/CMS+Cloud+DevOps+-+New+Engineer+Onboarding"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          View guide
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
            <span className="link-card__icon">
              {link.icon}
            </span>
            <div className="link-card__label">
              <p className="font-medium">
                {link.label}
              </p>
              <p className="text-xs ds-u-color--muted">{link.desc}</p>
            </div>
            <ExternalLink size={11} className="link-card__external-icon" />
          </a>
        ))}
      </div>
      <AuthRequired />
    </WidgetCard>
  )
}
