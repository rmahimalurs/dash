# CMS DMSC DevOps Dashboard

An internal web application that serves as a central tooling hub for the CMS Division of Medicaid and CHIP Services (DMSC) DevOps team. It provides unified visibility and control over critical infrastructure: license and certificate monitoring, service-account health, self-service account operations, and automated maintenance orchestration across JFrog Artifactory, CloudBees CI (Jenkins), and SonarQube in both commercial and GovCloud environments.

**Live:** https://devops-dashboard.cloud.cms.gov

## Features

### Dashboard
- TLS certificate expiry monitoring across all tool endpoints (concurrent checks)
- License expiry tracking (Artifactory, SonarQube, CloudBees)
- Active Directory **service-account password expiry** monitoring — CloudBees (dev/prod/sandbox, commercial + GovCloud), Artifactory, SonarQube, Datadog Synthetics, and SMTP relay accounts
- Live on-call display sourced from the VictorOps rotation (primary + next)
- Quick links to all DevOps tools and portals
- Dark mode

### Automation
A dedicated page of self-service tiles, grouped by tool:

- **Active Directory**
  - Unlock a locked-out account (clears `lockoutTime`)
  - Reset an account password (`unicodePwd` over LDAPS), with optional auto-generated password and save/update to 1Password
- **JFrog Artifactory**
  - Update / test the LDAP manager password (sync-only), or **full rotation** (reset AD + save to 1Password + update Artifactory via the Access API)
  - Unlock a locked-out Artifactory user
  - Repository cache refresh / reindex
  - Export the `*.cloud.cms.gov` wildcard cert from ACM into 1Password + a SOPS-encrypted secret PR
- **CloudBees Jenkins**
  - Update / test the CJOC LDAP manager password (sync-only), or **full rotation** (per env), with auto-generate + 1Password
  - Copy a prod controller into dev (jobs, credentials, plugins, network policies)
  - Export the wildcard cert (pending a jenkins-account KMS key)

Rotation is deliberately ordered **reset AD → save to 1Password → update the tool**, so a generated password is captured before the tool update; a tool-update failure is reported as a partial success (re-run the sync to finish).

### Maintenance
The Maintenance page automates the monthly DevOps maintenance cycle:
- CloudBees CI, JFrog Artifactory, and SonarQube upgrade modals — each reads the current versions from the maintenance branch and the latest from upstream (GitHub / ArtifactHub / registries), shows release notes, and commits the diff
- Karpenter chart + node AMI (controller/agent) updates, with tfvars kept in sync with the node-class
- ITC and MGGD maintenance ticket generation (with Excel attachments)
- Maintenance / sprint retro Confluence page creation
- Datadog downtime window management around the maintenance window
- GitHub maintenance-branch creation (idempotent, `jul26-maint` style)

### Site maintenance mode
Admin-toggled full-site "Under Maintenance" page for non-admins; admins pass through to toggle it back off.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript, Vite, Tailwind CSS, React Router |
| Backend | FastAPI (Python 3.12), Uvicorn, httpx, boto3, ldap3, onepassword-sdk |
| Auth | CMS Active Directory over **LDAPS** + JWT (httpOnly cookie) |
| Container | Docker (multi-stage build), nginx for SPA serving |
| Packaging | Helm 3, pushed to Artifactory |
| Secrets | SOPS + AWS KMS; 1Password service account for runtime reads/writes |
| Deployment | Flux HelmRelease (GitOps) on the JFrog dev EKS cluster |

## Architecture

```
Browser
  └── nginx (frontend pod)          React SPA, proxies /api → backend
        └── FastAPI (backend pod)   REST API + LDAPS auth + AWS / Jenkins / Jira / 1Password
              └── AWS EKS (jfrog-dev)  EKS Pod Identity; cross-account IAM roles for GovCloud
                                        + ACM cert export in the JFrog prod account
```

- **Auth / AD:** all LDAP traffic runs over **LDAPS (port 636)** and validates the DC certificate against the baked `awscloud-Temp-CA` cert (`/app/certs/ad-ca.pem`). AD writes (unlock / reset / rotate) bind as a delegated service account and make a **single** bind attempt with no retry, so a bad bind cannot flood AD and trip a lockout.
- **AWS:** the backend runs with an EKS Pod Identity in the JFrog dev account and assumes cross-account roles for GovCloud EC2 describes and for exporting the ACM wildcard cert from the JFrog prod account.
- **1Password:** a vault-scoped service-account token is used via the async 1Password SDK to read/write service-account and cert entries.

### Jenkins authentication

Dashboard login reuses one personal Jenkins API token for prod-east and one for
dev-east across sessions. A token is created only the first time an engineer
signs in (or after that token has been revoked), instead of creating two more
tokens at every login. Token values are encrypted in the engineer's existing
password-derived profile vault; sessions continue to use the same Jenkins
authentication behavior as before.

