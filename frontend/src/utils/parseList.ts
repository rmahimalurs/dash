export function parseList(raw: string, stripAt = false): string[] {
  return raw
    .split(/[\n,]/)
    .map(s => stripAt ? s.trim().replace(/^@/, '') : s.trim())
    .filter(Boolean)
}

export type CsvFieldType = 'email' | 'handle'

const _COLUMNS_BY_FIELD_TYPE: Record<CsvFieldType, Set<string>> = {
  email: new Set(['email', 'emails', 'email_address']),
  // Deliberately excludes "login" alone: GitHub's own API calls this field
  // "login", but a roster CSV using that exact header is just as likely to
  // mean something else entirely; the longer, GitHub-specific names below
  // are the ones actually worth recognizing without an explicit mapping.
  handle: new Set(['handle', 'github_handle', 'githubhandle', 'username', 'github']),
}

function _normalizeHeader(cell: string): string {
  return cell.trim().toLowerCase().replace(/[\s_]+/g, '_')
}

/** Splits one CSV row on commas, honoring double-quoted fields (which may
 * contain a comma) and a doubled "" as an escaped quote inside one -- a
 * naive `row.split(',')` would cut a quoted field like "alice,bob" into
 * two columns and shift everything after it. Shared by every CSV upload
 * in this app so none of them re-implement (and re-break) this. */
export function splitCsvRow(row: string): string[] {
  const cells: string[] = []
  let cell = ''
  let inQuotes = false
  for (let i = 0; i < row.length; i++) {
    const ch = row[i]
    if (inQuotes) {
      if (ch === '"') {
        if (row[i + 1] === '"') { cell += '"'; i++ } else { inQuotes = false }
      } else {
        cell += ch
      }
    } else if (ch === '"') {
      inQuotes = true
    } else if (ch === ',') {
      cells.push(cell)
      cell = ''
    } else {
      cell += ch
    }
  }
  cells.push(cell)
  return cells
}

/** Parses a pasted .csv/.txt file's text into a flat list of values: a
 * one-per-line .txt, or a .csv whose header has a column recognized for
 * `fieldType` -- scoped to the kind of value the calling action actually
 * wants, so a CSV with both an email and a handle column doesn't have the
 * wrong one picked just because it happens to appear first. Falls back to
 * every row's first column when no matching header is found. */
export function parseCsvValues(text: string, fieldType: CsvFieldType): string[] {
  const recognized = _COLUMNS_BY_FIELD_TYPE[fieldType]
  const rows = text.split(/\r?\n/).map(r => r.trim()).filter(Boolean).map(splitCsvRow)
  if (rows.length === 0) return []
  const header = rows[0].map(_normalizeHeader)
  const headerColIdx = header.findIndex(h => recognized.has(h))
  const colIdx = headerColIdx >= 0 ? headerColIdx : 0
  const dataRows = headerColIdx >= 0 ? rows.slice(1) : rows
  return dataRows.map(r => (r[colIdx] ?? '').trim()).filter(Boolean)
}
