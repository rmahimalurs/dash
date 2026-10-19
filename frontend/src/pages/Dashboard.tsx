import CertificateWidget from '../components/widgets/CertificateWidget'
import ServiceAccountWidget from '../components/widgets/ServiceAccountWidget'
import LicenseWidget from '../components/widgets/LicenseWidget'
import SonarQubeLocWidget from '../components/widgets/SonarQubeLocWidget'
import LinksWidget from '../components/widgets/LinksWidget'
import JiraWidget from '../components/widgets/JiraWidget'
import ConfluenceWidget from '../components/widgets/ConfluenceWidget'
import CloudWatchWidget from '../components/widgets/CloudWatchWidget'
import DatadogWidget from '../components/widgets/DatadogWidget'
import GithubWidget from '../components/widgets/GithubWidget'
import VictorOpsWidget from '../components/widgets/VictorOpsWidget'
import OnboardingWidget from '../components/widgets/OnboardingWidget'
import AwsAccountsWidget from '../components/widgets/AwsAccountsWidget'
import GoldImageWidget from '../components/widgets/GoldImageWidget'
import SupportWidget from '../components/widgets/SupportWidget'
export default function Dashboard() {
  return (
    <div className="space-y-6">

      {/* Row 1: Certificate table — full width so all columns breathe */}
      <CertificateWidget />

      {/* Row 2: License table — full width for same reason */}
      <LicenseWidget />

      {/* Row 2b: SonarQube server-wide licensed LOC (CLDSPT-112879) */}
      <SonarQubeLocWidget />

      {/* Row 3: Service account password expiry */}
      <ServiceAccountWidget />

      {/* Row 4: Tool links (big) + Jira & Confluence stacked (narrow) */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <LinksWidget />
        </div>
        <div className="flex flex-col gap-6">
          <JiraWidget />
          <ConfluenceWidget />
        </div>
      </div>

      {/* Row 5: Monitoring & source control — equal thirds */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <CloudWatchWidget />
        <DatadogWidget />
        <GithubWidget />
      </div>

      {/* Row 6: Ops & schedule references */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        <VictorOpsWidget />
        <AwsAccountsWidget />
        <OnboardingWidget />
        <GoldImageWidget />
      </div>

      {/* Row 7: Tool support portals */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <SupportWidget />
      </div>

    </div>
  )
}
