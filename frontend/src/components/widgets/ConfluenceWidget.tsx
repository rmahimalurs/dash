import { ExternalLink, BookOpen, FileText } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const CONFLUENCE_BASE = 'https://confluenceent.cms.gov'
const SPACE_KEY = 'COM'

const QUICK_LINKS = [
  { label: 'COMET Space Home', url: `${CONFLUENCE_BASE}/display/${SPACE_KEY}` },
  { label: 'Runbooks', url: `${CONFLUENCE_BASE}/display/${SPACE_KEY}/Runbooks` },
  { label: 'Architecture Diagrams', url: `${CONFLUENCE_BASE}/display/${SPACE_KEY}/Architecture` },
  { label: 'Maintenance Procedures', url: `${CONFLUENCE_BASE}/display/${SPACE_KEY}/Maintenance` },
  { label: 'On-Call Guide', url: `${CONFLUENCE_BASE}/display/${SPACE_KEY}/On-Call` },
]

export default function ConfluenceWidget() {
  return (
    <WidgetCard
      title="Confluence — COMET"
      icon={<BookOpen size={14} />}
      action={
        <a
          href={`${CONFLUENCE_BASE}/display/${SPACE_KEY}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          Open space
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1.5">
        <p className="text-xs ds-u-color--muted mb-3">
          COMET space &mdash; documentation and runbooks
        </p>
        {QUICK_LINKS.map((link) => (
          <a
            key={link.label}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <FileText size={13} className="link-card__icon" />
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
