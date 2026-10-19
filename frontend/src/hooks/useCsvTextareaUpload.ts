import type { ChangeEvent, Dispatch, SetStateAction } from 'react'
import { parseCsvValues, type CsvFieldType } from '../utils/parseList'

/** An <input type="file"> onChange handler that parses the file as CSV/txt
 * and appends the values into an existing newline-joined textarea string.
 * `fieldType` scopes which CSV column is recognized to what this action
 * actually wants (an email for invites, a handle for seat assignment),
 * so a file with both doesn't have the wrong one picked. */
export function useCsvTextareaUpload(setValue: Dispatch<SetStateAction<string>>, fieldType: CsvFieldType) {
  return (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    file.text().then(text => {
      const values = parseCsvValues(text, fieldType)
      setValue(prev => [prev, ...values].filter(Boolean).join('\n'))
    })
  }
}
