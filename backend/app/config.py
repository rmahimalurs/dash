from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LDAP — LDAPS (636) with the baked AD CA cert for chain validation.
    # 636 (regular DC) serves the single awscloud.cms.local domain and exposes the
    # constructed password-expiry attributes the GC (3268/3269) does not.
    LDAP_URL: str = "ldaps://e3ss-prd-dmc01.awscloud.cms.local:636"
    AD_LDAP_CA_FILE: str = "/app/certs/ad-ca.pem"  # CA to validate the DC cert; empty/missing -> encrypt without validation
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_BASE_DN: str = "OU=Accounts,OU=CMS,DC=awscloud,DC=cms,DC=local"
    # Only members of this AD group may sign in. Accepts a bare CN or a full DN
    # (the CN is extracted). Empty string disables the group gate (any AD user).
    LDAP_ACCESS_GROUP: str = "Hybrid-Cloud-DevOPS-Team"

    # AD account unlock — dedicated service account with delegated "reset lockout"
    # (write lockoutTime) permission. Writes require a writable DC on port 389/636,
    # NOT the Global Catalog (3268). Empty creds disable the feature at runtime.
    AD_UNLOCK_URL: str = ""          # e.g. ldaps://<dc>.awscloud.cms.local:636 ; falls back to LDAP_QUERY_URL / LDAP_URL(:389)
    AD_UNLOCK_BIND_DN: str = ""      # delegated svc account, e.g. svc-ad-unlock@awscloud.cms.local
    AD_UNLOCK_BIND_PASSWORD: str = ""
    AD_UNLOCK_SEARCH_BASE: str = ""  # defaults to the domain root derived from LDAP_BASE_DN

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 480

    # CloudBees URLs
    CLOUDBEES_EAST_DEV_URL: str = "https://jenkins-dev-east.cloud.cms.gov"
    CLOUDBEES_EAST_PROD_URL: str = "https://jenkins-east.cloud.cms.gov"
    CLOUDBEES_GOV_DEV_URL: str = "https://jenkins-gc-dev-west.cloud.cms.gov"
    CLOUDBEES_GOV_PROD_URL: str = "https://jenkins-gc-west.cloud.cms.gov"

    # Artifactory URLs
    ARTIFACTORY_DEV_URL: str = "https://artifactory-dev.cloud.cms.gov"
    ARTIFACTORY_PROD_URL: str = "https://artifactory.cloud.cms.gov"

    # SonarQube URLs
    SONARQUBE_DEV_URL: str = "https://sonarqube-dev.cloud.cms.gov"
    SONARQUBE_PROD_URL: str = "https://sonarqube.cloud.cms.gov"

    # Jenkins / CloudBees credentials (used for license API + job triggers)
    JENKINS_USER: str = ""    # personal account (rwrw); used for job triggers and SONARQUBE_JENKINS_TOKEN
    JENKINS_TOKEN: str = ""   # personal CJOC token (prod-east); fallback if env-specific tokens are blank
    # Per-environment service account credentials for CJOC Script Console (license fetch)
    # dso-jenkins-dev-a is admin on dev east + gov dev CJOCs
    # dso-jenkins-prod-a is admin on prod east + gov prod CJOCs
    JENKINS_DEV_USER: str = "dso-jenkins-dev-a"
    JENKINS_PROD_USER: str = "dso-jenkins-prod-a"
    JENKINS_EAST_DEV_TOKEN: str = ""
    JENKINS_EAST_PROD_TOKEN: str = ""
    JENKINS_GOV_DEV_TOKEN: str = ""
    JENKINS_GOV_PROD_TOKEN: str = ""
    # CJOC URLs for validating/reusing persistent per-user tokens and legacy logout cleanup.
    JENKINS_CJOC_URL: str = "https://jenkins-east.cloud.cms.gov/cjoc"
    JENKINS_DEV_EAST_CJOC_URL: str = "https://jenkins-dev-east.cloud.cms.gov/cjoc"

    # Artifactory license API credentials
    # Prod: basic auth — "JFrog PROD AD Credentials" in JFrog vault (jfrog-svc-prod)
    # Dev:  Bearer token — decoded from jfrog-admin-token secret in jfrog/dev k8s cluster
    ARTIFACTORY_PROD_USER: str = "jfrog-svc-prod"
    ARTIFACTORY_PROD_PASSWORD: str = ""
    ARTIFACTORY_PROD_ADMIN_TOKEN: str = ""  # Bearer JWT from jfrog-admin-token secret in prod cluster
    ARTIFACTORY_DEV_TOKEN: str = ""   # Bearer JWT; takes precedence over user/password for dev
    ARTIFACTORY_DEV_USER: str = ""
    ARTIFACTORY_DEV_PASSWORD: str = ""

    # SonarQube license API credentials (basic auth against /api/editions/show_license)
    # Both prod and dev use same admin account — "SonarQube - Admin" in SonarQube vault
    SONARQUBE_PROD_USER: str = "admin"
    SONARQUBE_PROD_PASSWORD: str = ""
    SONARQUBE_DEV_USER: str = "admin"
    SONARQUBE_DEV_PASSWORD: str = ""

    # SonarQube server-wide licensed LOC tracking (CLDSPT-112879). Same admin
    # creds as above. Checked hourly; emails SONARQUBE_LOC_NOTIFY_EMAILS on a
    # status escalation (ok->warning->critical), not on every tick.
    SONARQUBE_LOC_CAP: int = 50_000_000
    SONARQUBE_LOC_NOTIFY_EMAILS: str = "CMS_Cloud_DevOps@cms.hhs.gov"
    SONARQUBE_LOC_STATE_FILE: str = "./data/sonarqube_loc_alert.json"

    # GitHub status (githubstatus.com) alerting. Checked every 5 minutes;
    # posts to Slack #cms-cloud-devops-internal on a status change (down or
    # recovered), not on every tick, same shape as the SonarQube LOC alert.
    GITHUB_STATUS_STATE_FILE: str = "./data/github_status_alert.json"

    # CloudBees CI license expiry — optional manual fallback (YYYY-MM-DD, e.g. "2027-03-31")
    # Normally fetched live via Groovy script on each CJOC; set these only if that fails
    LICENSE_EXPIRY_CLOUDBEES_EAST_DEV: str = ""
    LICENSE_EXPIRY_CLOUDBEES_EAST_PROD: str = ""
    LICENSE_EXPIRY_CLOUDBEES_GOV_DEV: str = ""
    LICENSE_EXPIRY_CLOUDBEES_GOV_PROD: str = ""

    # SonarQube Jenkins job
    SONARQUBE_JOB_URL: str = "https://jenkins-east.cloud.cms.gov/sonarqube/job/deploy-sonarqube"
    SONARQUBE_JENKINS_TOKEN: str = ""  # token for the /sonarqube controller (differs from CJOC token)

    # GitHub
    GITHUB_TOKEN: str = ""          # service-account PAT (fallback when a user has no PAT)
    # Optional split credential for the enterprise/Copilot/billing reads, which
    # need admin:enterprise. Unset everywhere today: the service-account PAT in
    # the cluster already carries admin:enterprise, copilot and audit_log, so
    # those reads run on GITHUB_TOKEN via the fallback below.
    GITHUB_BILLING_TOKEN: str = ""
    GITHUB_ORG: str = "CMS-Enterprise"
    GITHUB_DEFAULT_REPO: str = ""
    # Commit identity used for the service-account fallback (when a user has no PAT).
    # Enterprise slug for enterprise-level reads. Not derivable from the org name,
    # and listing it requires the enterprise scope, so it is configured.
    GITHUB_ENTERPRISE_SLUG: str = "centers-for-medicare-medicaid-services"
    GITHUB_COMMIT_NAME: str = "CMS Cloud DevOps"
    GITHUB_COMMIT_EMAIL: str = "cms-cloud-devops@cms.hhs.gov"

    # Slack
    SLACK_BOT_TOKEN: str = ""
    # Incoming webhook URLs, one per channel. CMS Slack administration does not
    # issue bot tokens, so these are the supported path; a webhook is bound to
    # the channel it was created for and ignores any channel in the payload.
    SLACK_WEBHOOK_APPROVALS: str = ""   # #github-access-approvals-internal
    SLACK_WEBHOOK_TEAM: str = ""        # #cms-cloud-devops-internal

    # Jira (jiraent.cms.gov)
    JIRA_URL: str = "https://jiraent.cms.gov"
    JIRA_TOKEN: str = ""
    JIRA_PROJECT: str = "DMSC"
    # ITC maintenance ticket automation
    # Comma-separated emails allowed to create/close ITC/MGGD tickets
    ITC_AUTHORIZED_EMAIL: str = "jerry.hendren1@cms.hhs.gov"
    # Comma-separated AD sAMAccountNames also allowed (use when mail attribute differs from CMS email)
    ITC_AUTHORIZED_USERS: str = ""
    ITC_ASSIGNEE_JIRA_USER: str = "H4QT"        # Patrick Hendren's Jira username

    # MGGD Jira (jira.cms.gov — separate GovCloud instance)
    MGGD_URL: str = "https://jira.cms.gov"
    MGGD_TOKEN: str = ""
    MGGD_GTL_USER: str = "VHJN"                  # Lijun Shao
    MGGD_POC_NAME: str = "Max Rahimi"
    MGGD_POC_PHONE: str = "443-745-6312"
    MGGD_POC_EMAIL: str = "masood.rahimi1@cms.hhs.gov"
    MGGD_SIGNOFF_NAME: str = "Masood Rahimi"

    # VictorOps — portal URL used for frontend links (overridden by configmap)
    VICTOROPS_URL: str = "https://portal.victorops.com/client/cms-vdc"
    # VictorOps — REST API base URL (never overridden; kept separate from portal URL)
    VICTOROPS_API_URL: str = "https://api.victorops.com/api-public/v1"
    VICTOROPS_API_ID: str = ""
    VICTOROPS_API_KEY: str = ""
    VICTOROPS_DEVOPS_TEAM_SLUG: str = "team-yJsTfLQYgVFmBlcj"

    # Confluence
    CONFLUENCE_URL: str = "https://confluenceent.cms.gov"
    CONFLUENCE_SPACE: str = "COM"
    CONFLUENCE_TOKEN: str = ""
    CONFLUENCE_MAINT_RETRO_PARENT_ID: str = "1085018051"   # COM/Maintenance Retros
    CONFLUENCE_SPRINT_RETRO_PARENT_ID: str = "1129215321"  # COM/DevOps Sprint Retros

    # Datadog
    DATADOG_API_BASE: str = "https://api.ddog-gov.com"
    DATADOG_API_KEY: str = ""
    DATADOG_APP_KEY: str = ""
    DATADOG_STATE_FILE: str = "./data/datadog_downtime.json"

    # Onboarding
    ONBOARDING_CONFLUENCE_PAGE_ID: str = ""

    # LDAP Service Accounts — sAMAccountNames for password expiry monitoring
    LDAP_QUERY_URL: str = ""  # Overrides LDAP_URL for attribute queries (use port 389, not 3268)

    # CloudBees service accounts
    SA_CLOUDBEES_PROD_A: str = "dso-jenkins-prod-a"
    SA_CLOUDBEES_PROD_B: str = "dso-jenkins-prod-b"
    SA_CLOUDBEES_DEV_A: str = "dso-jenkins-dev-a"
    SA_CLOUDBEES_DEV_B: str = "dso-jenkins-dev-b"
    SA_CLOUDBEES_GOVCLOUD: str = "iusg-gc-cbj-prod"
    SA_CLOUDBEES_SANDBOX: str = "dso-jenkins-sandbox"

    # Artifactory service accounts
    SA_ARTIFACTORY_PROD: str = "jfrog-svc-prod"
    SA_ARTIFACTORY_DEV: str = "dso-ss-jfrog-dev"

    # SonarQube service accounts
    SA_SONARQUBE_PROD: str = "dso-ss-prod"
    SA_SONARQUBE_DEV: str = "dso-ss-dev"

    # Datadog Synthetics service accounts
    SA_DATADOG_SYNTHETICS_PROD: str = "dso-synthetics-a"
    SA_DATADOG_SYNTHETICS_DEV: str = "dso-synthetics-b"
    # Datadog Synthetic global-variable ids holding each SA's password
    # (Org Settings > Synthetic Tests > Global Variables). Rotation writes the new
    # AD password into the matching secure variable.
    DATADOG_SYNTHETICS_VAR_A: str = "c5a8be3d-d783-4b46-b50a-e3941b843d45"  # DSO_SYNTHETICS_A_PASSWORD
    DATADOG_SYNTHETICS_VAR_B: str = "caff1015-00b5-4cea-83c0-5423f616438f"  # DSO_SYNTHETICS_B_PASSWORD

    # SMTP relay service accounts
    SA_SMTP_PROD: str = "dso-smtp-prod"
    SA_SMTP_DEV: str = "dso-smtp-dev"

    # CMS internal SMTP relay (outbound mail from the dashboard).
    # The relay accepts unauthenticated relay from allowlisted internal source
    # IPs; it requires STARTTLS before MAIL FROM. Port 25 + STARTTLS, no auth.
    SMTP_ENABLED: bool = True
    SMTP_RELAY_HOST: str = "smtp.cloud.internal.cms.gov"
    SMTP_RELAY_PORT: int = 25
    SMTP_TIMEOUT: int = 20
    SMTP_FROM: str = "devops-dashboard@cms.hhs.gov"
    SMTP_FROM_NAME: str = "CMS Cloud DevOps Dashboard"
    # Internal relay presents an internal cert; opportunistic STARTTLS w/o
    # verification (source IP is already allowlisted). Set true to verify.
    SMTP_TLS_VERIFY: bool = False

    # PVC-cleanup ADO analysis email — DevOps distro cc'd on every send (same
    # list the Datadog PVC monitor 283161 notifies).
    PVC_EMAIL_CC: str = "CMS_Cloud_DevOps@cms.hhs.gov"

    # CBJ resource-waste ADO email — DevOps distro cc'd on every send.
    CBJ_WASTE_EMAIL_CC: str = "CMS_Cloud_DevOps@cms.hhs.gov"

    # Monthly-maintenance ticket notifications: reminder (13 days before) +
    # per-ticket confirmations. Comma-separated recipients (Patrick, Meghana, Max).
    # Recipients beyond the maintenance roster itself, which maint_notify
    # resolves from AD. These are the comms and management side, who are not on
    # the roster and so would not be picked up from it.
    MAINT_NOTIFY_EMAILS: str = (
        "patrickhendren@samtek.io,meghana.reddy@samtek.io,swamy.raj@samtek.io"
    )
    MAINT_REMINDER_DAYS: int = 13
    MAINT_REMINDER_STATE_FILE: str = "./data/maint_reminder.json"

    # CLDSPT ticketing — documents each real PVC prune. Uses JIRA_TOKEN.
    # CLDSPT ("CMS Cloud Support") is a JSM service desk: valid issue types are
    # Access / Service Request / Ask a Question / Incident / Sub-task (NO "Task").
    # A Service Request requires four fields (option IDs discovered from the
    # project; createmeta is restricted). Application Name is a free-form array —
    # defaults to the controller name when CLDSPT_APP_NAME is empty.
    CLDSPT_PROJECT: str = "CLDSPT"
    CLDSPT_ISSUE_TYPE: str = "Service Request"
    CLDSPT_REQUEST_TYPE_ID: str = "21026"   # Request Type: CloudBees Core (Jenkins)
    CLDSPT_URGENCY_ID: str = "21411"        # How urgent: Not urgent (within 5 business days)
    CLDSPT_PROD_ID: str = "21406"           # Production system?: Yes (prod-east controllers)
    CLDSPT_APP_NAME: str = ""               # Application Name; blank = use the controller name
    # Who CLDSPT's own intake routing assigns a new self-service ticket to by
    # default, before anyone on the team has picked it up. A routing-rule
    # change, not a fact about the world -- kept as a setting rather than a
    # hardcoded constant so updating it doesn't need a code change.
    CLDSPT_DEFAULT_QUEUE_ASSIGNEE: str = "RAAX"

    # DMSC prune ticket — documents each real PVC prune (replaces the CLDSPT
    # service request). Assigned to the triggering engineer, pointed 1, added to
    # the DMSC board's active sprint, and auto-closed Fixed when the prune finishes.
    DMSC_PRUNE_PROJECT: str = "DMSC"
    DMSC_PRUNE_ISSUE_TYPE: str = "Task"
    DMSC_PRUNE_STORY_POINTS: int = 1
    DMSC_FIXED_RESOLUTION_ID: str = "10200"   # Jira resolution "Fixed"

    # AWS region for boto3 calls (AMI lookups etc.)
    AWS_REGION: str = "us-east-1"

    # IAM role ARN to assume for GovCloud (us-gov-west-1) API calls (optional).
    # Format: arn:aws-us-gov:iam::<account-id>:role/<role-name>
    GOVCLOUD_DEV_ROLE_ARN: str = ""

    # IAM user credentials for GovCloud (us-gov-west-1) API calls.
    # Takes precedence over GOVCLOUD_DEV_ROLE_ARN when set.
    # GOVCLOUD_* = gc-dev-west account (021175979101); GOVCLOUD_PROD_* = gc-prod-west
    # (020847197482). Used for SOPS-encrypting the CBJ GovCloud TLS secrets with each
    # account's SOPS KMS key (kms:Encrypt granted to svc-devops-dashboard in-account).
    GOVCLOUD_AWS_ACCESS_KEY_ID: str = ""
    GOVCLOUD_AWS_SECRET_ACCESS_KEY: str = ""
    GOVCLOUD_PROD_AWS_ACCESS_KEY_ID: str = ""
    GOVCLOUD_PROD_AWS_SECRET_ACCESS_KEY: str = ""

    # Cross-account access to the Jenkins prod-east AWS account (478919403635) — used by the
    # Copy Controllers automation to read cbc-<controller>-assume-role IAM policies.
    # Set EITHER the role ARN (preferred, requires Pod Identity trust) OR the IAM user creds.
    JENKINS_PROD_EAST_ROLE_ARN: str = ""
    JENKINS_PROD_EAST_AWS_ACCESS_KEY_ID: str = ""
    JENKINS_PROD_EAST_AWS_SECRET_ACCESS_KEY: str = ""

    # Cross-account role in the Jenkins dev-east account (280350076387) for the CBJ
    # cert-export SOPS encrypt (kms:Encrypt on the dev-east SOPS key). Blank until the
    # role is created + applied; the cbj/dev-east tile errors clearly if unset.
    JENKINS_DEV_EAST_ROLE_ARN: str = ""

    # ── Snyk (SaaS) license/subscription ──────────────────────────────────────
    # Read the subscription end date from Snyk's hidden billing API for the
    # license modal + OE readiness. SNYK_TOKEN is a service-account token (blank =
    # falls back to manual). Group = CMS "Cms-ent"; tenant resolved from the group
    # when SNYK_TENANT_ID is blank.
    SNYK_API_URL: str = "https://api.snyk.io"
    SNYK_TOKEN: str = ""   # live billing lookup needs a personal token; blank for now
    SNYK_GROUP_ID: str = "a7c55a34-78fa-4b9b-909c-ee7403e5c543"
    SNYK_TENANT_ID: str = "6a858098-81bd-478f-b91a-2897a78249f9"
    # Manual current-license expiry used until a service-account token is set.
    SNYK_LICENSE_EXPIRY: str = "2027-09-30"

    # ── Wildcard cert export automation ───────────────────────────────────────
    # 1Password service-account token (has access to the vault below). Used to
    # store the exported cert, chain, TLS key, and passphrase.
    # The expiry of the token in force. Seeds the reminder before any refresh has
    # run; after one, the real expiry from JFrog is kept in the state file below.
    JFROG_TOKEN_EXPIRES_AT: str = "2026-11-17"
    JFROG_TOKEN_STATE_FILE: str = "/app/data/jfrog_token_expiry.json"
    JFROG_TOKENS_URL: str = "https://releases.jfrog.io/access/api/v1/tokens"
    OP_SERVICE_ACCOUNT_TOKEN: str = ""
    # 1Password vault (name or ID) where the wildcard cert entries are stored.
    OP_VAULT: str = ""
    # Cross-account IAM role in the PROD account for the export automation:
    # needs acm:ExportCertificate + kms:Encrypt on the prod wildcard cert / KMS key.
    # Dev uses the dashboard's own Pod Identity (must be granted the same in dev).
    CERT_EXPORT_PROD_ROLE_ARN: str = ""

    # CJOC URL for the prod-east CloudBees Operations Center (used to query controllers'
    # RBAC / admins via the Script Console). Defaults to CLOUDBEES_EAST_PROD_URL + /cjoc.
    JENKINS_PROD_EAST_CJOC_URL: str = "https://jenkins-east.cloud.cms.gov/cjoc"
    # Tooling Jenkins on dev-east that hosts the cbc-onboarding-casc job
    JENKINS_DEV_EAST_TOOLING_URL: str = "https://jenkins-dev-east.cloud.cms.gov/tooling"
    CBC_ONBOARDING_JOB_PATH: str = "job/automation/job/cbc-onboarding-casc"

    # Comma-separated usernames that always receive admin role on login
    # e.g. ADMIN_USERS=mrahimi,jdoe
    ADMIN_USERS: str = ""

    # Paths for RBAC roles file and audit log directory
    # Relative paths resolve from the backend/ working directory
    ROLES_FILE: str = "./data/roles.json"
    AUDIT_DIR: str = "./data/audit"

    # User profile storage (JSON per user + avatar binaries) — lives on the EFS volume
    PROFILES_DIR: str = "/app/data/profiles"
    AVATAR_MAX_BYTES: int = 2 * 1024 * 1024   # 2 MiB

    # Site-wide maintenance mode flag (EFS-persisted so it survives restarts)
    MAINTENANCE_STATE_FILE: str = "/app/data/maintenance.json"
    RELEASE_ANNOUNCE_STATE_FILE: str = "/app/data/release_announced.json"
    RELEASE_ANNOUNCE_ENABLED: bool = True
    PRIMARY_NAMESPACE: str = "devops-dashboard"  # beta and laptops run the same image elsewhere

    # Admin maintenance-date override (EFS-persisted). When enabled + not yet past,
    # replaces the computed 3rd-Saturday maintenance date everywhere.
    MAINT_DATE_OVERRIDE_STATE_FILE: str = "/app/data/maint_date_override.json"

    # ── Controller PVC cleanup (CloudBees Jenkins) ──────────────────────────
    # Datadog cluster_name tag whose controller PVCs we watch. Mirrors monitor
    # 283161 ([Kubernetes] Jenkins ... Controllers PVC Usage), prod-east only.
    PVC_CLEANUP_CLUSTER: str = "jenkins-prod-east"
    # Datadog monitor that already tracks this per-namespace. We read its group
    # states (monitors_read scope) rather than a raw timeseries query, because
    # the dashboard's Datadog app key lacks the timeseries_query scope.
    PVC_MONITOR_ID: int = 283161
    # Thresholds match the monitor: crit at 80% ("over"), warn at 75%
    # ("approaching"). Namespaces below the warn line are not surfaced.
    PVC_WARN_THRESHOLD: float = 0.75
    PVC_CRIT_THRESHOLD: float = 0.80
    # Slim Slack directory (email -> handle) staged on EFS by the admin upload
    # endpoint; the backend cannot run slack-cli (needs a browser session token).
    SLACK_DIRECTORY_FILE: str = "/app/data/slack-users.json"
    # HARD KILL SWITCH for the destructive prune. False = the service refuses any
    # real deletion (dry-run / preview still work). Actual pruning in prod is
    # impossible until this is explicitly set True in the deployed secret/config.
    PVC_PRUNE_ENABLED: bool = False

    # Audit log retention: files older than this many days are deleted by the cleanup task
    AUDIT_RETENTION_DAYS: int = 90

    # Scheduled daily sweeps (controller-user audit + CBJ podTemplate). An in-app
    # asyncio scheduler fires at SCHEDULED_SWEEP_HOUR in SCHEDULED_SWEEP_TZ each day.
    # Safe because the backend runs replicas:1. Set ENABLED=false to disable.
    SCHEDULED_SWEEPS_ENABLED: bool = True
    SCHEDULED_SWEEP_HOUR: int = 5                    # 5 AM
    SCHEDULED_SWEEP_TZ: str = "America/New_York"     # CMS Eastern

    # Logging level for the backend (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    LOG_LEVEL: str = "INFO"

    # Local dev — bypasses LDAP, accepts any login
    DEV_MODE: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
