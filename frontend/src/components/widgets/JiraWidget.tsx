import { ExternalLink, TicketCheck, PlusCircle } from 'lucide-react'
import WidgetCard, { AuthRequired } from './WidgetCard'

const JIRA_BASE = 'https://jiraent.cms.gov'
const PROJECT_KEY = 'DMSC'

const QUICK_LINKS = [
  { label: 'Active Sprint', url: `${JIRA_BASE}/secure/RapidBoard.jspa?rapidView=7118&projectKey=${PROJECT_KEY}&quickFilter=51231#` },
  { label: 'My Open Issues', url: `${JIRA_BASE}/issues/?jql=project+%3D+${PROJECT_KEY}+AND+assignee+%3D+currentUser()+AND+status+!%3D+Done` },
  { label: 'All Issues', url: `${JIRA_BASE}/projects/${PROJECT_KEY}/issues` },
  { label: 'Create Issue', url: `${JIRA_BASE}/secure/CreateIssue.jspa?pid=1&issuetype=10001` },
]

export default function JiraWidget() {
  return (
    <WidgetCard
      title="Jira (DMSC)"
      icon={<TicketCheck size={14} />}
      action={
        <a
          href={`${JIRA_BASE}/projects/${PROJECT_KEY}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          Open project
          <ExternalLink size={11} />
        </a>
      }
    >
      <div className="space-y-1.5">
        <p className="text-xs ds-u-color--muted mb-3">
          DMSC project — task tracking and on-call tickets
        </p>
        {QUICK_LINKS.map((link) => (
          <a
            key={link.label}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="link-card link-card--borderless"
          >
            <PlusCircle size={13} className="link-card__icon" />
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
