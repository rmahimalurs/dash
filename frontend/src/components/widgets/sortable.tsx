import { useMemo, useState, ReactNode } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react'

export type SortDir = 'asc' | 'desc'
export type Accessor<T> = (row: T) => string | number | null | undefined

/**
 * Generic client-side table sorting. `accessors` maps a column key to the value
 * to sort that column by. Empty/null values always sort last regardless of
 * direction (e.g. "never expires" / unknown rows stay at the bottom). Strings
 * compare with numeric-aware locale ordering; numbers compare numerically.
 *
 * Define `accessors` as a module-level constant for referential stability.
 */
export function useSort<T>(
  rows: T[],
  accessors: Record<string, Accessor<T>>,
  initial?: { key: string; dir?: SortDir },
) {
  const [sortKey, setSortKey] = useState<string | null>(initial?.key ?? null)
  const [sortDir, setSortDir] = useState<SortDir>(initial?.dir ?? 'asc')

  const toggle = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sorted = useMemo(() => {
    const get = sortKey ? accessors[sortKey] : undefined
    if (!get) return rows
    const dir = sortDir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = get(a)
      const vb = get(b)
      const na = va == null || va === ''
      const nb = vb == null || vb === ''
      if (na && nb) return 0
      if (na) return 1 // empties last
      if (nb) return -1
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir
    })
  }, [rows, sortKey, sortDir, accessors])

  return { sorted, sortKey, sortDir, toggle }
}

/** A clickable table header that renders the shared widget-table styling plus a sort indicator. */
export function SortableTh({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  className = '',
}: {
  label: ReactNode
  sortKey: string
  activeKey: string | null
  dir: SortDir
  onSort: (key: string) => void
  className?: string
}) {
  const active = activeKey === sortKey
  return (
    <th
      onClick={() => onSort(sortKey)}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={`px-4 py-3 text-left text-xs font-semibold ds-u-color--muted uppercase tracking-wider select-none cursor-pointer hover:text-cms-blue transition-colors ${className}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active ? (
          dir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
        ) : (
          <ChevronsUpDown size={12} className="text-gray-300" />
        )}
      </span>
    </th>
  )
}