The dashboard's existing configured credentials remain the fallback if a
personal token cannot be issued:

- SonarQube job parameters and deployment: `JENKINS_USER` + `SONARQUBE_JENKINS_TOKEN`.
- Dev-east controller onboarding: `JENKINS_DEV_USER` + `JENKINS_EAST_DEV_TOKEN`,
  retaining the existing `JENKINS_TOKEN` fallback when the dev-east token is unset.

Token reuse is checked against each CJOC at login. Jenkins continues to attribute
actions to the engineer, and the dashboard audit log continues to record the
requesting engineer. Job parameters, controller-copy behavior, AD authentication,
roles, and the GitHub PAT vault are unchanged.

Logout revokes session-only tokens in sessions created before this change. Reused
tokens remain encrypted for future sessions and are not revoked on logout. Older
orphaned `dashboard-*` tokens are not automatically revoked; review their usage
in Jenkins before removing them.

Run the regression tests with the backend dependencies installed:

```sh
cd backend
python -m unittest discover -s tests -v
```

The tests mock external services and use temporary profile/audit storage; they do
not create tokens, run Jenkins jobs, or change live infrastructure.

## Local Development

**Prerequisites:** Docker Desktop running. Nothing else, and no CMS network
access or credentials are needed to get the UI up.

```bash
cp .env.example .env.local
make dev                     # or: docker compose up
```

- Frontend dev server: http://localhost:3000 (Vite, hot reload)
- Backend API + Swagger UI: http://localhost:8000/api/docs

`.env.example` ships with `DEV_MODE=true`, which bypasses LDAP and accepts **any
username and password**, so you can sign in immediately. Every credential below
is blank by default and each feature reports that it is not configured rather
than failing, so the dashboard runs with none of them filled in. Add only the
ones for the area you are working on.

To get the Admin page, put your EUA in `ADMIN_USERS` in `.env.local`.

Both services hot reload from your working tree: the frontend through Vite, the
backend through uvicorn `--reload`.

Stop with `Ctrl-C`, or `docker compose down` if you started it detached.

## Environment Variables

Secrets are injected at runtime from a Kubernetes secret (SOPS-encrypted). For local dev use `.env.local` (never commit). `backend/app/config.py` is the source of truth for every setting.

### Required

| Variable | Description |
|---|---|
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | AD service account used to search users on login |
| `JWT_SECRET` | Secret key for JWT signing |
| `GITHUB_TOKEN` / `GITHUB_ORG` | GitHub PAT (repo scope) + org (`CMS-Enterprise`) |
| `JENKINS_USER` / `JENKINS_TOKEN` | Jenkins credentials for job triggers / passthrough |
| `JIRA_TOKEN` / `MGGD_TOKEN` / `CONFLUENCE_TOKEN` | Jira, MGGD (jira.cms.gov), Confluence PATs |
| `VICTOROPS_API_ID` / `VICTOROPS_API_KEY` | VictorOps REST API credentials |
| `ARTIFACTORY_PROD_ADMIN_TOKEN` | Artifactory admin Bearer token (LDAP password reset + user unlock) |
| `OP_SERVICE_ACCOUNT_TOKEN` / `OP_VAULT` | 1Password service-account token (vault-scoped) + default vault (`DevOps`) |
| `GOVCLOUD_AWS_ACCESS_KEY_ID` / `GOVCLOUD_AWS_SECRET_ACCESS_KEY` | IAM user for `us-gov-west-1` EC2 describes |

### AD account operations (unlock / reset / rotate)

| Variable | Description |
|---|---|
| `AD_UNLOCK_URL` | Writable-DC LDAPS URL, e.g. `ldaps://e3ss-prd-dmc01.awscloud.cms.local:636` (NOT the GC on 3268) |
| `AD_UNLOCK_BIND_DN` / `AD_UNLOCK_BIND_PASSWORD` | Delegated svc account with *Reset lockout* + *Reset password* rights |
| `AD_UNLOCK_SEARCH_BASE` | Optional; defaults to the domain root derived from `LDAP_BASE_DN` |

### Optional / Defaulted

| Variable | Default | Description |
|---|---|---|
| `LDAP_URL` | `ldaps://e3ss-prd-dmc01.awscloud.cms.local:636` | LDAPS server (login, queries) |
| `LDAP_QUERY_URL` | `` | Overrides `LDAP_URL` for attribute queries; falls back to it |
| `AD_LDAP_CA_FILE` | `/app/certs/ad-ca.pem` | CA to validate the DC cert; missing → encrypt without validation |
| `LDAP_BASE_DN` | `OU=Accounts,OU=CMS,DC=awscloud,DC=cms,DC=local` | User search base |
| `LDAP_ACCESS_GROUP` | `Hybrid-Cloud-DevOPS-Team` | Only members may sign in (empty disables the gate) |
| `CERT_EXPORT_PROD_ROLE_ARN` | `` | Cross-account role to export the ACM wildcard cert from JFrog prod |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `AWS_REGION` | `us-east-1` | AWS region for boto3 |
| `ADMIN_USERS` | `` | Comma-separated usernames granted admin on first login |
| `AUDIT_RETENTION_DAYS` | `90` | Days before audit log files are GC'd |
| `MAINTENANCE_STATE_FILE` | `/app/data/maintenance.json` | Site-maintenance-mode flag file |
| `DEV_MODE` | `false` | Bypass LDAP auth locally |

