import { Loader2 } from 'lucide-react'
import type { BulkJob } from '../../api/client'

export default function JobProgress({ job }: { job: BulkJob<unknown, unknown> }) {
  const pct = job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0
  return (
    <div className="space-y-2 py-4">
      <div className="flex items-center gap-2 text-sm">
        <Loader2 size={15} className="animate-spin flex-shrink-0" />
        <span>{job.done} / {job.total} ({pct}%)</span>
      </div>
      <div className="w-full h-2 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
        <div className="h-full bg-cms-blue transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      {job.current && (
        <p className="text-xs ds-u-color--muted truncate">Working on: {job.current}</p>
      )}
    </div>
  )
}
