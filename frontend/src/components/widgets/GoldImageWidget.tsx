import { CalendarClock, ExternalLink } from 'lucide-react'
import WidgetCard from './WidgetCard'

// 2026 CMS Hybrid Cloud Gold Image release dates, from the published calendar.
// These are the "Gold Image Release-<Month> 2026" rows only (not the patch dates).
// Source: https://cloud.cms.gov/cms-hybrid-cloud-patching-gold-image-calendar-new/
const GOLD_IMAGE_RELEASES = [
  '2026-01-16', '2026-02-13', '2026-03-13', '2026-04-17', '2026-05-15', '2026-06-12',
  '2026-07-17', '2026-08-14', '2026-09-11', '2026-10-16', '2026-11-13', '2026-12-11',
]
const CALENDAR_URL = 'https://cloud.cms.gov/cms-hybrid-cloud-patching-gold-image-calendar-new/'

function fmtDate(iso: string): string {
  return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
}

function daysUntil(iso: string): number {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const d = new Date(iso + 'T12:00:00')
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  return Math.round((target.getTime() - today.getTime()) / 86_400_000)
}

function whenLabel(days: number): string {
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `in ${days} days`
}

function badgeClasses(days: number): string {
  if (days <= 3) return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
  if (days <= 10) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
  return 'bg-cms-blue-light text-cms-blue dark:bg-cms-blue/20'
}

export default function GoldImageWidget() {
  const upcoming = GOLD_IMAGE_RELEASES.filter(d => daysUntil(d) >= 0)
  const next = upcoming[0]
  const rest = upcoming.slice(1, 4)

  return (
    <WidgetCard
      title="Gold Image Releases"
      icon={<CalendarClock size={14} />}
      action={
        <a
          href={CALENDAR_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-cms-blue hover:underline"
        >
          2026 calendar <ExternalLink size={11} />
        </a>
      }
    >
      {next ? (
        <>
          <div className="mb-3">
            <p className="text-xs ds-u-color--muted uppercase tracking-wide mb-1">Next release</p>
            <div className="flex items-baseline gap-2 flex-wrap">
              <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{fmtDate(next)}</p>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${badgeClasses(daysUntil(next))}`}>
                {whenLabel(daysUntil(next))}
              </span>
            </div>
          </div>

          {rest.length > 0 && (
            <div className="border-t border-gray-100 dark:border-gray-700 pt-2.5">
              <p className="text-xs ds-u-color--muted uppercase tracking-wide mb-1.5">Upcoming</p>
              <div className="space-y-1">
                {rest.map(d => (
                  <div key={d} className="flex items-center justify-between text-sm">
                    <span className="text-gray-700 dark:text-gray-300">{fmtDate(d)}</span>
                    <span className="text-xs ds-u-color--muted">in {daysUntil(d)} days</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-sm ds-u-color--muted">
          All 2026 Gold Image releases have passed. See the{' '}
          <a href={CALENDAR_URL} target="_blank" rel="noopener noreferrer" className="text-cms-blue hover:underline">
            latest calendar
          </a>{' '}
          for the 2027 schedule.
        </p>
      )}
    </WidgetCard>
  )
}