## Building and Deploying

### Docker images (`linux/amd64`, pushed to Artifactory)

Images are published to the CMS Artifactory Docker registry:

- **Registry:** `artifactory.cloud.cms.gov`
- **Repository:** `cms-devops-docker-local`
- **Images:** `devops-dashboard-backend`, `devops-dashboard-frontend`

**1. Authenticate to Artifactory** (one-time per machine). You must push as the
service account **`jfrog-svc-prod`** — personal accounts (e.g. `rwrw`) do **not**
have deploy/push permission on `cms-devops-docker-local`, so a `docker push` with
them fails with `403`. Get the `jfrog-svc-prod` credentials from the 1Password
"jfrog-svc-prod" item (never commit them):

```bash
docker login artifactory.cloud.cms.gov
# Username: jfrog-svc-prod
# Password: <from 1Password>
```

**2. Build and push both images** (requires `docker buildx`; builds `linux/amd64`
and pushes in a single step):

```bash
make docker-build VERSION=x.y.z
```

Under the hood this runs, for each image (see the `Makefile`):

```bash
docker buildx build --platform linux/amd64 \
  -t artifactory.cloud.cms.gov/cms-devops-docker-local/devops-dashboard-backend:x.y.z \
  ./backend --push
```

Produces `…/devops-dashboard-backend:x.y.z` and `…/devops-dashboard-frontend:x.y.z`.

> **Always bump the tag on every build.** `imagePullPolicy: Always` does not
> restart already-running pods, and reusing a tag serves the stale image — so a
> reused tag can silently deploy old code. Use the next `x.y.z` each time.

### Deployment (Flux / GitOps)

Deployed to the JFrog dev EKS cluster via a Flux `HelmRelease` in `cmscloud-devops`
(`kubernetes/envs/jfrog/dev/releases/devops-dashboard.yaml`). Bump the image tags there, then:

```bash
kubectl apply -f kubernetes/envs/jfrog/dev/releases/devops-dashboard.yaml
flux reconcile helmrelease devops-dashboard -n flux-system
```

Config-only changes (ConfigMap/secret) also need `kubectl rollout restart deploy/…-backend` — Flux reconcile alone doesn't restart pods when only config changes.

## Secret Management

Secrets are SOPS-encrypted with an AWS KMS key in `cmscloud-devops`:

```bash
sops -d kubernetes/envs/jfrog/dev/secret/devops-dashboard-secrets.enc.yaml   # view
sops    kubernetes/envs/jfrog/dev/secret/devops-dashboard-secrets.enc.yaml   # edit in place
```

The AD CA cert baked into the image lives at `backend/certs/ad-ca.pem` (sourced from the `gold-image-trusted` secret; renew before it expires).

## Project Structure

```
devops-dashboard/
├── backend/
│   ├── app/
│   │   ├── routers/         # FastAPI routes (auth, dashboard, maintenance, automation, admin, profile)
│   │   ├── services/        # ldap_accounts, ad_unlock, automation_service, cloudbees_ldap,
│   │   │                    #   jfrog_maintenance, cloudbees_maintenance, cert_export,
│   │   │                    #   onepassword_service, password_gen, copy_controller, jira/confluence …
│   │   ├── ldap_util.py     # shared LDAPS Server factory (CA validation)
│   │   ├── config.py        # Pydantic settings (all env vars)
│   │   └── main.py          # FastAPI app factory
│   ├── certs/ad-ca.pem      # baked AD CA cert for LDAPS validation
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/client.ts    # typed API client
│   │   ├── components/widgets/  # ActionCard-based automation + maintenance widgets
│   │   └── pages/           # Dashboard, Automation, Maintenance, Jira, Admin, Profile, UnderMaintenance
│   └── package.json
├── helm/devops-dashboard/   # Helm chart
├── Makefile
└── docker-compose.yml
```

## Access and Roles

| Role | Access |
|---|---|
| `user` | Dashboard, Automation, Maintenance, Jira, Profile |
| `admin` | All user access + Admin panel (role management, audit logs, site maintenance toggle) |

Sign-in is gated on membership of the `LDAP_ACCESS_GROUP` AD group. Roles live in a persistent JSON file on EFS (`/app/data/roles.json`); seed admins via `ADMIN_USERS`. Some Jira/ITC/MGGD actions are further gated to an authorized-users allowlist.
