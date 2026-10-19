import { CreateItcWidget, CreateMggdWidget } from '../components/widgets/JiraTicketWidgets'
import MaintenancePrepWidget from '../components/widgets/MaintenancePrepWidget'
import SprintOnCallWidget from '../components/widgets/SprintOnCallWidget'
import CloseItcWidget from '../components/widgets/CloseItcWidget'
import CloseMggdWidget from '../components/widgets/CloseMggdWidget'
import MaintRetroWidget from '../components/widgets/MaintRetroWidget'
import SprintRetroWidget from '../components/widgets/SprintRetroWidget'
import OEReadinessWidget from '../components/widgets/OEReadinessWidget'
import MaintenanceTicketsWidget from '../components/widgets/MaintenanceTicketsWidget'

export default function Jira() {
  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4">
          <h2 className="text-base font-semibold text-gray-800">Actions</h2>
          <p className="text-sm ds-u-color--muted mt-0.5">
            Automation shortcuts for Jira ticket creation and management
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
          <CreateItcWidget />
          <CreateMggdWidget />
          <MaintenancePrepWidget />
          <SprintOnCallWidget />
          <CloseItcWidget />
          <CloseMggdWidget />
          <MaintRetroWidget />
          <SprintRetroWidget />
          <OEReadinessWidget />
        </div>
      </section>

      <MaintenanceTicketsWidget />
    </div>
  )
}
