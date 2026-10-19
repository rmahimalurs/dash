/**
 * The monthly maintenance window, defined once.
 *
 * Maintenance runs on the **third Saturday** of the month, which is always the
 * Saturday falling in the third week: the first Saturday lands on day 1-7, so
 * the third lands on day 15-21.
 *
 * The window starts at 9 AM ET and no longer crosses midnight, so none of the
 * end times need a day rollover:
 *
 * - ITC / MGGD outage window: 09:00 to 13:00 (4 hours)
 * - Datadog downtime: 09:00 to 14:00 (5 hours), one hour past the outage so
 *   monitors stay silenced while the team verifies.
 *
 * These mirror the backend `get_next_maintenance_date` (jira_service.py) so the
 * modals pre-fill the same date the tickets use. An admin date override set on
 * the Admin page wins over the computed date; it is applied server-side, so
 * nothing here needs to know about it.
 */

export const MAINT_START_TIME = '09:00'
export const MAINT_END_TIME = '13:00'
export const MAINT_DOWNTIME_END_TIME = '14:00'

export const MAINT_START_LABEL = '9:00 AM'
export const MAINT_END_LABEL = '1:00 PM'
export const MAINT_WINDOW_LABEL = '3rd Saturday, 9 AM → 1 PM ET'
export const MAINT_DOWNTIME_WINDOW_LABEL = '3rd Saturday, 9 AM → 2 PM ET'

/** "09:00" -> "9:00 AM". The forms show the window in prose next to the
 *  datetimes they submit, and that prose has to follow an admin time override
 *  rather than a constant. */
export function to12Hour(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return hhmm
  const suffix = h < 12 ? 'AM' : 'PM'
  const hour12 = h % 12 === 0 ? 12 : h % 12
  return `${hour12}:${String(m).padStart(2, '0')} ${suffix}`
}

export function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** The third Saturday of the given month (month0 is 0-indexed). */
export function thirdSaturday(year: number, month0: number): Date {
  const firstSat = 1 + ((6 - new Date(year, month0, 1).getDay() + 7) % 7)
  return new Date(year, month0, firstSat + 14)
}

/** Third Saturday of this month, or next month's once it has passed. */
export function nextMaintenanceDate(): string {
  const today = new Date()
  const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const third = thirdSaturday(today.getFullYear(), today.getMonth())
  if (todayMidnight <= third) return isoDate(third)
  const nextMonth = today.getMonth() === 11 ? 0 : today.getMonth() + 1
  const nextYear = today.getMonth() === 11 ? today.getFullYear() + 1 : today.getFullYear()
  return isoDate(thirdSaturday(nextYear, nextMonth))
}
