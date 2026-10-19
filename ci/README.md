# Beta environment and its Jenkins job

A second copy of the dashboard runs in the **jfrog-dev** cluster in the
`dashboard-beta` namespace, so design and feature branches can be reviewed on a
real URL without touching production. Production stays in the
`devops-dashboard` namespace and is deployed the way it always was.

- URL: `https://dashboard-beta.cloud.cms.gov` (DNS pending, see below)
- Namespace: `dashboard-beta` (jfrog-dev, account 116248235601)
- Ingress: the existing `nginx` class and the existing NLB, so no new load
  balancer and no new certificate
- Chart: `cms-devops-helm/devops-dashboard`, the same published chart
  production uses

Nothing here lives in or writes to `cmscloud-devops`, and nothing here is
reconciled by Flux. The beta is a plain Helm release.

## How the agent reaches the private API

The jfrog-dev EKS endpoint is private. DNS and routing were already fine, so
reaching it needed nothing but a security group rule. Measured from a pod in
`cbc-tooling`:

| Check | Result |
| --- | --- |
| Egress to Artifactory | reachable |
| DNS for the jfrog-dev API | resolves to `10.242.52.242` |
| NetworkPolicies in `cbc-tooling` | none |
| Routing | both VPCs send `10.0.0.0/8` to the shared TGW `tgw-0f08888a7e2f3e38c` |

The Jenkins CNI runs custom networking with
`AWS_VPC_K8S_CNI_EXTERNALSNAT=true`, so the CNI does not rewrite pod addresses.
The pod subnets route `10.0.0.0/8` through a **private NAT gateway** instead,
one per availability zone, and that gateway does the SNAT, so the address the
API server sees is the gateway's:

| Pod subnet | Address the API server sees |
| --- | --- |
| `jenkins-dev-eks-pods-a` | `10.223.120.42` |
| `jenkins-dev-eks-pods-b` | `10.223.120.91` |
| `jenkins-dev-eks-pods-c` | `10.223.120.170` |

Those three are allowlisted on 443 on the jfrog-dev cluster security group
(`sg-01a3a58b5230697af`), in Terraform at
`terraform/envs/jfrog/modules/eks/main.tf` as
`aws_vpc_security_group_ingress_rule.jenkins_dev_east_api_access`, gated on the
JFrog dev account. They follow the `10.232.32.0/19` rule already on that group.

**Do not use `hostNetwork` here.** An earlier version of this pipeline set it
and allowlisted the node CIDR instead, which worked but earns a GuardDuty EKS
finding for host namespace use, and the account has GuardDuty on with EKS audit
log monitoring enabled. The NAT gateway addresses are also narrower than the
`/23` the node CIDR needed. The agent is an ordinary pod.

Because the job runs in a pod that can reach Artifactory, GitHub and the
cluster, there is no separate build agent and nothing permanent to maintain
inside jfrog-dev.

The podTemplate has two containers on purpose. **Kaniko unpacks the image it
builds into its own root filesystem**, so sharing a container with kubectl and
helm leaves them replaced by whatever was built last: the deploy stage ended up
looking at the frontend's `nginx:alpine` rootfs and could not find kubectl even
by absolute path. Kaniko gets `kaniko`, the deploy gets `tooling`.

## The tooling container

`artifactory.cloud.cms.gov/cms-devops-docker-local/devops-tooling:1.0.1`, built
from `ci/tooling/Dockerfile`: kubectl 1.34.1, helm 3.16.3, aws-cli 2.15.57, jq,
yq, git, and a copy of the kaniko executor it no longer needs now that kaniko
has its own container.

The binaries live in `/opt/tools/bin`, not `/usr/local/bin`, and kubectl and
helm come from upstream rather than `apk` because Alpine 3.20 ships kubectl
1.30, outside the supported skew for 1.34 clusters.

It is built the other way round from what you might expect: the kaniko executor
is copied onto Alpine rather than Alpine tooling being added to the kaniko
image. Kaniko's own image is busybox on scratch with no libc and no package
manager, and the official awscli is dynamically linked against glibc, so it
cannot run there at all. The kaniko executor is a static binary, so it runs
fine on a normal distro.

**Build it in the cluster, not on a laptop.** Zscaler intercepts TLS and
presents its own chain, which a fresh Alpine container does not trust, so the
`curl` steps fail with exit 60. The cluster has clean egress. A kaniko Job in
`dashboard-beta` does it, given a git credential and an Artifactory push
credential, with `DOCKER_CONFIG` pointed somewhere other than `/kaniko` because
the Dockerfile copies out of that tree:

```
--context=git://github.com/CMS-Enterprise/devops-dashboard.git#refs/heads/<branch>
--context-sub-path=ci/tooling
--dockerfile=Dockerfile
--destination=artifactory.cloud.cms.gov/cms-devops-docker-local/devops-tooling:<version>
```

## One-time setup

All four steps are applied. This section is here so it can be rebuilt.

### 1. Namespace, identity and RBAC — applied

```bash
kubectl apply -f ci/rbac/beta-deployer.yaml
```

This creates the `beta-deployer` service account with a **namespace-scoped**
Role. It is deliberately confined; verified with `kubectl auth can-i`:

| Action | Result |
| --- | --- |
| patch/delete deployments in `dashboard-beta` | yes |
| read secrets in `dashboard-beta` | yes |
| anything in `devops-dashboard` | **no** |
| read secrets in `flux-system` | **no** |
| patch HelmReleases | **no** |
| list nodes, list pods across namespaces | **no** |
| create ClusterRoleBindings | **no** |

