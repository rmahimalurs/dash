import { useState } from 'react'
import { ExternalLink, Link, LifeBuoy } from 'lucide-react'
import WidgetCard from './WidgetCard'

interface SupportLink {
  name: string
  url: string
  faviconUrl: string
  description: string
}

const SUPPORT_LINKS: SupportLink[] = [
  {
    name:        'CloudBees',
    url:         'https://app.cloudbees.com/~cmsvdc/home/',
    faviconUrl:  '/jenkins-favicon.webp',
    description: 'CloudBees Support Portal',
  },
  {
    name:        'Artifactory',
    url:         'https://support.jfrog.com/s/login/?language=en_US&ec=302&startURL=%2Fs%2F',
    faviconUrl:  '/jfrog-icon.png',
    description: 'JFrog Support Portal',
  },
  {
    name:        'SonarQube',
    url:         'https://auth.customer.sonarsource.com/u/login',
    faviconUrl:  'https://sonarqube.cloud.cms.gov/favicon.ico',
    description: 'SonarSource Customer Portal',
  },
  {
    name:        'Snyk',
    url:         'https://support.snyk.io/hc/en-us',
    faviconUrl:  'https://snyk.cms.gov/favicon.ico',
    description: 'Snyk Support Center',
  },
]

function ToolIcon({ src, name }: { src: string; name: string }) {
  const [errored, setErrored] = useState(false)
  if (errored) return <Link size={20} className="ds-u-color--muted" />
  return (
    <img
      src={src}
      alt={name}
      className="w-6 h-6 object-contain"
      onError={() => setErrored(true)}
    />
  )
}

export default function SupportWidget() {
  return (
    <WidgetCard title="DevOps Tools Support" icon={<LifeBuoy size={14} />}>
      <div className="flex flex-col gap-2">
        {SUPPORT_LINKS.map((link) => (
          <a
            key={link.name}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card"
          >
            <span className="flex-shrink-0 w-7 flex items-center justify-center">
              <ToolIcon src={link.faviconUrl} name={link.name} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium transition-colors">
                {link.name}
              </p>
              <p className="text-xs ds-u-color--muted truncate">{link.description}</p>
            </div>
            <ExternalLink size={12} className="link-card__external-icon" />
          </a>
        ))}
      </div>
    </WidgetCard>
  )
}
