import { AlertTriangle } from 'lucide-react'
import { ReactNode } from 'react'

interface WidgetCardProps {
  title: string
  icon?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  noPadding?: boolean
}

export default function WidgetCard({
  title,
  icon,
  action,
  children,
  className = '',
  noPadding = false,
}: WidgetCardProps) {
  return (
    <div className={`theme-card flex flex-col ${className}`}>
      {/* Card header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-700">
        <div className="flex items-center gap-2.5">
          {icon && (
            <div className="theme-card__icon w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0">
              {icon}
            </div>
          )}
          <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">{title}</h2>
        </div>
        {action && <div className="flex-shrink-0">{action}</div>}
      </div>

      {/* Card content */}
      <div className={`flex-1 flex flex-col ${noPadding ? '' : 'p-5'}`}>{children}</div>
    </div>
  )
}

export function AuthRequired() {
  return (
    <div className="alert alert--warning alert--compact mt-auto">
      <AlertTriangle size={11} className="alert__icon mt-0.5" />
      <span className="text-xs">Auth Required</span>
    </div>
  )
}

// Skeleton loader for table rows
export function SkeletonRow({ cols }: { cols: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-gray-100 dark:bg-gray-700 rounded animate-pulse" style={{ width: `${60 + Math.random() * 30}%` }} />
        </td>
      ))}
    </tr>
  )
}
