import { ReactNode } from 'react'

interface ActionCardProps {
  icon: ReactNode
  label: string
  description: string
  color: string
  onClick: () => void
}

export default function ActionCard({ icon, label, description, color, onClick }: ActionCardProps) {
  return (
    <button
      onClick={onClick}
      className="theme-card theme-card--plain items-start text-left group w-full transition-all duration-150"
    >
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color} group-hover:scale-110 transition-transform duration-150`}>
        {icon}
      </div>
      <div>
        <p className="text-sm font-semibold text-gray-800 group-hover:text-cms-blue transition-colors">
          {label}
        </p>
        <p className="text-xs ds-u-color--muted mt-0.5">{description}</p>
      </div>
    </button>
  )
}
