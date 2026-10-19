// Content for the in-app Manual page (pages/Manual.tsx).
//
// One entry per dashboard page → its sections → the tiles within. Keep tile
// `name` in sync with the label shown on the actual card so the manual maps 1:1
// to what the engineer sees. `what` = what the tile does; `why` = why it exists.

export interface ManualTile {
  name: string
  what: string
  why: string
  status?: 'live' | 'coming-soon' | 'admin'
}

export interface ManualSection {
  title: string
  tiles: ManualTile[]
}

export interface ManualPage {
  id: string
  title: string
  route: string
  blurb: string
  sections: ManualSection[]
}

export const MANUAL: ManualPage[] = [
  {
    id: 'dashboard',
    title: 'Dashboard',
    route: '/',
    blurb:
      'The landing page: live health checks (certificates, licenses, service-account password expiry), quick links to every tool, and shortcuts into the monitoring surfaces the team watches. Everything here is read-only, nothing changes state.',
    sections: [
      {
        title: 'Release awareness',
        tiles: [
          {
            name: "What's new",
            what: 'A popup that appears once per release, on any page, listing what changed in the version you are actually running. Dismissing it with "Got it" records the acknowledgment against your profile, so it stays gone until the next release and follows you across browsers.',
            why: 'Features were shipping without the team noticing. Tying the notice to the deployed version means nobody has to remember to announce a release, and nobody sees the same notice twice.',
          },
        ],
      },
      {
        title: 'Health & expiry monitoring',
        tiles: [
          {
            name: 'Certificate Expiry',
            what: 'Checks the TLS certificate expiry for the team’s public endpoints (JFrog, CloudBees, SonarQube, the dashboard) concurrently and shows days remaining for each.',
            why: 'Expired certificates cause outages that are easy to miss; surfacing them early leaves time to renew before anything breaks.',
          },
          {
            name: 'License Expiry',
            what: 'Shows the remaining validity of the commercial tool licenses — JFrog Artifactory, CloudBees CI, SonarQube, and Snyk.',
            why: 'A lapsed license can disable a production tool; this is the early warning that a renewal is due.',
          },
          {
            name: 'Service Account Password Expiry',
            what: 'Tracks the AD password-expiry date for the DevOps service accounts (CloudBees, Artifactory, SonarQube, SMTP, Datadog Synthetics).',
            why: 'An expired service-account password locks the tool that depends on it. Flagged accounts are rotated from the Automation page.',
          },
          {
            name: 'SonarQube Licensed LOC',
            what: 'Shows SonarQube’s server-wide licensed lines-of-code usage vs the cap (percent used, status). A backend job also checks hourly and emails the DevOps distro when the status escalates (ok → warning → critical).',
            why: 'SonarQube is licensed by total lines of code; quietly crossing the cap blocks new analysis. This is the early warning before that happens.',
            status: 'live',
          },
        ],
      },
      {
        title: 'Links & shortcuts',
        tiles: [
          {
            name: 'Tools',
            what: 'Quick-launch links to the consoles used daily (Jenkins, Artifactory, SonarQube, Akamai, Snyk, Splunk, and more) with real favicons.',
            why: 'One click to the right console instead of hunting through bookmarks.',
          },
          {
            name: 'Jira (DMSC)',
            what: 'Curated quick links into the team’s DMSC Jira project (board, backlog, common filters).',
            why: 'One hop to the work-tracking views the team uses most.',
          },
          {
            name: 'Confluence — COMET',
            what: 'Links into the COMET Confluence space (runbooks, retros, knowledge base).',
            why: 'The team’s documentation home is always one click away.',
          },
          {
            name: 'GitHub Repos',
            what: 'Curated links to the team’s key GitHub repositories (CMS-Enterprise and CMSgov orgs).',
            why: 'Fast access to the infrastructure and automation repos.',
          },
          {
            name: 'Onboarding',
            what: 'Links to the onboarding material for new team members.',
            why: 'A central starting point for ramping up on the platform.',
          },
          {
            name: 'DevOps Tools Support',
            what: 'Direct links to the vendor support portals (CloudBees, JFrog, SonarQube, Snyk).',
            why: 'When a tool needs a vendor ticket, the correct portal is right here.',
          },
        ],
      },
      {
        title: 'Monitoring & accounts',
        tiles: [
          {
            name: 'CloudWatch Dashboards',
            what: 'Links to the relevant AWS CloudWatch dashboards for the clusters.',
            why: 'Infrastructure metrics at a glance.',
          },
          {
            name: 'Datadog Monitors',
            what: 'Quick links to the team’s key Datadog monitors and the monitor-manage view (GovCloud tenant).',
            why: 'Jump straight to the monitors that matter (for example the Jenkins PVC-usage alert) instead of searching Datadog.',
          },
          {
            name: 'VictorOps',
            what: 'Links into the VictorOps portal and its common views.',
            why: 'Fast access to paging and schedules. The current on-call name is shown live in the sidebar.',
          },
          {
            name: 'AWS Accounts',
            what: 'Reference list of the team’s AWS accounts grouped by area, with CloudTamer links.',
            why: 'Quick lookup of account IDs when switching roles or filing access requests.',
          },
        ],
      },
    ],
  },

  {
    id: 'maintenance',
    title: 'Maintenance',
    route: '/maintenance',
    blurb:
      'Everything for the monthly maintenance window, the 3rd Saturday of the month running 9 AM to 1 PM ET: cut the branch, silence monitors, notify the ops centers, and drive the per-tool upgrades. Actions here change real state, so steps are gated and audit-logged.',
    sections: [
      {
        title: 'Maintenance actions',
        tiles: [
          {
            name: 'Cut Maintenance Branch',
            what: 'Creates the maintenance branch from main in the infrastructure repo (idempotent — reuses the branch if it already exists).',
            why: 'All maintenance changes ride on one dedicated branch; this standardizes and de-risks the first step.',
          },
          {
            name: 'Create DD Downtime',
            what: 'Schedules or activates a Datadog downtime to silence monitors for the window. Pre-filled to 9 AM to 2 PM ET, an hour past the outage so monitors stay quiet through verification.',
            why: 'Prevents alert noise and paging on-call during planned maintenance.',
          },
          {
            name: 'Notify XOC / EOC',
            what: 'Generates the XOC and EOC notification messages with the window details and copy-ready Slack links.',
            why: 'CMS requires notifying the operations centers before and after maintenance; this drafts the exact messages so they are consistent.',
          },
        ],
      },
      {
        title: 'Tool maintenance — Step 1: shared platform (run first)',
        tiles: [
          {
            name: 'Base Helm Charts',
            what: 'Bumps the charts in kubernetes/base/releases (AWS CloudWatch Metrics, AWS for Fluent Bit, kube-state-metrics, Velero, Snapshot Controller) on the maintenance branch, with release notes and per-chart skip control.',
            why: 'These charts belong to no single tool: both the JFrog and CloudBees clusters reconcile them, so they get one card instead of riding along in the JFrog dev modal where they were easy to miss. They are a prerequisite for the tools that reconcile them: while any shared chart is behind, the JFrog and CloudBees cards are gated (with a Run anyway override) so those upgrades always build on a current base. SonarQube is never gated, because it deploys through its own Jenkins pipeline and does not reconcile the shared base.',
          },
          {
            name: 'EKS Control Plane',
            what: 'Lists all six clusters (4 CloudBees + JFrog dev/prod) with their declared eks_version and the upgrade targets AWS currently offers for that region, including end-of-support dates. Picking a target runs pluto over that cluster\'s GitOps manifests to list APIs and CRDs the new version removes or deprecates, pulls the Kubernetes urgent-upgrade and deprecation notes, and resolves the gold image built for the target. Apply commits the eks_version bump plus the matching AMI realign to the maintenance branch.',
            why: 'The control-plane bump, the deprecated-API check, and the node image all have to move together. Doing it from one card means the gold image never lags the control plane, and nothing reaches a new minor with removed APIs still in the manifests.',
          },
        ],
      },
      {
        title: 'Tool maintenance — Step 2: per-tool, Dev',
        tiles: [
          {
            name: 'SonarQube — Dev',
            what: 'Deploys or updates SonarQube in dev via the Jenkins pipeline (upgrades, re-indexing, config sync).',
            why: 'Validate in dev first before touching production.',
          },
          {
            name: 'JFrog — Dev',
            what: 'Opens the JFrog dev maintenance modal: bumps the JFrog Helm chart and OCI repo versions, node AMI and Karpenter, then applies to jfrog-dev, with per-release skip control. The shared base charts moved to their own Base Helm Charts tile.',
            why: 'Drives the Artifactory / Xray upgrade on the maintenance branch instead of editing manifests by hand.',
          },
          {
            name: 'CloudBees CI — Dev',
            what: 'Opens the CloudBees dev maintenance modal: controller and agent AMIs, Karpenter nodeclass, and the CloudBees Core chart version.',
            why: 'Coordinates the several moving parts of a CBJ upgrade so nothing drifts out of sync.',
          },
        ],
      },
      {
        title: 'Tool maintenance — Step 2: per-tool, Prod',
        tiles: [
          {
            name: 'SonarQube — Prod',
            what: 'The production SonarQube deploy, run after the dev deploy is validated.',
            why: 'Same pipeline as dev, promoted to prod during the window.',
          },
          {
            name: 'JFrog — Prod',
            what: 'The production JFrog maintenance modal (chart / OCI / AMI / Karpenter), applied to jfrog-prod.',
            why: 'Promotes the validated dev changes to the production Artifactory.',
          },
          {
            name: 'CloudBees CI — Prod',
            what: 'The production CloudBees maintenance modal across prod-east and gov-prod-west.',
            why: 'Promotes the validated CBJ upgrade to the production controllers.',
          },
        ],
      },
      {
        title: 'Maintenance reference',
        tiles: [
          {
            name: 'Maintenance Runbooks',
            what: 'Links out to the per-tool Confluence maintenance runbooks (CloudBees Jenkins, JFrog, SonarQube) with the step-by-step procedures, rollback plans, and escalation paths.',
            why: 'The tiles automate the mechanics; the runbooks are the source of truth for the full process and what to do when something goes wrong.',
          },
        ],
      },
    ],
  },

  {
    id: 'jira',
    title: 'Jira',
    route: '/jira',
    blurb:
      'Shortcuts for the recurring Jira and Confluence paperwork around maintenance and sprints. These actions are gated to authorized users.',
    sections: [
      {
        title: 'Ticket & retro automation',
        tiles: [
          {
            name: 'Create ITC Ticket',
            what: 'Creates the ITC maintenance ticket with the window auto-derived from the maintenance date (9 AM to 1 PM ET, same day), plus the IR-plan and downtime Excel attachments.',
            why: 'Every maintenance needs an ITC; this fills the required fields and attachments the same way each month.',
          },
          {
            name: 'Create MGGD Ticket',
            what: 'Creates the MGGD change request in the GovCloud Jira with all required option fields and the downtime Excel attached.',
            why: 'MGGD is a long change form; the tile encodes the correct field IDs so it is not hand-filled and mis-keyed.',
          },
          {
            name: 'Maintenance Prep',
            what: 'Creates the monthly maintenance-prep tickets with the assignee chosen by auto-rotation.',
            why: 'Standardizes prep-task creation and rotates ownership across the team fairly.',
          },
          {
            name: 'Sprint & On-Call',
            what: 'Creates the on-call support tickets for the sprint.',
            why: 'Ensures each sprint has its on-call tracking tickets without manual setup.',
          },
          {
            name: 'Close ITC',
            what: 'Transitions the ITC ticket to Implemented with a completion comment.',
            why: 'Closes the loop after maintenance with the correct resolution set.',
          },
          {
            name: 'Close MGGD',
            what: 'Adds the completion comment to this month’s MGGD ticket.',
            why: 'Records maintenance completion on the change request.',
          },
          {
            name: 'Maintenance Retro',
            what: 'Creates the Confluence retro page for the latest maintenance under the COMET space and links it from the parent.',
            why: 'Every maintenance gets a retro; this scaffolds the page from the standard template.',
          },
          {
            name: 'Sprint Retro',
            what: 'Creates the Confluence retro page for the current sprint.',
            why: 'Standard sprint-retro scaffolding, numbered and dated from the active sprint.',
          },
          {
            name: 'OE Readiness',
            what: 'Fills the annual Open Enrollment DevOps readiness pages (OEC space) for a chosen year. Auto-discovers the split CloudBees/Jenkins and JFrog/SonarQube pages and best-effort fills each readiness row: live license and TLS-cert expiry, on-call, monitoring and architecture links, owners resolved to real Confluence user mentions, and live Karpenter instance-flavor counts. Carries forward accounts, capacity, patching, BaseCamp screenshots, dependencies, and vendor-escalation links, and marks each filled row Completed. On Fill it also creates one SRE readiness ticket (CLDSRE) per tool and links it, and comments the assigned CCOE ticket — which can be closed from the tile once every section is verified. Writes are non-destructive (empty cells only).',
            why: 'OE readiness is a large annual checklist rebuilt from scratch each year. This turns hours of hand-copying live data and last-year content into one click, while leaving the human-judgment items clearly flagged.',
            status: 'live',
          },
        ],
      },
    ],
  },

  {
    id: 'automation',
    title: 'Automation',
    route: '/automation',
    blurb:
      'Day-to-day operational tasks that used to be manual one-off scripts: service-account rotations, account unlocks, certificate export, controller cloning, and PVC cleanup. Sensitive actions are gated and audit-logged.',
    sections: [
      {
        title: 'Active Directory',
        tiles: [
          {
            name: 'Unlock / Reset AD Account',
            what: 'Clears an AD lockout or resets an AD account password (auto-generates the new password and stores it in 1Password), all over LDAPS.',
            why: 'AD lockouts and expired passwords are the most common break-fix. It uses a single bind so it cannot itself trip the AD lockout policy, unlike ad-hoc ldap commands.',
          },
        ],
      },
      {
        title: 'JFrog Artifactory',
        tiles: [
          {
            name: 'JFrog Svc Account Password',
            what: 'Rotates the JFrog service-account (LDAP manager) password for dev or prod. Full rotation resets AD, banks the new password in 1Password, verifies it via an LDAP bind, then updates Artifactory only if the bind succeeds.',
            why: 'Rotating a shared service-account password by hand is error-prone and can lock the tool. This makes it atomic and never writes an unverified password to Artifactory.',
          },
          {
            name: 'Unlock Artifactory User',
            what: 'Clears a locked-out Artifactory account through the Access API.',
            why: 'Users get locked out of Artifactory; this unlocks them without digging through the admin console.',
          },
          {
            name: 'Refresh Repo Cache / Reindex',
            what: 'Zaps a remote-proxy repository cache or recalculates a repository index in prod.',
            why: 'Fixes stale metadata and binary-provider 500s without a full service restart.',
          },
          {
            name: 'Check User Access',
            what: 'Enter an EUA (dev or prod) to see whether the user is provisioned in Artifactory and everything they can reach: identity (realm, admin, status, last login), group memberships, the Artifactory projects they belong to with role in each, and the permission targets that grant them access (directly or via a group), with the repo-level permissions.',
            why: 'Answers "does this person have Artifactory access, and to what?" in one step — across groups, projects, and permission targets — without hand-tracing the admin console.',
            status: 'live',
          },
          {
            name: 'Artifactory User Audit',
            what: 'Scans every Artifactory project (dev or prod) and lists the ones that have deactivated members — accounts whose AD is disabled (people who left) — ranked by count. Click a project to review its members cross-referenced against AD and delete the deactivated ones; deletion removes the user from Artifactory entirely (and every project). Artifactory never disables an LDAP user locally, so AD is the source of truth. A background sweep runs daily at 5 AM ET (and on demand); deletion re-checks AD server-side and refuses anything not confirmed-disabled.',
            why: 'Former staff linger as Artifactory accounts across hundreds of projects long after they leave. This shows exactly which projects are affected and cleans them up safely, without hand-checking each name against AD.',
            status: 'live',
          },
          {
            name: 'Export Wildcard Cert',
            what: 'Exports the auto-renewed *.cloud.cms.gov ACM wildcard certificate, stores the cert, chain, and key in 1Password, and opens a SOPS-encrypted-secret PR. Idempotent — no-ops when the fingerprint is unchanged.',
            why: 'The wildcard renews automatically but the Kubernetes TLS secret must still be updated by hand; this automates the export and the PR.',
          },
        ],
      },
      {
        title: 'SonarQube',
        tiles: [
          {
            name: 'Check User Access',
            what: 'Look up a user by EUA, login, name, or email to confirm they are provisioned in SonarQube (active, last sign-in, auth source) and list the application projects they can access, with role (user vs administrator) in each. Also flags email collisions — when two accounts share an email, or an unprovisioned user\'s AD email is already held by another account — which silently block LDAP login.',
            why: 'Answers "does this person have SonarQube access, and to what?" in one step, and surfaces the #1 silent login blocker: SonarQube requires unique emails, so a shared email stops LDAP auto-provisioning. Project access at CMS is group-based (<app>-users / <app>-administrators), so the tile derives application access from group memberships instead of scanning thousands of projects.',
          },
          {
            name: 'SonarQube Svc Account Password — Prod',
            what: 'Will rotate the SonarQube LDAP manager password for prod.',
            why: 'Parity with the JFrog and CloudBees rotation tiles. Not yet built.',
            status: 'coming-soon',
          },
          {
            name: 'SonarQube Svc Account Password — Dev',
            what: 'Will rotate the SonarQube LDAP manager password for dev.',
            why: 'Parity with the JFrog and CloudBees rotation tiles. Not yet built.',
            status: 'coming-soon',
          },
        ],
      },
      {
        title: 'CloudBees Jenkins',
        tiles: [
          {
            name: 'CBJ Svc Account Password',
            what: 'Rotates the LDAP manager password across the four CJOCs (dev-east, prod-east, gov-dev-west, gov-prod-west) with a test-then-save gate per environment.',
            why: 'CBJ has four controllers binding with the same account; rotating them consistently by hand is tedious and lockout-prone.',
          },
          {
            name: 'Check User Access',
            what: 'Enter an EUA and environment (Prod East / GovCloud Prod) to see every CloudBees controller the user has access to, with the RBAC groups and roles granting it, plus their AD status. Backed by a daily 5 AM scan of all controllers’ RBAC (with an on-demand Re-scan) since access is per-controller and scanning ~196 live would be too slow.',
            why: 'CloudBees access is granted by RBAC groups on each controller, so there is no single place to see what one person can reach. This surfaces it across all controllers at once.',
            status: 'live',
          },
          {
            name: 'Copy Controllers',
            what: 'Clones a prod-east controller into dev-east: discovers its AWS roles, network CIDRs, admins, jobs, secrets, and plugins, then triggers the onboarding pipeline and applies each piece.',
            why: 'Stands up a faithful dev copy of a prod controller for testing, without reconstructing all that configuration by hand.',
          },
          {
            name: 'Controller PVC Cleanup',
            what: 'Remediates the Jenkins Controllers PVC-usage alert: lists over-threshold controllers, shows the disk breakdown from the disk-usage plugin, gets ADO sign-off (Slack message plus a formatted email), auto-files a DMSC ticket assigned to the triggering engineer (1 point, added to the active sprint, and auto-closed Fixed when the prune completes), then prunes old builds, workspaces, and caches. ADO emails skip anyone whose AD account is deactivated, escalate on repeat sends (plain → Second Notice → Final Notice), and record who was emailed and when.',
            why: 'Controller PVCs fill with old build history and page on-call for months. This makes the cleanup safe (ADO-approved, dry-run-first, kill-switched), self-documenting, and it never emails people who have left.',
            status: 'live',
          },
          {
            name: 'CBJ Resource-Waste Email',
            what: 'Lists ADO teams whose CBJ podTemplates (or controllers) reserve far more CPU/memory/disk than they use at peak (from the Monitoring analysis), pick an environment (Prod East or GovCloud Prod), select a team to review the offending containers and drafted message, then email the team’s ADO admins a right-sizing request (auto-resolved recipients on prod-east, manual entry on gov-west), cc’ing the DevOps distro. Deactivated ADOs are excluded, sends escalate (Second/Final Notice), and history is recorded.',
            why: 'Karpenter sizes nodes on what containers reserve, not use, so over-provisioned podTemplates quietly cost real node capacity. This turns the read-only Monitoring analysis into an action: ask the owning team to right-size.',
            status: 'live',
          },
          {
            name: 'Pod Quota (fiftypods)',
            what: 'Audits the per-controller fiftypods ResourceQuota (agent pods, default cap 50) across an environment (Prod East / GovCloud Prod), flagging controllers at or near the limit. Drill into one to raise the limit (bounded, max 100) and/or see its running builds — longest-running first — and abort stuck ones to free agent pods.',
            why: 'When a controller hits its pod quota, pipelines fail with "exceeded quota: fiftypods". This shows exactly which controllers are maxed and lets you either free pods by killing stuck builds or raise the cap — without hunting through kubectl and the Jenkins UI.',
            status: 'live',
          },
          {
            name: 'Controller User Audit',
            what: 'Scans every CloudBees controller (Prod East or GovCloud Prod) and lists the ones that have deactivated users — accounts whose AD is disabled (people who left) — ranked by count. Click a controller to review its users cross-referenced against AD and delete the deactivated ones. A background sweep runs every day at 5 AM ET (and on demand) so the list is ready without waiting; deletion re-checks AD server-side and refuses anything not confirmed-disabled.',
            why: 'Left-the-org users accumulate on hundreds of controllers and are impossible to find by hand. This surfaces exactly where the cleanup is needed and does it safely.',
            status: 'live',
          },
          {
            name: 'Export Wildcard Cert',
            what: 'The same wildcard-cert export as JFrog, targeting the CloudBees clusters’ ingress and CJOC TLS secrets across all four environments.',
            why: 'The CloudBees ingress and CJOC secrets need the renewed wildcard just like Artifactory does.',
          },
        ],
      },
      {
        title: 'Datadog Synthetics',
        tiles: [
          {
            name: 'Datadog Synthetics Password',
            what: 'Full rotation of a Datadog Synthetics service account (pick dso-synthetics-a or dso-synthetics-b): resets the AD password, saves it to 1Password, softly verifies it over LDAP, then writes the new password into the matching secure Datadog global variable (DSO_SYNTHETICS_A/B_PASSWORD under Synthetic Tests › Global Variables).',
            why: 'Synthetic tests log in with these AD accounts and read the password from a Datadog global variable; rotating means changing it in AD, 1Password, and Datadog in lockstep, which is error-prone by hand.',
            status: 'live',
          },
        ],
      },
    ],
  },

  {
    id: 'monitoring',
    title: 'Monitoring',
    route: '/monitoring',
    blurb:
      'Read-only monitoring surfaces sourced live from CloudWatch. Pick an environment from the dropdown; Prod East and GovCloud Prod are kept separate (different AWS accounts).',
    sections: [
      {
        title: 'CBJ Monitoring',
        tiles: [
          {
            name: 'CBJ Resource Analysis',
            what: 'Per-container table comparing what each CloudBees Jenkins container reserved from Kubernetes vs. what it actually used at its busiest moment in the last 7 days, from CloudWatch Container Insights. Toggle between Build/Agent podTemplates and Controllers, and pick the environment (Prod East / GovCloud Prod) from a dropdown. Sorted by CPU wasted, worst first; red = wasteful (<10% used), yellow = low use (10–30%).',
            why: 'Karpenter provisions nodes based on reserved, not used — so over-provisioned podTemplates and controllers force bigger/extra nodes and cost real capacity. This surfaces the worst offenders so the owning ADO teams can be asked to right-size (via the CBJ Resource-Waste Email tile on Automation).',
            status: 'live',
          },
          {
            name: 'podTemplate Config',
            what: 'Reads each prod-east controller’s configured pod request/limit (CPU, memory, disk) straight from the Jenkins build console logs — where the Kubernetes plugin prints the resolved pod YAML — so it catches jobs that haven’t run recently. Cross-joins against live CloudWatch usage to separate “confirmed wasteful” (measured) from “large requests, no recent data”. Backed by a cache that refreshes automatically every day at 5 AM ET (and on demand).',
            why: 'The Resource Analysis tile only sees containers CloudWatch measured recently; this fills the gap by reading the declared podTemplate config for every controller, so nothing over-provisioned is missed.',
            status: 'live',
          },
        ],
      },
    ],
  },

  {
    id: 'github',
    title: 'GitHub',
    route: '/github',
    blurb:
      'GitHub access requests out of Jira, enterprise license and Copilot seat usage, and repository activity across the CMS-Enterprise org, plus the home for GitHub automations as they are built.',
    sections: [
      {
        title: 'Analytics',
        tiles: [
          {
            name: 'GitHub access requests (CLDSPT)',
            what: 'Every CLDSPT ticket whose summary mentions GitHub, in every status, counted all-time and open, broken down by status and by the nature of the request, and then per engineer. Clicking an engineer lists their tickets with the status, the request type, the approver, and the latest comment. Status chips and request-type chips are filters, and the bell carries each engineer their own open count.',
            why: 'GitHub access work was invisible until someone searched Jira by hand, and nobody could say how much of it was waiting on an approver rather than on us. Statuses are read from Jira rather than hardcoded, so a new CLDSPT status cannot silently fall out of the totals; the page reports an unaccounted count and it is currently zero.',
          },
          {
            name: 'Application Name on each ticket',
            what: 'Every request is labeled with its Application Name beside the request type. When the field is blank, the label shows what we worked out ourselves: first from the justification text, and failing that from the requester\'s AD groups, where CMS group names encode the application (ct-ado-claimscorevendora-application-admin means ClaimsCore, CFACTS_USER_PRD means CFACTS). A name the live application catalog confirms is shown as settled and says what it matched on; anything else is dashed with a question mark, as a lead rather than a fact. A ticket with no signal at all reads "App not set".',
            why: 'This is the field the whole approval chain hangs off: Jira cascades the Primary Approver, Backup Approver and Business Owner from it, so a blank one is exactly why a ticket has nobody to approve it. Of 176 open requests 140 have a name and 36 do not, and the two fallback signals recover an application for 17 of those. Nothing is written back to Jira on purpose, since setting the field triggers Jira\'s cascade and emails the second-stage approver before any Business Owner has signed off. The guessing runs in the daily sweep, so the page reads a cached answer rather than waiting on the catalog.',
          },
          {
            name: 'Approval state, both stages',
            what: 'Approval runs in two stages and each open request shows where it is. The requester\'s Business Owner signs off first; a ticket with nobody asked yet reads "BO approval required" and turns into "Request BO approval" on hover, which comments on the ticket asking the requester to get that sign-off. Once a Business Owner approval is on the ticket, a second button appears that asks Hung Van, the second-stage approver, to sign off on top. A fully approved ticket shows both. Copilot seat requests skip all of it.',
            why: 'CLDSPT does not use Jira\'s approval feature for these and no approval field is ever populated, so a human commenting that they approve is the only record. The classifier tells an approval from a request for one, since Jira\'s automation writes "Could you please approve?", and tells the two stages apart by who wrote the comment, which also stopped Hung\'s own sign-offs being miscounted as Business Owner approvals. The second-stage button refuses until the first approval exists: asking him early is what pinged him on tickets nobody had approved. Neither button sets Application Name, because that triggers Jira\'s cascade and emails him prematurely.',
          },
          {
            name: 'Enterprise licenses and Copilot adoption',
            what: 'Consumed over purchased in one tile, with seats available and the percentage underneath. Beside it, Copilot seats and how many are actually being used. Clicking the seat count breaks it down per organization; clicking the usage count lists the people who are not using the seat they hold.',
            why: 'CMS licenses Copilot for everyone and wants it used, so the question is adoption rather than cost recovery. Per-org is where that becomes actionable: CMS-Enterprise runs at 70% active and cms-enterprise-cpi-ucm at 48%, which is where the untouched seats are concentrated.',
          },
          {
            name: 'Copilot nudges and power users',
            what: 'Each unused seat has an email button that encourages the holder to start using the Copilot license they already have. Nudges escalate: a second one to the same person is subject-prefixed Second Notice, and the row shows how many have gone out and when. Below that, the people holding their own AI-credit budget are listed with the budget, whether it blocks at the cap, and when they last used Copilot.',
            why: 'A Copilot seat carries only a GitHub login, and these are vendor handles AD has never heard of, so no email could be addressed. The enterprise consumed-licenses report maps each login to its EUA and AD turns that into a working address. Power users are read from the enterprise budgets API, the only place a per-user credit grant is recorded; listing their Copilot activity next to the budget is what shows a grant going to somebody who is not using it. No credits have been drawn down enterprise-wide yet, so activity is the usable signal until GitHub\'s premium-request usage report starts returning data. Nothing here cancels a seat: reclaim was removed because CMS wants everyone licensed.',
          },
          {
            name: 'Repositories',
            what: 'Two counts that open their table on click: repos pushed in the last 30 days, and repos with no push in a year or more. Both show language, open issue count and time since the last push, and repos this team owns are badged.',
            why: 'The org holds 100+ repos across many CMS teams, so this separates what is ours from what is merely nearby, and the stale count is the one that tells you what nobody is maintaining. Archived repos are expected to be idle, so they are left out of stale.',
          },
          {
            name: 'Locked by token scope',
            what: 'Lists the areas the service token cannot reach, naming the exact scope each one needs. Copilot usage, Actions billing, the org audit log, Dependabot, secret and code scanning, and all enterprise reporting sit behind scopes the current PAT lacks.',
            why: 'The automation account holds enterprise owner rights, but a PAT only carries the scopes it was minted with. Showing the gap and the fix beats an unexplained empty panel, and these sections populate on their own once the scopes are added.',
          },
        ],
      },
      {
        title: 'Automations',
        tiles: [
          {
            name: 'Automations',
            what: 'Reserved for GitHub automations. Nothing is wired yet. Dashboard GitHub writes already run through the per-user PAT vault, so commits and PRs it opens are attributed to the engineer rather than the service account.',
            why: 'The page exists so analytics and automations share one home instead of GitHub work scattering across the Automation and Maintenance pages.',
          },
        ],
      },
    ],
  },

  {
    id: 'admin',
    title: 'Admin',
    route: '/admin',
    blurb:
      'Controls for the dashboard itself. This page and its tiles require the admin role.',
    sections: [
      {
        title: 'Dashboard controls',
        tiles: [
          {
            name: 'Site Maintenance Mode',
            what: 'Toggles a full-site maintenance page; non-admin users see it while it is on, admins pass through with a banner.',
            why: 'Take the dashboard offline for its own upgrades without confusing users.',
            status: 'admin',
          },
          {
            name: 'Maintenance Date Override',
            what: 'Overrides the auto-computed maintenance date (normally the 3rd Saturday of the month, i.e. the Saturday of the 3rd week) with an explicit date, as was done to move September 2026 from the 19th to the 26th. When on, every maintenance flow — Maintenance Prep, ITC/MGGD tickets, the reminder email, IR-plan filenames — uses the override date. When off, it falls back to the 3rd Saturday. Auto-expires once the override date passes.',
            why: 'Occasionally a maintenance window moves off the standard 3rd Saturday; this shifts every downstream flow in one place instead of hand-editing each ticket and reminder.',
            status: 'admin',
          },
          {
            name: 'Slack Directory (email → handle)',
            what: 'Uploads the slack-cli users cache that maps CMS emails to Slack handles.',
            why: 'PVC cleanup and other tiles resolve a Jenkins admin’s email to a Slack @handle from this directory; it needs refreshing when the roster changes.',
            status: 'admin',
          },
          {
            name: 'User Roles',
            what: 'Lists dashboard users and lets an admin grant or revoke the admin role. Promoting someone to admin emails them automatically, naming who granted it and what admin access allows, and the page reports whether that email was sent.',
            why: 'Admin covers maintenance mode, the maintenance-date override and the audit log, so the person should know they hold it rather than finding out by accident. The change is audit-logged either way, and a failed email never blocks the promotion.',
            status: 'admin',
          },
          {
            name: 'Audit Log',
            what: 'A browsable, filterable log of state-changing actions: who did what, when, and from where.',
            why: 'Accountability for the sensitive automation (rotations, prunes, ticket creation, maintenance applies).',
            status: 'admin',
          },
        ],
      },
    ],
  },
]
