import type { ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

export function StatTile({ label, value, sub, tone = 'text-gray-900 dark:text-gray-100' }: {
  label: string; value: string | number; sub?: ReactNode; tone?: string
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
      <p className="text-xs ds-u-color--muted">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${tone}`}>{value}</p>
      {sub && <p className="text-xs ds-u-color--muted mt-0.5">{sub}</p>}
    </div>
  )
}

/** A stat tile whose detail table only appears once the number is clicked. */
export function RevealTile({ label, value, revealLabel, open, onToggle, tone, disabled }: {
  label: string
  value: string | number
  revealLabel: string
  open: boolean
  onToggle: () => void
  tone?: string
  disabled?: boolean
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
      <p className="text-xs ds-u-color--muted">{label}</p>
      <p className={`text-2xl font-semibold mt-1 ${tone ?? 'text-gray-900 dark:text-gray-100'}`}>{value}</p>
      <button
        onClick={onToggle}
        disabled={disabled}
        className="mt-0.5 inline-flex items-center gap-1 text-xs text-cms-blue hover:underline disabled:ds-u-color--muted disabled:no-underline disabled:cursor-default"
      >
        {!disabled && (open ? <ChevronDown size={11} /> : <ChevronRight size={11} />)}
        {revealLabel}
      </button>
    </div>
  )
}
