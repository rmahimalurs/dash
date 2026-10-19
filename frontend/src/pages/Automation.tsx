import { KeyRound, Construction, Network, Github } from 'lucide-react'
import GitHubOrgInvites from '../components/widgets/GitHubOrgInvites'
import GitHubCopilotSeatAssign from '../components/widgets/GitHubCopilotSeatAssign'
import GitHubRepoCreate from '../components/widgets/GitHubRepoCreate'
import UpdateJFrogPasswordWidget from '../components/widgets/UpdateJFrogPasswordWidget'
import JFrogRegistryTokenWidget from '../components/widgets/JFrogRegistryTokenWidget'
import RepoCacheRefreshWidget from '../components/widgets/RepoCacheRefreshWidget'
import CertExportWidget from '../components/widgets/CertExportWidget'
import UpdateCloudBeesPasswordWidget from '../components/widgets/UpdateCloudBeesPasswordWidget'
import CopyControllerWidget from '../components/widgets/CopyControllerWidget'
import PvcCleanupWidget from '../components/widgets/PvcCleanupWidget'
import CbjWasteEmailWidget from '../components/widgets/CbjWasteEmailWidget'
import ControllerUserAuditWidget from '../components/widgets/ControllerUserAuditWidget'
import ArtifactoryUserAuditWidget from '../components/widgets/ArtifactoryUserAuditWidget'
import ArtifactoryAccessWidget from '../components/widgets/ArtifactoryAccessWidget'
import CloudBeesAccessWidget from '../components/widgets/CloudBeesAccessWidget'
import PodQuotaWidget from '../components/widgets/PodQuotaWidget'
import JFrogUnlockWidget from '../components/widgets/JFrogUnlockWidget'
import ActiveDirectoryUnlockWidget from '../components/widgets/ActiveDirectoryUnlockWidget'
import SonarQubeAccessWidget from '../components/widgets/SonarQubeAccessWidget'
import UpdateDatadogSyntheticsWidget from '../components/widgets/UpdateDatadogSyntheticsWidget'

function PlaceholderCard({ label, description }: { label: string; description: string }) {
  return (
    <div className="flex flex-col items-start gap-3 p-5 bg-white dark:bg-gray-800 rounded-xl border border-dashed border-gray-200 dark:border-gray-700 opacity-60 select-none">
      <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-gray-100 dark:bg-gray-700">
        <Construction size={20} className="ds-u-color--muted" />
      </div>
      <div>
        <p className="text-sm font-semibold ds-u-color--muted">{label}</p>
        <p className="text-xs ds-u-color--muted mt-0.5">{description}</p>
        <span className="inline-block mt-1.5 text-[10px] font-semibold uppercase tracking-wide ds-u-color--muted bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">
          Coming Soon
        </span>
      </div>
    </div>
  )
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <span className="ds-u-color--muted">{icon}</span>
        <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">{title}</h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {children}
      </div>
    </div>
  )
}

export default function Automation() {
  return (
    <div className="space-y-10 max-w-5xl">
      <Section title="GitHub" icon={<Github size={15} />}>
        <GitHubOrgInvites />
        <GitHubCopilotSeatAssign />
        <GitHubRepoCreate />
      </Section>

      <Section title="Active Directory" icon={<Network size={15} />}>
        <ActiveDirectoryUnlockWidget />
      </Section>

      <Section title="JFrog Artifactory" icon={<KeyRound size={15} />}>
        <UpdateJFrogPasswordWidget />
        <JFrogUnlockWidget />
        <JFrogRegistryTokenWidget />
        <ArtifactoryAccessWidget />
        <RepoCacheRefreshWidget />
        <ArtifactoryUserAuditWidget />
        <CertExportWidget tool="jfrog" label="Export Wildcard Cert" />
      </Section>

      <Section title="SonarQube" icon={<KeyRound size={15} />}>
        <SonarQubeAccessWidget />
        <PlaceholderCard
          label="SonarQube Svc Account Password — Prod"
          description="Update LDAP manager password for SonarQube prod"
        />
        <PlaceholderCard
          label="SonarQube Svc Account Password — Dev"
          description="Update LDAP manager password for SonarQube dev"
        />
      </Section>

      <Section title="CloudBees Jenkins" icon={<KeyRound size={15} />}>
        <UpdateCloudBeesPasswordWidget />
        <CloudBeesAccessWidget />
        <CopyControllerWidget />
        <PvcCleanupWidget />
        <PodQuotaWidget />
        <CbjWasteEmailWidget />
        <ControllerUserAuditWidget />
        <CertExportWidget tool="cbj" label="Export Wildcard Cert" />
      </Section>

      <Section title="Datadog Synthetics" icon={<KeyRound size={15} />}>
        <UpdateDatadogSyntheticsWidget />
      </Section>
    </div>
  )
}