### 2. Supporting secrets — applied

| Secret | Contents |
| --- | --- |
| `wildcard-cloud-cms-gov-tls` | `*.cloud.cms.gov`, copied from the existing in-cluster wildcard |
| `artifactory-pull-secret` | image pull credentials |
| `dashboard-beta-secrets` | the beta's own configuration, below |

### 3. Jenkins credentials — applied

Three credentials on the tooling controller
(`https://jenkins-dev-east.cloud.cms.gov/tooling`), all created and verified:

| ID | Kind | Purpose |
| --- | --- | --- |
| `github-devops-dashboard` | username + token | cloning this repository |
| `artifactory-push` | username + token | kaniko pushing to `cms-devops-docker-local` |
| `jfrog-dev-beta-deployer-token` | secret text | the `beta-deployer` service account token |

`artifactory-push` is `jfrog-svc-prod`. Push rights were confirmed by
initiating a blob upload against `cms-devops-docker-local` and cancelling it,
which returned 202. Note that asking the registry for a push-scoped token
reports no permissions for this account even though pushing works, so that is
not a usable way to check. The namespace's own `docker-credentials` secret only
pulls, which is why the job writes its own kaniko config instead of mounting it.

`jfrog-dev-beta-deployer-token` is the token minted in the cluster, and it was
verified against the API server with the committed CA before being stored:

```bash
kubectl -n dashboard-beta get secret beta-deployer-token \
  -o jsonpath='{.data.token}' | base64 -d
```

`github-devops-dashboard` is the `cms-cloud-devops-automation` PAT. It needs
that account to have access to this repository: before it was added as a
maintainer, every clone failed with "Repository not found" rather than a
permission error, despite the token carrying `repo` scope. The pipeline does not
take a second git credential, it reuses the job's own via
`scm.userRemoteConfigs`, so this one credential covers both the pipeline file
and the branch being built.

### 4. The job — created

`devops-dashboard-beta` on the tooling controller, Pipeline script from SCM,
script path `ci/Jenkinsfile.beta`. It currently points at the
`feat/beta-pipeline` branch, because that is where the pipeline file lives
until PR #39 merges; **switch it to `main` after the merge**.

Proven end to end on build #15: both images built with kaniko and pushed, helm
rolled the beta out, and the verify stage confirmed the running image carried
that build's tag.

| Parameter | Meaning |
| --- | --- |
| `BRANCH` | the branch to build and deploy, for example a design branch |
| `DEPLOY` | uncheck to build and push images without rolling out |

Note the Timestamper plugin is not installed on this controller, so
`timestamps()` is not a valid option here.

The pipeline definition, `ci/beta-values.yaml` and `ci/jfrog-dev-ca.crt` always
come from the branch the job is configured against. Only the image contents
come from `BRANCH`, which is checked out separately into `src/`. Each run tags
images `beta-<branch>-<build>` and records the source commit in the build
description, so a rollback is a rerun of the earlier build.

`ci/jfrog-dev-ca.crt` is the jfrog-dev API server CA, valid to August 2033. It
is a public certificate, not a secret, and it lets the job verify TLS instead of
skipping verification.

## Reaching the beta today

The DNS record is deferred, so reach the beta with a port-forward:

```bash
kubectl -n dashboard-beta port-forward svc/dashboard-beta-devops-dashboard-frontend 8080:80
# http://localhost:8080
```

Sign in with any username and password. `DEV_MODE` is on, so there is no LDAP
bind and no EUA needed.

## DNS, when it is wanted

The ingress and the TLS certificate are already correct and serving
`*.cloud.cms.gov` for `dashboard-beta.cloud.cms.gov`; the hostname record is
the only missing piece. `cloud.cms.gov` is a Third Packet zone, so it goes
through a WHSD request:

| Field | Value |
| --- | --- |
| Record | `dashboard-beta.cloud.cms.gov` |
| Type | CNAME |
| Target | `jfrog-dev-nlb-0afa4dd96c8f9f6f.elb.us-east-1.amazonaws.com` |

## What the beta deliberately cannot do

Production holds 45 configuration keys, including tokens that delete users,
trigger Jenkins jobs, patch production and send real email. The beta holds
seven, and none of them can write anywhere:

| Key | Why it is present |
| --- | --- |
| `DEV_MODE=true` | any username and password signs in, so no EUA or LDAP bind is needed |
| `JWT_SECRET` | sign-in cannot work without one |
| `ADMIN_USERS` | so the Admin page is reachable |
| `SMTP_ENABLED=false` | the CMS relay is reachable from this cluster, so a true value would send real mail to real people |
| `SCHEDULED_SWEEPS_ENABLED=false` | stops the daily 05:00 sweeps, which exist to refresh production caches |
| `VICTOROPS_API_ID` / `VICTOROPS_API_KEY` | the on-call widget; the only integration verified to be read-only (`victorops_service.py` issues `httpx.get` and nothing else) |

Deliberately absent: `GITHUB_TOKEN`, every `JENKINS_*` token,
`JIRA_TOKEN`, `MGGD_TOKEN`, `CONFLUENCE_TOKEN`,
`ARTIFACTORY_PROD_ADMIN_TOKEN`, `SONARQUBE_*`, `DATADOG_*` and
`OP_SERVICE_ACCOUNT_TOKEN`.

Tiles that need those will render as empty or "not configured". That is the
intended state, not a broken deployment: layout, navigation and styling are
fully exercisable, and no action taken in the beta can reach a production
system.
