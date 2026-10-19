import axios from 'axios'

/**
 * Extract a human-readable message from an axios/FastAPI error.
 *
 * FastAPI returns 422 validation errors as `detail: [{loc, msg, type}, ...]` (an
 * array of objects). Passing that array straight into React state and rendering
 * it as a child crashes the page ("Objects are not valid as a React child"),
 * which shows up as a white screen. Always route API errors through this so the
 * result is guaranteed to be a string.
 */
export function apiErrorMessage(err: any, fallback = 'Something went wrong.'): string {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msg = detail
      .map((d: any) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: any) => x !== 'body').join('.') : ''
        return [loc, d?.msg].filter(Boolean).join(': ')
      })
      .filter(Boolean)
      .join('; ')
    if (msg) return msg
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return err?.message || fallback
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface User {
  id: number
  username: string
  email: string
  display_name: string
  team: string
  role: 'admin' | 'user'
  job_title: string
  slack_handle: string
  phone: string
  jira_authorized?: boolean
  avatar_url?: string | null
}

export interface AdminUser {
  username: string
  display_name: string
  email: string
  role: 'admin' | 'user'
}

export interface AuditEvent {
  timestamp: string
  event: string
  username: string
  ip: string | null
  details: Record<string, unknown>
}

export interface AuditLogResult {
  events: AuditEvent[]
  total: number
  page: number
  page_size: number
}

export interface Certificate {
  tool: string
  env: string
  domain: string
  expiry_date: string | null
  days_remaining: number | null
  status: 'ok' | 'warning' | 'critical' | 'unknown'
  error?: string
}

export interface License {
  tool: string
  env: string
  expiry_date: string | null
  days_remaining: number | null
  status: 'ok' | 'warning' | 'critical' | 'unknown' | 'manual' | 'check_manually'
  notes?: string
  error?: string | null
}

export interface SonarQubeLoc {
  tool: string
  env: string
  total_ncloc: number | null
  cap: number | null
  percent_used: number | null
  status: 'ok' | 'warning' | 'critical' | 'unknown' | 'check_manually'
  error?: string | null
}

export interface ServiceAccount {
  label: string
  username: string
  expiry_date: string | null
  days_remaining: number | null
  never_expires: boolean
  status: 'ok' | 'warning' | 'critical' | 'expired' | 'never_expires' | 'unknown'
  error?: string | null
}

export interface MaintTicketRef {
  key: string
  url: string
  status: string | null
  is_closed: boolean
}

export interface MaintPrepTicketRef {
  key: string
  url: string
  assignee: string | null
  assignee_name: string | null
  status: string | null
}

export interface MaintenanceOverview {
  prep: {
    tools: Record<string, MaintPrepTicketRef | null>
  }
  itc: MaintTicketRef | null
  mggd: MaintTicketRef | null
}

export interface ToolLink {
  id: number
  name: string
  environment: string
  url: string
  category: string
  icon: string
}

export interface SonarQubeJobParam {
  name: string
  type: 'choice' | 'string' | 'text' | 'boolean'
  description: string
  default: string
  choices: string[]
}

export interface SonarQubeParamsResult {
  params: SonarQubeJobParam[]
  job_url: string
}

export interface SonarQubeReleaseNoteEntry {
  key: string
  summary: string
  type: string
  url: string
}

export interface SonarQubeReleaseNotes {
  available: boolean
  version?: string
  count?: number
  entries?: SonarQubeReleaseNoteEntry[]
  source_url?: string
  error?: string
}

export interface SonarQubeDeployResult {
  job_url: string
  build_url: string
  build_number: number | null
  status: string
}

export interface ITCTicketData {
  maintenance_date: string    // "MM-DD-YYYY"
  description: string         // full Jira wiki-markup body
  start_dt: string            // ISO datetime
  end_dt: string              // ISO datetime
  confluence_url?: string
  mggd_url?: string
}

export interface ITCTicketResult {
  key: string
  url: string
  cloned_from: string
}

export interface MGGDTicketData {
  maintenance_date: string      // "MM-DD-YYYY"
  description: string
  start_dt: string              // ISO datetime
  end_dt: string                // ISO datetime
  go_nogo_review_date: string   // "YYYY-MM-DD"
  release_number: string
  downtime?: boolean
  impl_rollback_plan_attached?: boolean
  itc_key?: string              // optional ITC ticket # for IR Plan attachment
}

export interface MGGDTicketResult {
  key: string
  url: string
}

export interface DatadogDowntimeData {
  scope: string
  start: number        // Unix timestamp
  end: number          // Unix timestamp
  message: string
  monitor_tags: string[]
}

export interface XocEocPreview {
  itc: { key: string; url: string } | null
  mggd: { key: string; url: string } | null
}

export interface MaintenanceBranchData {
  repo: string
  branch_name: string
  base_branch: string
}

export interface BranchDefaults {
  org: string
  default_repo: string
}

// ─── Axios Instance ───────────────────────────────────────────────────────────

const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: cookie-based auth — no token injection needed
apiClient.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error),
)

// Response interceptor: redirect to /login on 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const currentPath = window.location.pathname
      if (currentPath !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

// ─── Auth ─────────────────────────────────────────────────────────────────────

export async function login(username: string, password: string): Promise<User> {
  const form = new URLSearchParams({ username, password })
  const { data } = await apiClient.post<User>('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

export async function getMe(): Promise<User> {
  const { data } = await apiClient.get<User>('/auth/me')
  return data
}

// ── Maintenance mode ──────────────────────────────────────────────────────────
export interface MaintenanceMode {
  enabled: boolean
  message: string
  updated_by?: string | null
  updated_at?: string | null
}
export async function getMaintenanceMode(): Promise<MaintenanceMode> {
  const { data } = await apiClient.get<MaintenanceMode>('/dashboard/maintenance-mode')
  return data
}
export async function getMaintenanceModeAdmin(): Promise<MaintenanceMode> {
  const { data } = await apiClient.get<MaintenanceMode>('/admin/maintenance-mode')
  return data
}
export async function setMaintenanceMode(enabled: boolean, message?: string): Promise<MaintenanceMode> {
  const { data } = await apiClient.post<MaintenanceMode>('/admin/maintenance-mode', { enabled, message })
  return data
}

// ── Maintenance-date override (admin) ──────────────────────────────────────────
export interface MaintDateOverride {
  enabled: boolean
  date: string | null                   // "YYYY-MM-DD"
  start_time?: string | null            // 24-hour "HH:MM"
  end_time?: string | null
  downtime_end_time?: string | null
  go_nogo_date?: string | null
  updated_by?: string | null
  updated_at?: string | null
}

/** The date and window every maintenance flow uses, with the admin override
 *  already applied. Computing this in the browser cannot see the override. */
export interface MaintenanceWindow {
  date: string
  start_time: string
  end_time: string
  downtime_end_time: string
  go_nogo_date: string
  /** True when the review date has already passed, which Change Management
   *  rejects. Surfaced so the forms can refuse to submit. */
  go_nogo_in_past: boolean
  lead_days: number
  go_nogo_lead_days: number
  overridden: string[]
  is_overridden: boolean
}

export async function getMaintenanceWindow(): Promise<MaintenanceWindow> {
  const { data } = await apiClient.get<MaintenanceWindow>('/maintenance/window')
  return data
}
export async function getMaintDateOverride(): Promise<MaintDateOverride> {
  const { data } = await apiClient.get<MaintDateOverride>('/admin/maint-date-override')
  return data
}
export async function setMaintDateOverride(
  enabled: boolean,
  date: string | null,
  times?: { start_time?: string | null; end_time?: string | null; downtime_end_time?: string | null; go_nogo_date?: string | null },
): Promise<MaintDateOverride> {
  const { data } = await apiClient.post<MaintDateOverride>('/admin/maint-date-override', {
    enabled, date, ...(times ?? {}),
  })
  return data
}

export async function updateProfile(profileData: Partial<User>): Promise<User> {
  const { data } = await apiClient.patch<User>('/auth/me', profileData)
  return data
}

export async function uploadAvatar(file: File): Promise<{ avatar_url: string | null }> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<{ avatar_url: string | null }>(
    '/profile/avatar',
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function deleteAvatar(): Promise<{ avatar_url: null }> {
  const { data } = await apiClient.delete<{ avatar_url: null }>('/profile/avatar')
  return data
}

// ─── GitHub PAT (per-user, vault-encrypted; status-only, never returns the token) ──
export interface GithubPatStatus {
  set: boolean
  login?: string
  scopes?: string
  validated_at?: string
  locked?: boolean         // vault key not in memory (re-login needed to use/save)
  needs_reentry?: boolean  // saved PAT can't be decrypted (AD password changed)
  valid?: boolean          // present only on validate responses
  error?: string
}
export async function getGithubPat(): Promise<GithubPatStatus> {
  const { data } = await apiClient.get<GithubPatStatus>('/profile/github-pat')
  return data
}
export async function saveGithubPat(pat: string): Promise<GithubPatStatus> {
  const { data } = await apiClient.post<GithubPatStatus>('/profile/github-pat', { pat })
  return data
}
export async function validateGithubPat(): Promise<GithubPatStatus> {
  const { data } = await apiClient.post<GithubPatStatus>('/profile/github-pat/validate')
  return data
}
export async function deleteGithubPat(): Promise<GithubPatStatus> {
  const { data } = await apiClient.delete<GithubPatStatus>('/profile/github-pat')
  return data
}

// ─── Certificates & Licenses ─────────────────────────────────────────────────

export async function getCertificates(): Promise<Certificate[]> {
  const { data } = await apiClient.get<Certificate[]>('/dashboard/certificates')
  return data
}

export async function getLicenses(): Promise<License[]> {
  const { data } = await apiClient.get<License[]>('/dashboard/licenses')
  return data
}

export async function getSonarQubeLoc(): Promise<SonarQubeLoc[]> {
  const { data } = await apiClient.get<SonarQubeLoc[]>('/dashboard/sonarqube-loc')
  return data
}

export async function getMaintenanceOverview(): Promise<MaintenanceOverview> {
  const { data } = await apiClient.get<MaintenanceOverview>('/dashboard/maintenance-tickets')
  return data
}

export async function getServiceAccounts(): Promise<ServiceAccount[]> {
  const { data } = await apiClient.get<ServiceAccount[]>('/dashboard/service-accounts')
  return data
}

// ─── CBJ Monitoring: resource analysis (agents + controllers) ────────────────

export type CbjEnv = 'prod-east' | 'gc-prod-west'
export type CbjAnalysisTarget = 'agents' | 'controllers'
export type CbjStatus = 'ok' | 'warning' | 'critical' | 'unknown'

export interface CbjResourceAnalysisRow {
  env: string
  namespace: string
  container: string
  cpu_reserved_cores: number | null
  cpu_used_at_peak_cores: number | null
  cpu_wasted_cores: number | null
  cpu_pct_used: number | null
  mem_reserved_gb: number | null
  mem_used_at_peak_gb: number | null
  mem_wasted_gb: number | null
  mem_pct_used: number | null
  status: CbjStatus
  // configured ephemeral-storage from the podTemplate sweep (waste-email rows only)
  disk_request?: string | null
  disk_limit?: string | null
}

export async function getCbjResourceAnalysis(
  env: CbjEnv,
  target: CbjAnalysisTarget = 'agents',
): Promise<CbjResourceAnalysisRow[]> {
  const { data } = await apiClient.get<CbjResourceAnalysisRow[]>(
    `/monitoring/cbj-resource-analysis/${env}`,
    { params: { target } },
  )
  return data
}

// ─── CBJ waste-email automation (per-team ADO right-sizing requests) ─────────

export interface CbjWasteTeam {
  namespace: string
  controller: string
  container_count: number
  total_cpu_wasted_cores: number
  total_mem_wasted_gb: number
  worst_status: 'critical' | 'warning'
  rows: CbjResourceAnalysisRow[]
}

export interface CbjWasteTeamList {
  env: string
  target: CbjAnalysisTarget
  resolvable_ados: boolean
  teams: CbjWasteTeam[]
  error: string | null
}

export interface CbjAdo {
  sid: string
  email: string | null
  slack_handle: string | null
  slack_name: string | null
  ad_status?: string        // disabled | active | not_found | unknown
  deactivated?: boolean
}

export interface ExcludedDeactivated {
  sid: string
  email: string | null
  name: string | null
}

export interface EmailNoticeEntry {
  sent_at: string   // ISO
  ordinal: number   // 1 = first notice, 2 = second, 3+ = final
  to: string[]
  by: string
}

export interface CbjTeamAdos {
  env: string
  target: CbjAnalysisTarget
  namespace: string
  controller: string
  rows: CbjResourceAnalysisRow[]
  admins: CbjAdo[]
  admin_discovery_error: string | null
  resolvable_ados: boolean
  note: string | null
  ado_message: string
  error: string | null
  email_history?: EmailNoticeEntry[]
}

export interface CbjWasteEmailResult {
  sent: boolean
  notice_ordinal?: number
  email_history?: EmailNoticeEntry[]
  to?: string[]
  cc?: string[]
  subject?: string
  controller?: string
  namespace?: string
  excluded_deactivated?: ExcludedDeactivated[]
  error?: string
}

export async function getCbjWasteTeams(env: CbjEnv, target: CbjAnalysisTarget = 'agents'): Promise<CbjWasteTeamList> {
  const { data } = await apiClient.get<CbjWasteTeamList>(`/automation/cbj-waste/${env}/teams`, { params: { target } })
  return data
}

export async function getCbjTeamAdos(env: CbjEnv, namespace: string, target: CbjAnalysisTarget = 'agents'): Promise<CbjTeamAdos> {
  const { data } = await apiClient.get<CbjTeamAdos>(
    `/automation/cbj-waste/${env}/${encodeURIComponent(namespace)}/ados`, { params: { target } })
  return data
}

export async function emailCbjWasteAdo(
  env: CbjEnv, namespace: string, target: CbjAnalysisTarget = 'agents', extraEmails: string[] = [],
): Promise<CbjWasteEmailResult> {
  const { data } = await apiClient.post<CbjWasteEmailResult>(
    `/automation/cbj-waste/${env}/${encodeURIComponent(namespace)}/email-ado`,
    { extra_emails: extraEmails },
    { params: { target } },
  )
  return data
}

// ─── CBJ podTemplate config sweep (DMSC-479, prod-east only) ─────────────────
// Configured request/limit read from the resolved pod YAML in each job's
// last-build console log (primary — accurate, works even when the config
// comes from a trusted shared library), falling back to Replay script text
// only when the log has no provisioning block at all. Not CloudWatch — so it
// still shows jobs that haven't run recently.

export interface CbjPodTemplateJobRef {
  job: string
  build: number | null
  // Direct link to the exact build's console output — the literal evidence
  // this row's numbers were read from, clickable to cross-check in Jenkins.
  url: string | null
}

export interface CbjPodTemplateContainer {
  container: string | null
  cpu_request: string | null
  cpu_limit: string | null
  mem_request: string | null
  mem_limit: string | null
  ephemeral_request: string | null
  ephemeral_limit: string | null
  source: 'console-log' | 'replay-yaml' | 'containerTemplate-dsl'
  jobs: CbjPodTemplateJobRef[]
  job_count: number
  // Joined live from CloudWatch on every read (not baked into the sweep
  // cache) — null means this container hasn't run in CloudWatch's lookback
  // window, which is exactly the case this tool exists to catch.
  cw_cpu_used_at_peak_cores?: number | null
  cw_mem_used_at_peak_gb?: number | null
  cw_status?: 'ok' | 'warning' | 'critical' | 'unknown' | null
}

export interface CbjPodTemplateControllerResult {
  controller: string
  error: string | null
  total_jobs?: number
  jobs_no_build?: number
  jobs_no_replay?: number
  jobs_library_delegated?: string[]
  jobs_with_podtemplate?: number
  jobs_unresolved?: string[]
  containers: CbjPodTemplateContainer[]
}

export interface CbjPodTemplateSweep {
  swept_at: number | null
  controller_count: number
  results: CbjPodTemplateControllerResult[]
  cloudwatch_joined_at?: number
}

export interface CbjPodTemplateSweepStatus {
  running: boolean
  done: number
  total: number
  started_at: number | null
  last_error: string | null
}

export async function getCbjPodTemplateConfig(): Promise<CbjPodTemplateSweep> {
  const { data } = await apiClient.get<CbjPodTemplateSweep>('/monitoring/cbj-podtemplate-config')
  return data
}

export async function startCbjPodTemplateSweep(): Promise<{ started: boolean; already_running: boolean }> {
  const { data } = await apiClient.post('/monitoring/cbj-podtemplate-config/sweep')
  return data
}

export async function getCbjPodTemplateSweepStatus(): Promise<CbjPodTemplateSweepStatus> {
  const { data } = await apiClient.get<CbjPodTemplateSweepStatus>('/monitoring/cbj-podtemplate-config/sweep-status')
  return data
}

// ─── Tool Links ───────────────────────────────────────────────────────────────

export async function getLinks(): Promise<ToolLink[]> {
  const { data } = await apiClient.get<ToolLink[]>('/dashboard/links')
  return data
}

// ─── On-Call ──────────────────────────────────────────────────────────────────

export interface OncallPerson {
  username: string | null
  display_name: string
  from: string | null
  until: string | null
  is_override?: boolean
}

export interface OncallInfo {
  primary: OncallPerson
  secondary: OncallPerson
}

export async function getOncall(): Promise<OncallInfo> {
  const { data } = await apiClient.get<OncallInfo>('/dashboard/oncall')
  return data
}

// ─── SonarQube Maintenance ────────────────────────────────────────────────────

export async function getSonarQubeParams(): Promise<SonarQubeParamsResult> {
  const { data } = await apiClient.get('/maintenance/sonarqube-params')
  return data
}

export async function getSonarQubeVersions(): Promise<string[]> {
  const { data } = await apiClient.get<{ versions: string[] }>('/maintenance/sonarqube-versions')
  return data.versions
}

export async function getSonarQubeReleaseNotes(version: string): Promise<SonarQubeReleaseNotes> {
  const { data } = await apiClient.get<SonarQubeReleaseNotes>(
    '/maintenance/sonarqube-release-notes',
    { params: { version } },
  )
  return data
}

export async function triggerSonarQubeMaintenance(
  params: Record<string, string>,
): Promise<SonarQubeDeployResult> {
  const { data } = await apiClient.post<SonarQubeDeployResult>(
    '/maintenance/sonarqube-dev',
    { params },
  )
  return data
}

// ─── Jira Tickets ─────────────────────────────────────────────────────────────

export async function createITCTicket(ticketData: ITCTicketData): Promise<{ ticket: ITCTicketResult }> {
  const { data } = await apiClient.post('/maintenance/itc-ticket', ticketData)
  return data
}

export async function createMGGDTicket(ticketData: MGGDTicketData): Promise<{ ticket: MGGDTicketResult }> {
  const { data } = await apiClient.post('/maintenance/mggd-ticket', ticketData)
  return data
}

// ─── Datadog Downtime ─────────────────────────────────────────────────────────

export interface DatadogDowntime {
  id: string
  scope: string
  message: string
  start: number | null
  end: number | null
  status: 'active' | 'scheduled'
}

export async function createDatadogDowntime(
  downtimeData: DatadogDowntimeData,
): Promise<{ downtime_id: string; scope: string; message: string; start: number | null; end: number | null }> {
  const { data } = await apiClient.post('/maintenance/datadog-downtime', downtimeData)
  return data
}

export async function getActiveDatadogDowntime(): Promise<{ downtime: DatadogDowntime | null }> {
  const { data } = await apiClient.get('/maintenance/datadog-active')
  return data
}

export async function extendDatadogDowntime(downtimeId: string): Promise<{ downtime_id: string; end: number | null }> {
  const { data } = await apiClient.post(`/maintenance/datadog-downtime/${downtimeId}/extend`, {})
  return data
}

export async function cancelDatadogDowntime(downtimeId: string): Promise<{ cancelled: boolean }> {
  const { data } = await apiClient.delete(`/maintenance/datadog-downtime/${downtimeId}`)
  return data
}

// ─── XOC/EOC Notification ────────────────────────────────────────────────────

export async function getXocEocPreview(): Promise<XocEocPreview> {
  const { data } = await apiClient.get('/maintenance/xoceoc-preview')
  return data
}

export async function closeItcTicket(key: string): Promise<{ ticket: { key: string; url: string } }> {
  const { data } = await apiClient.post('/maintenance/close-itc', { key })
  return data
}

export async function closeMggdTicket(key: string): Promise<{ ticket: { key: string; url: string } }> {
  const { data } = await apiClient.post('/maintenance/close-mggd', { key })
  return data
}

export async function getMggdTasks(key: string): Promise<{ jfrog: string; jenkins: string; sonar: string }> {
  const { data } = await apiClient.get('/maintenance/mggd-tasks', { params: { key } })
  return data
}

// ─── Maintenance Branch ───────────────────────────────────────────────────────

export async function getBranchDefaults(): Promise<BranchDefaults> {
  const { data } = await apiClient.get('/maintenance/branch-defaults')
  return data
}

export async function cutMaintenanceBranch(
  branchData: MaintenanceBranchData,
): Promise<{ repo: string; branch: string; sha: string; url: string; already_existed: boolean }> {
  const { data } = await apiClient.post('/maintenance/branch', branchData)
  return data
}

// ─── JFrog Dev Maintenance ────────────────────────────────────────────────────

export interface JFrogChangelogEntry {
  version: string
  date: string
  notes: string[]
  has_important: boolean
}

export interface JFrogReleaseSection {
  heading: string
  items: string[]
  is_breaking: boolean
}

export interface JFrogReleaseNotes {
  available: boolean
  type?: 'changelog' | 'github_release'
  // JFrog CHANGELOG.md style — list of version entries in the upgrade range
  entries?: JFrogChangelogEntry[]
  // GitHub release style — categorized sections
  sections?: JFrogReleaseSection[]
  has_breaking?: boolean
  upgrade_guide_url?: string | null
  source_url?: string
  error?: string
}

export interface JFrogChartRow {
  key: string
  label: string
  file: string
  current_version: string | null
  latest_version: string | null
  has_update: boolean
  floating?: boolean  // env floats this chart (e.g. dev 107.x) — auto-tracks latest, no bump
  is_breaking: boolean
  changelog_url: string
  app_version?: string  // only for artifactory — "7.x.y" derived from chart version
  error?: string | null
  release_notes?: JFrogReleaseNotes
}

export interface AmiReleaseNotes {
  available: boolean
  date?: string
  notes?: string[]
  source_url?: string
  error?: string
}

export interface JFrogAmiInfo {
  current_ami: string | null
  current_ami_nodeclass: string | null
  has_update_nodeclass?: boolean
  latest_ami: string | null
  latest_ami_name: string | null
  has_update: boolean
  error: string | null
  eks_version: string
  release_notes?: AmiReleaseNotes
}

export interface JFrogDevParams {
  branch: string
  branch_created: boolean
  branch_url: string
  ami: JFrogAmiInfo
  helm_charts: JFrogChartRow[]
  oci_repos: JFrogChartRow[]
}

export interface JFrogDevApplyRequest {
  branch: string
  new_ami: string
  new_ami_name?: string
  helm_versions: Record<string, string>
  oci_versions: Record<string, string>
  rebase_from_main?: boolean
}

export interface JFrogDevApplyResult {
  committed_files: string[]
  branch: string
  branch_url: string
}

export async function getJFrogDevParams(): Promise<JFrogDevParams> {
  const { data } = await apiClient.get('/maintenance/jfrog-dev-params')
  return data
}

export async function applyJFrogDevChanges(payload: JFrogDevApplyRequest): Promise<JFrogDevApplyResult> {
  const { data } = await apiClient.post('/maintenance/jfrog-dev-apply', payload)
  return data
}

// ─── What's new ───────────────────────────────────────────────────────────────

export interface WhatsNewHighlight {
  title: string
  body: string
}

export interface WhatsNew {
  version: string
  date: string
  title: string
  highlights: WhatsNewHighlight[]
  acknowledged: boolean
  acknowledged_version: string
}

export interface ReleaseAnnouncement {
  version: string
  channel: string
  announced: boolean
  held?: boolean
  announced_at: string | null
  announced_by: string | null
  preview: string
}

export async function getReleaseAnnouncement(): Promise<ReleaseAnnouncement> {
  const { data } = await apiClient.get('/admin/release-announcement')
  return data
}

export async function postReleaseAnnouncement(
  force: boolean, allowDuplicate = false,
): Promise<{
  posted: boolean; version: string; reason?: string; at?: string; duplicate_blocked?: boolean
}> {
  const { data } = await apiClient.post(
    '/admin/release-announcement', { force, allow_duplicate: allowDuplicate },
  )
  return data
}

export interface DashboardHealth {
  status: string
  version?: string
}

export async function getHealth(): Promise<DashboardHealth> {
  const { data } = await apiClient.get('/dashboard/health')
  return data
}

export async function getWhatsNew(): Promise<WhatsNew> {
  const { data } = await apiClient.get('/dashboard/whats-new')
  return data
}

export async function acknowledgeWhatsNew(version: string): Promise<{ acknowledged: boolean }> {
  const { data } = await apiClient.post('/dashboard/whats-new/ack', { version })
  return data
}

// ─── EKS Control Plane Upgrade ────────────────────────────────────────────────

export interface EksVersionOption {
  version: string
  status: string | null
  default: boolean
  release_date: string | null
  end_of_standard_support: string | null
  end_of_extended_support: string | null
  patch_version: string | null
}

export interface EksClusterRow {
  key: string
  label: string
  family: string
  region: string
  is_prod: boolean
  tfvars_path: string
  nodeclass_paths: string[]
  current_version: string | null       // declared in terraform.tfvars
  live_version: string | null          // what the control plane is running
  live_error: string | null
  version_drift: boolean               // declared and running disagree
  available_versions: EksVersionOption[]
  upgrade_targets: EksVersionOption[]
  next_version: string | null
  latest_version: string | null
  error: string | null
}

export interface EksUpgradeParams {
  branch: string
  branch_exists: boolean
  branch_url: string
  clusters: EksClusterRow[]
}

export interface K8sReleaseNotes {
  available: boolean
  version?: string
  urgent?: string[]
  deprecations?: string[]
  api_changes?: string[]
  source_url?: string
  error?: string | null
}

export interface PlutoFinding {
  name: string | null
  file: string
  api_version: string | null
  kind: string | null
  deprecated_in: string | null
  removed_in: string | null
  replacement_api: string | null
  component: string | null
  deprecated: boolean
  removed: boolean
}

export interface PlutoReport {
  available: boolean
  target_version?: string
  files_scanned?: number
  scanned_paths?: string[]
  removed_count?: number
  deprecated_count?: number
  items?: PlutoFinding[]
  error?: string | null
}

export interface EksUpgradePreview {
  cluster: string
  label: string
  target_version: string
  ref_scanned: string
  release_notes: K8sReleaseNotes
  pluto: PlutoReport
  gold_image: { ami_id: string | null; ami_name: string | null; error: string | null }
}

export interface EksUpgradeApplyRequest {
  branch: string
  cluster: string
  target_version: string
  new_ami?: string
  new_ami_name?: string
  rebase_from_main?: boolean
  confirm_prod?: boolean
}

export interface EksUpgradeApplyResult {
  committed_files: string[]
  errors: string[]
  branch: string
  branch_url: string
}

export async function getEksUpgradeParams(): Promise<EksUpgradeParams> {
  const { data } = await apiClient.get('/maintenance/eks-upgrade-params')
  return data
}

export async function getEksUpgradePreview(cluster: string, targetVersion: string): Promise<EksUpgradePreview> {
  const { data } = await apiClient.get('/maintenance/eks-upgrade-preview', {
    params: { cluster, target_version: targetVersion },
  })
  return data
}

export async function applyEksUpgrade(payload: EksUpgradeApplyRequest): Promise<EksUpgradeApplyResult> {
  const { data } = await apiClient.post('/maintenance/eks-upgrade-apply', payload)
  return data
}

// ─── Shared Base Helm Charts ──────────────────────────────────────────────────

export interface BaseChartsParams {
  branch: string
  branch_created: boolean
  branch_exists: boolean
  branch_url: string
  helm_charts: JFrogChartRow[]
}

export interface BaseChartsApplyRequest {
  branch: string
  helm_versions: Record<string, string>
  rebase_from_main?: boolean
}

export interface BaseChartsApplyResult {
  committed_files: string[]
  errors: string[]
  branch: string
  branch_url: string
}

export async function getBaseChartsParams(): Promise<BaseChartsParams> {
  const { data } = await apiClient.get('/maintenance/base-charts-params')
  return data
}

export async function applyBaseChartsChanges(payload: BaseChartsApplyRequest): Promise<BaseChartsApplyResult> {
  const { data } = await apiClient.post('/maintenance/base-charts-apply', payload)
  return data
}

// ─── JFrog Prod Maintenance ───────────────────────────────────────────────────

export async function getJFrogProdParams(): Promise<JFrogDevParams> {
  const { data } = await apiClient.get('/maintenance/jfrog-prod-params')
  return data
}

export async function applyJFrogProdChanges(payload: JFrogDevApplyRequest): Promise<JFrogDevApplyResult> {
  const { data } = await apiClient.post('/maintenance/jfrog-prod-apply', payload)
  return data
}

// ─── CloudBees Dev Maintenance ────────────────────────────────────────────────

export interface CloudBeesReleaseEntry {
  version: string
  date: string
  notes: string[]
  has_important: boolean
  sections: { heading: string; items: string[]; is_breaking: boolean }[]
}

export interface CloudBeesReleaseNotes {
  available: boolean
  type?: 'cb_release'
  entries?: CloudBeesReleaseEntry[]
  has_breaking?: boolean
  source_url?: string
  error?: string
}

export interface CloudBeesChartInfo {
  file: string
  current_version: string | null
  current_tag: string | null
  latest_version: string | null
  latest_tag: string | null
  has_update: boolean
  changelog_url: string
  release_notes?: CloudBeesReleaseNotes
}

export interface CloudBeesEnvInfo {
  label: string
  current_controller_ami: string | null
  current_controller_ami_nodeclass: string | null
  latest_controller_ami: string | null
  latest_controller_ami_name: string | null
  controller_target_ami: string | null
  controller_has_update: boolean
  controller_drift: boolean
  current_agent_ami: string | null
  latest_agent_ami: string | null
  latest_agent_ami_name: string | null
  agent_has_update: boolean
  controller_error: string | null
  agent_error: string | null
}

export interface CloudBeesDevParams {
  branch: string
  branch_created: boolean
  branch_url: string
  chart: CloudBeesChartInfo
  oci_repos: JFrogChartRow[]
  envs: {
    'dev-east': CloudBeesEnvInfo
    'gc-dev-west': CloudBeesEnvInfo
  }
}

export interface CloudBeesDevApplyRequest {
  branch: string
  new_chart_version?: string
  new_chart_tag?: string
  dev_east_controller_ami?: string
  dev_east_controller_ami_name?: string
  dev_east_agent_ami?: string
  dev_east_agent_ami_name?: string
  gc_dev_west_controller_ami?: string
  gc_dev_west_controller_ami_name?: string
  gc_dev_west_agent_ami?: string
  gc_dev_west_agent_ami_name?: string
  karpenter_version?: string
  karpenter_crd_version?: string
  rebase_from_main?: boolean
}

export async function getCloudBeesDevParams(): Promise<CloudBeesDevParams> {
  const { data } = await apiClient.get('/maintenance/cloudbees-dev-params')
  return data
}

export async function applyCloudBeesDevChanges(
  payload: CloudBeesDevApplyRequest,
): Promise<{ committed_files: string[]; branch: string; branch_url: string }> {
  const { data } = await apiClient.post('/maintenance/cloudbees-dev-apply', payload)
  return data
}

// ─── CloudBees Prod Maintenance ───────────────────────────────────────────────

export interface CloudBeesProdParams {
  branch: string
  branch_created: boolean
  branch_url: string
  chart: CloudBeesChartInfo
  oci_repos: JFrogChartRow[]
  envs: {
    'prod-east': CloudBeesEnvInfo
    'gc-prod-west': CloudBeesEnvInfo
  }
}

export interface CloudBeesProdApplyRequest {
  branch: string
  new_chart_version?: string
  new_chart_tag?: string
  prod_east_controller_ami?: string
  prod_east_controller_ami_name?: string
  prod_east_agent_ami?: string
  prod_east_agent_ami_name?: string
  gc_prod_west_controller_ami?: string
  gc_prod_west_controller_ami_name?: string
  gc_prod_west_agent_ami?: string
  gc_prod_west_agent_ami_name?: string
  karpenter_version?: string
  karpenter_crd_version?: string
  rebase_from_main?: boolean
}

export async function getCloudBeesProdParams(): Promise<CloudBeesProdParams> {
  const { data } = await apiClient.get('/maintenance/cloudbees-prod-params')
  return data
}

export async function applyCloudBeesProdChanges(
  payload: CloudBeesProdApplyRequest,
): Promise<{ committed_files: string[]; branch: string; branch_url: string }> {
  const { data } = await apiClient.post('/maintenance/cloudbees-prod-apply', payload)
  return data
}

// ─── Admin: RBAC ─────────────────────────────────────────────────────────────

export async function getAdminUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<AdminUser[]>('/admin/users')
  return data
}

export async function updateUserRole(
  username: string,
  role: 'admin' | 'user',
): Promise<{ username: string; role: string; notified?: boolean; notify_error?: string | null }> {
  const { data } = await apiClient.put(`/admin/users/${username}/role`, { role })
  return data
}

// ─── Admin: Audit Log ─────────────────────────────────────────────────────────

export async function getAuditLog(params: {
  date_from?: string
  date_to?: string
  username?: string
  event_type?: string
  page?: number
  page_size?: number
}): Promise<AuditLogResult> {
  const { data } = await apiClient.get<AuditLogResult>('/admin/audit', { params })
  return data
}

export default apiClient

// ─── Maintenance Prep ─────────────────────────────────────────────────────────

export interface MaintPrepMember {
  index: number
  username: string
  name: string
}

export interface MaintPrepRotation {
  jfrog: MaintPrepMember
  cloudbees: MaintPrepMember
  sonarqube: MaintPrepMember
  last_jfrog_assignee: string | null
}

export interface DmscSprint {
  id: number | null   // null for projected sprints not yet created
  name: string
  state: string       // 'active' | 'future' | 'projected'
  startDate?: string
  endDate?: string
}

export interface MaintPrepParams {
  maint_date: string
  maint_date_str: string
  rotation: MaintPrepRotation
  sprints: DmscSprint[]
  recommended_sprint_id: number | null   // sprint overlapping the maintenance window, if any
  projected_sprint: DmscSprint | null     // suggested new sprint when none overlaps
}

export interface MaintPrepTicket {
  key: string
  url: string
  service: string
  assignee: string
  sp: number
}

export async function getMaintPrepParams(): Promise<MaintPrepParams> {
  const { data } = await apiClient.get('/maintenance/maint-prep-params')
  return data
}

export interface MaintPrepStatus {
  maint_date: string
  maint_date_str: string
  all_created: boolean
  tools: Record<string, {
    key: string; url: string
    assignee: string | null; assignee_name: string | null; status: string | null
    /** The window the ticket's own body states, which an override can make
     *  differ from maint_date_str. */
    window_date_str?: string | null
    exact?: boolean
  } | null>
  /** Tools whose prep ticket was matched to a nearby window rather than this
   *  exact date, so the UI can show the discrepancy instead of hiding it. */
  date_mismatch?: string[]
}
export async function getMaintPrepStatus(): Promise<MaintPrepStatus> {
  const { data } = await apiClient.get('/maintenance/prep-status')
  return data
}

export interface TicketReadiness {
  maint_date: string
  maint_date_str: string
  days_until: number
  due: boolean
  prep_all_created: boolean
}
export async function getTicketReadiness(): Promise<TicketReadiness> {
  const { data } = await apiClient.get('/maintenance/ticket-readiness')
  return data
}

export interface NewsletterPreview {
  page_id: string; title: string; url: string; change_number: number; dry_run: boolean
}
// Dry-run: resolves the maintenance-week newsletter page (no edit) so the ITC
// modal can pre-fill the "Link to Comms Request" field.
export async function previewNewsletter(payload: {
  itc_key?: string; maint_date_mdy: string; start_dt: string; end_dt: string
}): Promise<NewsletterPreview> {
  const { data } = await apiClient.post('/maintenance/newsletter-append', { ...payload, dry_run: true })
  return data
}

export async function createMaintPrepTickets(payload: {
  sprint_id: number | null
  new_sprint_name?: string
  new_sprint_start?: string
  new_sprint_end?: string
  maint_date_str: string
  jfrog_assignee: string
  cloudbees_assignee: string
  sonarqube_assignee: string
}): Promise<{ tickets: MaintPrepTicket[] }> {
  const { data } = await apiClient.post('/maintenance/maint-prep-create', payload)
  return data
}

// ─── On-Call Tickets ──────────────────────────────────────────────────────────

export interface OnCallTeamMember {
  username: string
  name: string
}

export interface OnCallSuggestion {
  week: number
  start: string
  until: string | null
  victorops_user: string | null
  jira_user: string
  mapped: boolean
}

export interface OnCallParams {
  sprints: DmscSprint[]
  team: OnCallTeamMember[]
  suggestions: OnCallSuggestion[]
}

export interface OnCallTicket {
  key: string
  url: string
  week: number
  assignee: string
}

export async function getOnCallParams(): Promise<OnCallParams> {
  const { data } = await apiClient.get('/maintenance/on-call-params')
  return data
}

export async function createOnCallTickets(payload: {
  sprint_id?: number | null
  new_sprint_name?: string
  new_sprint_start?: string
  new_sprint_end?: string
  weeks: { week: number; assignee: string }[]
}): Promise<{ tickets: OnCallTicket[]; sprint_id: number; sprint_name: string | null }> {
  const { data } = await apiClient.post('/maintenance/on-call-create', payload)
  return data
}

// ─── Retro Pages ──────────────────────────────────────────────────────────────

export interface RetroPreviewSection {
  title?: string
  already_exists?: boolean
  existing_url?: string | null
  date?: string             // maintenance section
  end_date?: string         // sprint section
  sprint_number?: number    // sprint section
  error?: string
}

export interface RetroPreview {
  maintenance: RetroPreviewSection
  sprint: RetroPreviewSection
}

export interface RetroCreateResult {
  created: boolean
  already_existed: boolean
  title: string
  url: string
  source_date?: string
  end_date?: string
  sprint_number?: number
}

export async function getRetroPreview(): Promise<RetroPreview> {
  const { data } = await apiClient.get('/maintenance/retro-preview')
  return data
}

export async function createMaintenanceRetroPage(): Promise<RetroCreateResult> {
  const { data } = await apiClient.post('/maintenance/retro-maintenance')
  return data
}

export async function createSprintRetroPage(): Promise<RetroCreateResult> {
  const { data } = await apiClient.post('/maintenance/retro-sprint')
  return data
}

// ─── OE (Open Enrollment) DevOps Readiness ─────────────────────────────────────

export type OESectionStatus = 'auto' | 'carry' | 'manual'

export interface OESection {
  key: string
  label: string
  status: OESectionStatus
  text: string
  already_filled: boolean
}

export interface OEPageRef {
  id: string
  title: string
  url: string
}

export interface OEPagePlan {
  kind: 'cbj' | 'jfrog_sonar'
  found: boolean
  page: OEPageRef | null
  sections: OESection[]
}

export interface OEPreview {
  year: number
  pages: OEPagePlan[]
}

export interface OESreTicket {
  tool: string
  key: string | null
  url: string | null
  existing?: boolean
  error?: string
}

export interface OECcoeRef {
  key: string
  url: string
  commented: boolean
}

export interface OEApplyResultRow {
  kind: string
  page: OEPageRef
  written: string[]
  ccoe: OECcoeRef | null
}

export interface OEApplyResult {
  year: number
  results: OEApplyResultRow[]
  sre: OESreTicket[]
}

export interface OECloseCcoeResult {
  ok: boolean
  status?: string
  key?: string
  error?: string
}

export async function getOEReadinessPreview(year: number): Promise<OEPreview> {
  const { data } = await apiClient.get('/maintenance/oe-readiness/preview', { params: { year } })
  return data
}

export async function applyOEReadiness(
  year: number,
  selections: Record<string, string[]>,
  overwrite = false,
): Promise<OEApplyResult> {
  const { data } = await apiClient.post('/maintenance/oe-readiness/apply', { year, selections, overwrite })
  return data
}

export async function closeOECcoe(year: number, kind: string): Promise<OECloseCcoeResult> {
  const { data } = await apiClient.post('/maintenance/oe-readiness/close-ccoe', { year, kind })
  return data
}

// ─── Automation ───────────────────────────────────────────────────────────────

export interface JFrogLdapTestResult {
  ok: boolean
  message: string
  status_code: number | null
}

export interface JFrogLdapSaveResult {
  status: string
  env: string
  account: string
  test: JFrogLdapTestResult
}

export async function getJFrogLdapAccount(env: 'dev' | 'prod'): Promise<{ env: string; account: string }> {
  const { data } = await apiClient.get(`/automation/jfrog-password/${env}/account`)
  return data
}

export async function testJFrogLdapPassword(
  env: 'dev' | 'prod', password: string,
): Promise<JFrogLdapTestResult> {
  const { data } = await apiClient.post(`/automation/jfrog-password/${env}/test`, { password })
  return data
}

export async function updateJFrogLdapPassword(
  env: 'dev' | 'prod', password: string,
): Promise<JFrogLdapSaveResult> {
  const { data } = await apiClient.post(`/automation/jfrog-password/${env}`, { password })
  return data
}

// ─── Account unlock (Artifactory + Active Directory) ──────────────────────────
export interface JFrogUnlockResult { status: string; env: string; username: string }
export interface AdUnlockResult {
  status: 'unlocked' | 'not_found'
  account: string
  dn?: string
  was_locked?: boolean
  message: string
}

export interface OnePasswordResult { action?: 'updated' | 'created'; title?: string; vault?: string; error?: string }
export interface AdResetResult {
  status: 'reset' | 'not_found'
  account: string
  dn?: string
  message: string
  generated_password?: string
  onepassword?: OnePasswordResult | null
}
export interface AdResetOptions {
  password?: string
  generate?: boolean
  save_to_1password?: boolean
}

export async function unlockJFrogUser(env: 'dev' | 'prod', username: string): Promise<JFrogUnlockResult> {
  const { data } = await apiClient.post(`/automation/jfrog-unlock/${env}`, { username })
  return data
}

// ─── SonarQube user-access lookup ─────────────────────────────────────────────
export interface SonarQubeAppAccess { application: string; role: 'admin' | 'user' | 'member' }
export interface SonarQubeCandidate {
  login: string
  name?: string
  email?: string
  eua?: string
  active?: boolean
}
export interface SonarQubeUserAccess {
  configured: boolean
  found?: boolean
  ambiguous?: boolean
  env: 'dev' | 'prod'
  login: string
  name?: string
  email?: string
  eua?: string
  active?: boolean
  local?: boolean
  external_provider?: string
  external_identity?: string
  last_connection?: string | null
  tokens_count?: number
  in_baseline_group?: boolean
  groups?: string[]
  applications?: SonarQubeAppAccess[]
  application_count?: number
  admin_count?: number
  candidates?: SonarQubeCandidate[]
  email_shared_with?: SonarQubeCandidate[]
  email_collision?: { ad_email: string; ad_name?: string; conflicting: SonarQubeCandidate[] } | null
  similar?: string[]
  message: string
}

export async function getSonarQubeUserAccess(
  env: 'dev' | 'prod',
  username: string,
): Promise<SonarQubeUserAccess> {
  const { data } = await apiClient.post(`/automation/sonarqube-access/${env}`, { username })
  return data
}

// ── CloudBees "Check User Access" (cached sweep) ───────────────────────────────
export interface CloudBeesControllerAccess {
  controller: string
  groups: string[]
  roles: string[]
}
export interface CloudBeesUserAccess {
  env: string
  eua: string
  found: boolean
  no_scan?: boolean
  swept_at: number | null
  ad_status?: string
  global_admin?: boolean
  cjoc?: CloudBeesControllerAccess | null
  controller_count?: number
  controllers?: CloudBeesControllerAccess[]
  roles_summary?: string[]
  sweep?: ControllerSweepState
  message: string
}
export async function getCloudBeesUserAccess(
  env: ControllerUserEnv, username: string,
): Promise<CloudBeesUserAccess> {
  const { data } = await apiClient.post(`/automation/cloudbees-access/${env}`, { username })
  return data
}
export async function startCloudBeesAccessSweep(env: ControllerUserEnv): Promise<{ started: boolean; already_running?: boolean }> {
  const { data } = await apiClient.post(`/automation/cloudbees-access/${env}/sweep`)
  return data
}
export async function getCloudBeesAccessSweepStatus(env: ControllerUserEnv): Promise<ControllerSweepState> {
  const { data } = await apiClient.get(`/automation/cloudbees-access/${env}/sweep-status`)
  return data
}

// ── Artifactory "Check User Access" (live) ─────────────────────────────────────
export interface ArtifactoryProjectAccess {
  project: string
  name: string
  roles: string[]
}
export interface ArtifactoryPermissionTarget {
  name: string
  via: string           // "user" | "group:<name>"
  permissions: string[]
  repositories: string[]
}
export interface ArtifactoryUserAccess {
  configured: boolean
  found?: boolean
  env: string
  eua: string
  username?: string
  email?: string
  realm?: string
  admin?: boolean
  status?: string
  last_logged_in?: string | null
  groups?: string[]
  projects?: ArtifactoryProjectAccess[]
  project_count?: number
  permission_targets?: ArtifactoryPermissionTarget[]
  permission_target_count?: number
  message: string
}
export async function getArtifactoryUserAccess(
  env: ArtifactoryUserEnv, username: string,
): Promise<ArtifactoryUserAccess> {
  const { data } = await apiClient.post(`/automation/artifactory-access/${env}`, { username })
  return data
}

export interface AdAccountStatus {
  status: 'found' | 'not_found'
  account: string
  dn?: string
  is_locked?: boolean
  bad_pwd_count?: number | null
  password_expired?: boolean
  password_status?: 'ok' | 'warning' | 'critical' | 'expired' | 'never_expires' | 'unknown'
  password_expiry_date?: string | null
  password_days_remaining?: number | null
  password_never_expires?: boolean
  message: string
}

export async function getAdAccountStatus(account: string): Promise<AdAccountStatus> {
  const { data } = await apiClient.post('/automation/ad-account-status', { account })
  return data
}

export async function unlockAdAccount(account: string): Promise<AdUnlockResult> {
  const { data } = await apiClient.post('/automation/ad-unlock', { account })
  return data
}

export async function resetAdPassword(account: string, opts: AdResetOptions): Promise<AdResetResult> {
  const { data } = await apiClient.post('/automation/ad-reset-password', { account, ...opts })
  return data
}

// ─── Full service-account rotation (reset AD + save 1Password + verify + update tool) ──
export interface RotateResult {
  status: 'ok' | 'partial'
  env: string
  account: string
  ad_reset?: AdResetResult
  onepassword?: OnePasswordResult | null
  verified?: boolean
  test?: { ok: boolean; message: string; status_code?: number | null }
  tool_error?: string | null
  generated_password?: string
}
export interface RotateOptions { password?: string; generate?: boolean; save_to_1password?: boolean }

export async function rotateJFrogAccount(env: 'dev' | 'prod', opts: RotateOptions): Promise<RotateResult> {
  const { data } = await apiClient.post(`/automation/jfrog-rotate/${env}`, opts)
  return data
}

export async function rotateCloudBeesAccount(env: string, opts: RotateOptions): Promise<RotateResult> {
  const { data } = await apiClient.post(`/automation/cloudbees-rotate/${env}`, opts)
  return data
}

// Datadog Synthetics: sel 'a' = dso-synthetics-a, 'b' = dso-synthetics-b. Rotation
// resets AD + saves 1Password + writes the new password into the matching Datadog
// secure global variable (DSO_SYNTHETICS_A/B_PASSWORD). LDAP verify is soft.
export async function rotateDatadogSyntheticsAccount(sel: 'a' | 'b', opts: RotateOptions): Promise<RotateResult> {
  const { data } = await apiClient.post(`/automation/datadog-synthetics-rotate/${sel}`, opts)
  return data
}

// ─── Wildcard cert export ─────────────────────────────────────────────────────
export interface CertExportTarget { tool: string; env: string; configured: boolean; reason?: string }
export interface CertExportResult {
  status?: 'updated' | 'unchanged'
  message?: string
  cert_arn: string
  op_items: string[]
  enc_paths: string[]
  pr_url: string | null
}
export async function getCertExportTargets(): Promise<CertExportTarget[]> {
  const { data } = await apiClient.get<{ targets: CertExportTarget[] }>('/automation/cert-export/targets')
  return data.targets
}
export async function runCertExport(tool: string, env: string): Promise<CertExportResult> {
  const { data } = await apiClient.post<CertExportResult>(`/automation/cert-export/${tool}/${env}`)
  return data
}

// ─── JFrog entitlement credential (vendor registry/chart auth in SOPS) ───────
export interface JFrogRegistryTokenTarget {
  env: string
  label: string
  enc_path: string
  secret_count: number
  ready: boolean
  reason?: string
}
export interface JFrogRegistryTokenVerification {
  username: string
  registry: string
  chart_host: string
  verified: boolean
}
export interface JFrogApplyCommand {
  step: string
  command: string
}
export interface JFrogRegistryTokenResult {
  env: string
  branch: string
  branch_synced: boolean
  sync_note: string
  path: string
  secrets: string[]
  verified: JFrogRegistryTokenVerification
  // Only on the automatic path.
  requested_automatically?: boolean
  expires_in?: number | null
  refresh_token_rotated?: boolean
  refresh_token_stored?: boolean
  refresh_note?: string
  apply_commands?: JFrogApplyCommand[]
}
export interface JFrogTokenExpiry {
  expires_at: string | null
  days_remaining: number | null
  status: 'ok' | 'warning' | 'critical' | 'expired' | 'unknown'
  source: string
  can_refresh: boolean
}
export async function getJFrogTokenExpiry(): Promise<JFrogTokenExpiry> {
  const { data } = await apiClient.get<JFrogTokenExpiry>('/automation/jfrog-registry-token/expiry')
  return data
}
export async function refreshJFrogRegistryToken(env: string): Promise<JFrogRegistryTokenResult> {
  const { data } = await apiClient.post<JFrogRegistryTokenResult>(
    `/automation/jfrog-registry-token/${env}/refresh`,
  )
  return data
}
export async function getJFrogRegistryTokenTargets(): Promise<JFrogRegistryTokenTarget[]> {
  const { data } = await apiClient.get<{ targets: JFrogRegistryTokenTarget[] }>('/automation/jfrog-registry-token/targets')
  return data.targets
}
export async function rotateJFrogRegistryToken(
  env: string,
  username: string,
  password: string,
): Promise<JFrogRegistryTokenResult> {
  const { data } = await apiClient.post<JFrogRegistryTokenResult>(
    `/automation/jfrog-registry-token/${env}`,
    { username, password },
  )
  return data
}

// ─── Artifactory repo cache refresh / reindex (prod only) ─────────────────────
export interface RefreshRepo {
  key: string
  type: 'LOCAL' | 'REMOTE' | 'VIRTUAL'
  package_type: string
}
export interface RepoRefreshResult {
  repo: string
  type: string
  package_type?: string
  ok: boolean
  action: string
  detail: string
  deleted?: number
}

export async function listRefreshRepos(): Promise<RefreshRepo[]> {
  const { data } = await apiClient.get<{ repos: RefreshRepo[] }>('/automation/repo-refresh/repos')
  return data.repos
}

export async function refreshRepos(
  repos: string[], pkg?: string,
): Promise<RepoRefreshResult[]> {
  const { data } = await apiClient.post<{ results: RepoRefreshResult[] }>(
    '/automation/repo-refresh', { repos, package: pkg || null },
  )
  return data.results
}

// ─── CloudBees CJOC LDAP password ────────────────────────────────────────────

export interface CloudBeesEnv { key: string; label: string }
export interface CloudBeesAccountInfo {
  account: string | null
  account_full?: string | null
  ldap_url: string | null
  error: string | null
}
export interface CloudBeesTestResult {
  ok: boolean
  message: string
  status_code: number | null
}
export interface CloudBeesSaveResult {
  status: string
  env: string
  output: string
  test: CloudBeesTestResult
}

export async function getCloudBeesEnvs(): Promise<CloudBeesEnv[]> {
  const { data } = await apiClient.get('/automation/cloudbees-password/envs')
  return data.envs
}

export async function getCloudBeesAccount(env: string): Promise<CloudBeesAccountInfo> {
  const { data } = await apiClient.get(`/automation/cloudbees-password/${env}/account`)
  return data
}

export async function testCloudBeesLdapPassword(
  env: string, password: string,
): Promise<CloudBeesTestResult> {
  const { data } = await apiClient.post(`/automation/cloudbees-password/${env}/test`, { password })
  return data
}

export async function updateCloudBeesLdapPassword(
  env: string, password: string,
): Promise<CloudBeesSaveResult> {
  const { data } = await apiClient.post(`/automation/cloudbees-password/${env}`, { password })
  return data
}

// ─── Copy Controllers ────────────────────────────────────────────────────────

export interface CopyControllerPreview {
  controller_name: string
  aws_roles: string[]
  aws_roles_error: string | null
  aws_policy_arn?: string | null
  network_cidrs: string[]
  network_cidrs_error: string | null
  network_namespace?: string | null
  network_np_count?: number
  admins: string[]
  admins_error: string | null
  already_exists_on_dev?: boolean
  dev_existence_error?: string | null
}

export interface CopyControllerRunRequest {
  controller_name: string
  aws_roles: string[]
  network_ranges: string[]
  admins: string[]
  cldspt_ticket?: string
  fisma_id?: string
  migrate_all_jobs: boolean
  job_list: string[]
  copy_secrets: boolean
  copy_plugins: boolean
}

export interface CopyControllerRunResult {
  controller_name: string
  already_existed_on_dev?: boolean
  job_url: string
  queue_url: string | null
  build_url: string | null
  build_number: number | null
  status: string
  parameters: Record<string, string>
  secrets_encoded?: string | null
  secrets_error?: string | null
  jobs_payload?: string | null
  jobs_count?: number
  jobs_folders?: number
  jobs_jobs?: number
  jobs_error?: string | null
  jobs_export_errors?: string[]
  plugins_delta?: string[]
  plugins_catalog_gaps?: string[]
  plugins_files_changed?: string[]
  plugins_pr_url?: string | null
  plugins_pr_number?: number | null
  plugins_summary?: string | null
  plugins_no_changes?: boolean
  plugins_error?: string | null
  pending_followups: { jobs: boolean; secrets: boolean; plugins: boolean }
}

export interface ApplySecretsResult {
  output: string
  error: string | null
}

export interface ApplyJobsResult {
  output: string
  items_in_payload: number
  error: string | null
}

export async function applyCopyControllerSecrets(
  controllerName: string, encoded: string,
): Promise<ApplySecretsResult> {
  const { data } = await apiClient.post('/automation/copy-controller/apply-secrets', {
    controller_name: controllerName, encoded,
  })
  return data
}

export async function applyCopyControllerJobs(
  controllerName: string, payload: string,
): Promise<ApplyJobsResult> {
  const { data } = await apiClient.post('/automation/copy-controller/apply-jobs', {
    controller_name: controllerName, payload,
  })
  return data
}

export interface CopyControllerStatus {
  controller_name: string
  controller_exists_on_dev: boolean
  existence_error: string | null
  build_url: string | null
  build_number: number | null
  build_building: boolean | null
  build_result: string | null   // "SUCCESS" | "FAILURE" | "ABORTED" | "UNSTABLE" | null (running)
  build_error: string | null
}

export async function getCopyControllerStatus(
  controllerName: string, buildUrl?: string | null,
): Promise<CopyControllerStatus> {
  const params: any = {}
  if (buildUrl) params.build_url = buildUrl
  const { data } = await apiClient.get(
    `/automation/copy-controller/${encodeURIComponent(controllerName)}/status`,
    { params },
  )
  return data
}

export async function previewCopyController(controllerName: string): Promise<CopyControllerPreview> {
  const { data } = await apiClient.post('/automation/copy-controller/preview', { controller_name: controllerName })
  return data
}

export async function runCopyController(req: CopyControllerRunRequest): Promise<CopyControllerRunResult> {
  const { data } = await apiClient.post('/automation/copy-controller/run', req)
  return data
}

// ─── Controller PVC cleanup (prod-east) ──────────────────────────────────────

export interface PvcController {
  namespace: string
  controller: string
  status: 'crit' | 'warn'
  monitor_status?: string
  last_triggered_ts?: number | null
}

export interface PvcControllerList {
  over: PvcController[]
  approaching: PvcController[]
  error: string | null
  thresholds?: { warn: number; crit: number }
  cluster?: string
  monitor_id?: number
}

export interface PvcAdmin {
  sid: string
  email: string | null
  slack_handle: string | null
  slack_name: string | null
  matched_by?: 'email' | 'eua' | null
  ad_status?: string        // disabled | active | not_found | unknown
  deactivated?: boolean
}

export interface PvcCategory {
  category: string
  bytes: number
  cleanable: boolean
}

export interface PvcUsage {
  error: string | null
  controller: string
  jenkins_home: string
  total_bytes: number
  free_bytes: number
  pct: number
  disk_usage_source: 'plugin' | 'missing' | 'error' | null
  disk_usage_error?: string | null
  directories: { name: string; bytes: number }[]
  top_jobs: { name: string; bytes: number }[]
  suggested_categories: PvcCategory[]
  admins: PvcAdmin[]
  admin_discovery_error: string | null
  ado_message: string
  email_history?: EmailNoticeEntry[]
}

export interface PvcPruneStart {
  state: 'started' | 'already_running'
  dryRun?: boolean
  controller?: string
  categories?: string[]
  progress?: PvcPruneProgress
  cldspt?: { key: string; url: string; assignee?: string }
  cldspt_error?: string
  cldspt_assign_error?: string
  error: string | null
}

export interface PvcEmailResult {
  sent: boolean
  notice_ordinal?: number
  email_history?: EmailNoticeEntry[]
  to?: string[]
  cc?: string[]
  subject?: string
  excluded_deactivated?: ExcludedDeactivated[]
  error?: string
}

// ─── Controller user audit + cleanup ───────────────────────────────────────────

export type ControllerUserEnv = 'prod-east' | 'gc-prod-west'

export interface ControllerUser {
  id: string
  full_name: string
  last_granted: number | null
  ad_status: string          // disabled | active | not_found | unknown | system
  deactivated: boolean
  is_system: boolean
}

export interface ControllerUserAudit {
  env: string
  controller: string
  users: ControllerUser[]
  counts: { total: number; deactivated: number; unknown: number }
  error: string | null
}

export interface ControllerUserDeleteResult {
  deleted: string[]
  failed: { id: string; error: string }[]
  refused?: string[]
  error: string | null
}

export interface ControllerSweepState {
  running: boolean
  done: number
  total: number
  started_at: number | null
  last_error: string | null
}

export interface ControllerSweepRow {
  controller: string
  total: number
  deactivated: number
  unknown: number
  error?: string | null
}

export interface ControllerUsersSummary {
  env: string
  swept_at: number | null
  controller_count?: number
  controllers: ControllerSweepRow[]
  sweep: ControllerSweepState
  error: string | null
}

// ── CBJ pod-quota (fiftypods) audit + remediation ─────────────────────────────
export interface PodQuotaController {
  controller: string
  namespace: string
  hard: number
  used: number
  at_limit: boolean
  near_limit: boolean
  pct: number
}
export interface PodQuotaAudit {
  env: string
  hard_cap: number
  at_limit_count: number
  controllers: PodQuotaController[]
  error: string | null
}
export interface RunningBuild {
  job: string
  number: number
  url: string
  durationMs: number
}
export interface RunningBuilds {
  env: string
  controller: string
  count: number
  builds: RunningBuild[]
  error: string | null
}
export interface QuotaIncreaseResult {
  env: string
  controller: string
  previous_hard: number
  hard: number
  used: number
  error: string | null
}
export async function getPodQuotaAudit(env: ControllerUserEnv): Promise<PodQuotaAudit> {
  const { data } = await apiClient.get(`/automation/pod-quota/${env}/audit`)
  return data
}
export async function getRunningBuilds(env: ControllerUserEnv, controller: string): Promise<RunningBuilds> {
  const { data } = await apiClient.get(`/automation/pod-quota/${env}/${encodeURIComponent(controller)}/running-builds`)
  return data
}
export async function increasePodQuota(env: ControllerUserEnv, controller: string, newLimit: number): Promise<QuotaIncreaseResult> {
  const { data } = await apiClient.post(`/automation/pod-quota/${env}/${encodeURIComponent(controller)}/increase`, { new_limit: newLimit, confirm: true })
  return data
}
export async function abortRunningBuild(env: ControllerUserEnv, controller: string, job: string, number: number): Promise<{ aborted: boolean; result: string }> {
  const { data } = await apiClient.post(`/automation/pod-quota/${env}/${encodeURIComponent(controller)}/abort-build`, { job, number, confirm: true })
  return data
}
export async function abortAllRunningBuilds(env: ControllerUserEnv, controller: string, olderThanDays = 0): Promise<{ aborted: number; failed: number; older_than_days: number }> {
  const { data } = await apiClient.post(`/automation/pod-quota/${env}/${encodeURIComponent(controller)}/abort-all-builds`, { confirm: true, older_than_days: olderThanDays })
  return data
}

export async function getControllerUsersSummary(env: ControllerUserEnv): Promise<ControllerUsersSummary> {
  const { data } = await apiClient.get(`/automation/controller-users/${env}/summary`)
  return data
}

export async function startControllerUsersSweep(env: ControllerUserEnv): Promise<{ started: boolean; already_running?: boolean }> {
  const { data } = await apiClient.post(`/automation/controller-users/${env}/sweep`)
  return data
}

export async function getControllerUsersSweepStatus(env: ControllerUserEnv): Promise<ControllerSweepState> {
  const { data } = await apiClient.get(`/automation/controller-users/${env}/sweep-status`)
  return data
}

// ─── Artifactory user audit + cleanup (by project) ──────────────────────────────

export type ArtifactoryUserEnv = 'prod' | 'dev'

export interface ArtifactoryProjectRow {
  project: string
  name: string
  total: number
  deactivated: number
  unknown: number
  error?: string | null
}

export interface ArtifactoryUsersSummary {
  env: string
  swept_at: number | null
  project_count?: number
  projects: ArtifactoryProjectRow[]
  sweep: ControllerSweepState
  error: string | null
}

export interface ArtifactoryUser {
  id: string
  full_name: string
  roles: string[]
  ad_status: string          // disabled | active | not_found | unknown
  deactivated: boolean
}

export interface ArtifactoryProjectAudit {
  env: string
  project: string
  users: ArtifactoryUser[]
  counts: { total: number; deactivated: number; unknown: number }
  error: string | null
}

export async function getArtifactoryUsersSummary(env: ArtifactoryUserEnv): Promise<ArtifactoryUsersSummary> {
  const { data } = await apiClient.get(`/automation/artifactory-users/${env}/summary`)
  return data
}

export async function startArtifactoryUsersSweep(env: ArtifactoryUserEnv): Promise<{ started: boolean; already_running?: boolean }> {
  const { data } = await apiClient.post(`/automation/artifactory-users/${env}/sweep`)
  return data
}

export async function getArtifactoryUsersSweepStatus(env: ArtifactoryUserEnv): Promise<ControllerSweepState> {
  const { data } = await apiClient.get(`/automation/artifactory-users/${env}/sweep-status`)
  return data
}

export async function auditArtifactoryProject(env: ArtifactoryUserEnv, project: string): Promise<ArtifactoryProjectAudit> {
  const { data } = await apiClient.get(`/automation/artifactory-users/${env}/${encodeURIComponent(project)}/audit`)
  return data
}

export async function deleteArtifactoryUsers(env: ArtifactoryUserEnv, ids: string[]): Promise<ControllerUserDeleteResult> {
  const { data } = await apiClient.post(`/automation/artifactory-users/${env}/delete`, { ids, confirm: true })
  return data
}

export async function auditControllerUsers(env: ControllerUserEnv, controller: string): Promise<ControllerUserAudit> {
  const { data } = await apiClient.get(
    `/automation/controller-users/${env}/${encodeURIComponent(controller)}/audit`)
  return data
}

export async function deleteControllerUsers(
  env: ControllerUserEnv, controller: string, ids: string[],
): Promise<ControllerUserDeleteResult> {
  const { data } = await apiClient.post(
    `/automation/controller-users/${env}/${encodeURIComponent(controller)}/delete`,
    { ids, confirm: true })
  return data
}

export interface PvcPruneProgress {
  jobsProcessed: number
  totalJobs: number
  buildsDeleted: number
  filesCleared: number
}

export interface PvcPruneStatus {
  state: 'idle' | 'running' | 'done' | 'error' | string
  dryRun?: boolean
  controller?: string
  categories?: string[]
  keep?: number
  progress?: PvcPruneProgress
  report?: Record<string, { items?: number; keep?: number }>
  freeBefore?: number
  freeAfter?: number | null
  reclaimedBytes?: number | null
  total_items?: number
  total_bytes?: number
  stale?: boolean
  error: string | null
}

export async function getPvcControllers(): Promise<PvcControllerList> {
  const { data } = await apiClient.get('/automation/pvc-cleanup/controllers')
  return data
}

export async function getPvcUsage(controller: string): Promise<PvcUsage> {
  const { data } = await apiClient.get(`/automation/pvc-cleanup/${encodeURIComponent(controller)}/usage`)
  return data
}

export async function startPvcPrune(
  controller: string,
  opts: { categories: string[]; ado_confirmed: boolean; ado?: string | null; keep_builds?: number; dry_run: boolean; pct?: number },
): Promise<PvcPruneStart> {
  const { data } = await apiClient.post(`/automation/pvc-cleanup/${encodeURIComponent(controller)}/prune`, opts)
  return data
}

export async function getPvcPruneStatus(controller: string): Promise<PvcPruneStatus> {
  const { data } = await apiClient.get(`/automation/pvc-cleanup/${encodeURIComponent(controller)}/prune-status`)
  return data
}

export async function emailPvcAdo(controller: string): Promise<PvcEmailResult> {
  const { data } = await apiClient.post(`/automation/pvc-cleanup/${encodeURIComponent(controller)}/email-ado`)
  return data
}

export async function completePvcPrune(
  controller: string,
  payload: { ticket_key: string; reclaimed_bytes: number; items: number; report?: Record<string, { items?: number }> },
): Promise<{ ok: boolean; ticket: string }> {
  const { data } = await apiClient.post(`/automation/pvc-cleanup/${encodeURIComponent(controller)}/prune-complete`, payload)
  return data
}

// Admin: stage the slack-cli users cache (email -> handle) into EFS
export interface SlackDirectoryMeta { staged: boolean; count: number; fetched_at: string | null }

export async function getSlackDirectory(): Promise<SlackDirectoryMeta> {
  const { data } = await apiClient.get('/admin/slack-directory')
  return data
}

export async function uploadSlackDirectory(payload: unknown): Promise<{ count: number; fetched_at: string | null }> {
  const { data } = await apiClient.post('/admin/slack-directory', payload)
  return data
}

// ─── GitHub analytics ─────────────────────────────────────────────────────────

export interface GitHubArea {
  available: boolean
  status: number
  scopes_needed: string[]
  enterprises?: string[]
}

export interface GitHubCapabilities {
  configured: boolean
  login?: string
  scopes?: string[]
  org?: string
  enterprise?: string
  areas?: Record<string, GitHubArea>
  locked?: string[]
  missing_scopes?: string[]
  sso?: { required: boolean; authorization_url: string }
  unreadable_team_repos?: string[]
  org_role?: string | null
  error?: string | null
}

export interface GitHubPullRequest {
  repo: string
  number: number
  title: string
  author: string
  url: string
  draft: boolean
  review_decision: string | null
  created_at: string
  age_days: number
  bucket: 'approved' | 'changes_requested' | 'needs_review' | 'draft'
  stale: boolean
}

export interface GitHubPullRequests {
  scope: string
  total: number
  returned: number
  truncated: boolean
  counts: Record<string, number>
  stale_count: number
  bot_count: number
  pull_requests: GitHubPullRequest[]
  error?: string | null
}

export interface GitHubRepo {
  name: string
  private: boolean
  language: string | null
  open_issues: number
  pushed_at: string | null
  pushed_days: number
  archived: boolean
  url: string
  is_team_repo: boolean
}

export interface GitHubRepos {
  page_size: number
  repos: GitHubRepo[]
  team_repos: GitHubRepo[]
  recent_count?: number
  recent_days_threshold?: number
  stale?: GitHubRepo[]
  stale_count?: number
  stale_days_threshold?: number
  archived_count?: number
  error?: string | null
}

export async function getGitHubCapabilities(): Promise<GitHubCapabilities> {
  const { data } = await apiClient.get('/github/capabilities')
  return data
}

export async function getGitHubPullRequests(scope: 'team' | 'org'): Promise<GitHubPullRequests> {
  const { data } = await apiClient.get('/github/pull-requests', { params: { scope } })
  return data
}

export async function getGitHubRepos(limit = 15): Promise<GitHubRepos> {
  const { data } = await apiClient.get('/github/repos', { params: { limit } })
  return data
}

export async function refreshGitHubCache(): Promise<{ refreshed: boolean }> {
  const { data } = await apiClient.post('/github/refresh')
  return data
}

export interface GitHubStatusComponent {
  name: string
  status: string
  label: string
}

export interface GitHubStatusIncident {
  name: string
  status: string
  impact: string
  shortlink: string
  updated_at: string
}

export interface GitHubStatus {
  indicator: string
  description: string
  components: GitHubStatusComponent[]
  degraded: GitHubStatusComponent[]
  incidents: GitHubStatusIncident[]
  checked_at: string
  url: string
  error?: string | null
}

export async function getGitHubStatus(): Promise<GitHubStatus> {
  const { data } = await apiClient.get('/github/status')
  return data
}

export interface OrgInviteEligibility {
  can_send: boolean
  login: string | null
}

export async function getOrgInviteEligibility(): Promise<OrgInviteEligibility> {
  const { data } = await apiClient.get('/github/org-invites/can-send')
  return data
}

export interface AccessibleOrgs {
  orgs: string[]
  default: string
}

export async function getAccessibleOrgs(): Promise<AccessibleOrgs> {
  const { data } = await apiClient.get('/github/orgs')
  return data
}

// ─── Bulk background jobs (org invites, Copilot seats, repo creation) ─────────
//
// Each "start" call returns a job id immediately; the actual work (which can
// run for a while with no bulk endpoint on GitHub's side for invites, or
// hundreds of handles to check for seats/repos) happens in a background
// thread. Poll getBulkJob() for progress and, once status is "done" or
// "error", the final per-item results.

export interface BulkJob<TResult = unknown, TExtra = Record<string, unknown>> {
  id: string
  kind: string
  status: 'running' | 'done' | 'error'
  total: number
  done: number
  current: string | null
  results: TResult[]
  extra: TExtra
  error: string | null
}

export async function getBulkJob<TResult = unknown, TExtra = Record<string, unknown>>(
  jobId: string,
): Promise<BulkJob<TResult, TExtra>> {
  const { data } = await apiClient.get(`/github/jobs/${jobId}`)
  return data
}

export interface OrgInviteResult {
  email: string
  ok: boolean
  invitation_id?: number
  role?: string
  error?: string
}

export interface OrgInviteJobExtra {
  invited_by: string | null
  org: string
  team: string | null
  role: string
}

export async function sendOrgInvites(
  emails: string[],
  role: 'member' | 'owner',
  team: string,
  approvalNote: string,
  org: string,
): Promise<{ job_id: string }> {
  const { data } = await apiClient.post('/github/org-invites', {
    emails, role, team, approval_note: approvalNote, org,
  })
  return data
}

export interface CopilotSeatJobExtra {
  assigned_by: string | null
  org: string
  policy_warning: string | null
  rejected_input: { value: string; reason: string }[]
  not_members: string[]
  pending_invite: string[]
  undetermined: string[]
  already_seated: string[]
  assigned: string[]
  assign_failed: string[]
  assign_unverifiable: string[]
}

export async function getCopilotSeatEligibility(): Promise<OrgInviteEligibility> {
  const { data } = await apiClient.get('/github/copilot/seats/can-assign')
  return data
}

export async function assignCopilotSeats(handles: string[], org: string): Promise<{ job_id: string }> {
  const { data } = await apiClient.post('/github/copilot/seats/assign', { handles, org })
  return data
}

export interface RepoCreateSpec {
  name: string
  requestor: string
  extra_admins: string[]
  ticket_key: string
}

export interface RepoCreateStepResult {
  team?: string
  username?: string
  role?: string
  ok: boolean
  error: string | null
  verified: boolean
}

export interface RepoCreateResult {
  name: string
  requestor: string
  extra_admins: string[]
  ok: boolean
  repo_created: boolean
  repo_already_existed: boolean
  repo_error: string | null
  teams: RepoCreateStepResult[]
  collaborators: RepoCreateStepResult[]
  invalid_handles: string[]
  skipped_non_members: string[]
}

export interface RepoCreateJobExtra {
  created_by: string | null
  org: string
}

export async function getRepoCreateEligibility(): Promise<OrgInviteEligibility> {
  const { data } = await apiClient.get('/github/repos/can-create')
  return data
}

export async function createRepos(specs: RepoCreateSpec[], forceExisting = false): Promise<{ job_id: string }> {
  const { data } = await apiClient.post('/github/repos/create', { specs, force_existing: forceExisting })
  return data
}

export interface GitHubCopilotSeat {
  login: string
  organization: string | null
  created_at: string | null
  last_activity_at: string | null
  idle_days: number | null
  editor: string | null
  pending_cancellation_date: string | null
  never_used: boolean
  idle: boolean
}

export interface GitHubCopilot {
  enterprise: string
  total_seats: number
  fetched: number
  never_used_count: number
  idle_count: number
  active_count: number
  pending_cancellation: number
  avg_idle_days: number | null
  idle_days_threshold: number
  by_org: {
    organization: string
    seats: number
    never_used: number
    idle: number
    active: number
    active_pct: number
  }[]
  seats: GitHubCopilotSeat[]
  error?: string | null
}

export interface GitHubCopilotPowerUser {
  login: string
  budget_amount: number
  blocks_at_cap: boolean
  alerting: boolean
  credits_used: number | null
  never_used: boolean
  idle_days: number | null
  editor: string | null
  organization: string | null
  has_seat: boolean
  downgrade_candidate: boolean
}

export interface GitHubCopilotPowerUsers {
  enterprise: string
  users: GitHubCopilotPowerUser[]
  pools: { name: string; budget_amount: number; blocks_at_cap: boolean }[]
  total: number
  downgrade_candidates: number
  usage_available: boolean
  usage_note?: string | null
  idle_days_threshold: number
  error?: string | null
}

export async function getGitHubCopilotPowerUsers(): Promise<GitHubCopilotPowerUsers> {
  const { data } = await apiClient.get('/github/copilot/power-users')
  return data
}

export interface GitHubLicenses {
  enterprise: string
  purchased: number
  consumed: number
  available: number
  used_pct: number
  error?: string | null
}

export async function getGitHubCopilot(): Promise<GitHubCopilot> {
  const { data } = await apiClient.get('/github/copilot')
  return data
}

export interface GitHubCopilotIdentity {
  eua: string | null
  email: string | null
  name: string | null
  source: 'ad' | 'verified_domain' | null
}

export interface GitHubCopilotIdentities {
  identities: Record<string, GitHubCopilotIdentity>
  reminders?: Record<string, { sent_at: string; ordinal: number; to: string[]; by: string }[]>
  requested: number
  resolved: number
}

export interface GitHubCopilotRemindResult {
  sent: number
  requested: number
  results: { login: string; email?: string; sent: boolean; error?: string | null }[]
}

export async function getGitHubCopilotIdentities(logins: string[]): Promise<GitHubCopilotIdentities> {
  const { data } = await apiClient.post('/github/copilot/identities', { logins })
  return data
}

export async function nudgeGitHubCopilotSeats(logins: string[]): Promise<GitHubCopilotRemindResult> {
  const { data } = await apiClient.post('/github/copilot/remind', { logins })
  return data
}

export interface GitHubEnterpriseTeam {
  slug: string
  name: string | null
  members: number
  created_at?: string | null
}

export interface GitHubEnterpriseTeams {
  enterprise?: string
  teams: GitHubEnterpriseTeam[]
  error?: string | null
}

export interface GitHubTeamCopilotReport {
  enterprise: string
  team: string
  members: number
  idle_days_threshold: number
  with_seat: number
  no_seat: number
  active: number
  never_used: number
  idle: number
  with_budget: number
  identities_resolved: number
  error?: string | null
}

export async function getGitHubEnterpriseTeams(): Promise<GitHubEnterpriseTeams> {
  const { data } = await apiClient.get('/github/teams')
  return data
}

export async function getGitHubTeamCopilotReport(team: string): Promise<GitHubTeamCopilotReport> {
  const { data } = await apiClient.get('/github/reports/team-copilot', { params: { team } })
  return data
}

/** Download the report as a CSV.
 *
 *  Fetched through apiClient rather than a plain link because the API needs the
 *  bearer token, which a browser navigation would not send. The filename comes
 *  from Content-Disposition so the server stays the one naming the file.
 */
export async function downloadTeamCopilotCsv(team: string): Promise<string> {
  const res = await apiClient.get('/github/reports/team-copilot.csv', {
    params: { team },
    responseType: 'blob',
  })
  const disposition = String(res.headers['content-disposition'] ?? '')
  const match = disposition.match(/filename="?([^"]+)"?/)
  const filename = match ? match[1] : `${team}-copilot.csv`

  const url = URL.createObjectURL(res.data as Blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    // Revoke on the next tick; revoking synchronously can cancel the download.
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }
  return filename
}

export async function getGitHubLicenses(): Promise<GitHubLicenses> {
  const { data } = await apiClient.get('/github/licenses')
  return data
}

export type CopilotBudgetStatus = 'over' | 'near' | 'warning' | 'healthy' | 'unknown'

export interface GitHubCostCenterResource {
  type: string
  name: string
}

export interface GitHubCostCenterSpend {
  cost_center: string
  cost_center_id: string | null
  state: string | null
  resources: GitHubCostCenterResource[]
  budget_amount: number
  prevent_further_usage: boolean
  alerting: boolean
  users_healthy: number
  users_warning_75: number
  users_near_90: number
  users_over_100: number
  users_total: number
  users_at_risk: number
  status: CopilotBudgetStatus
}

export interface GitHubUnbudgetedCostCenter {
  cost_center: string
  cost_center_id: string | null
  state: string | null
  resources: GitHubCostCenterResource[]
}

export interface GitHubCostCenterIndividualBudgets {
  cost_center: string
  cost_center_id: string | null
  state: string | null
  resources: GitHubCostCenterResource[]
  members_with_budget: string[]
  members_with_budget_count: number
  members_at_risk: number
  status: CopilotBudgetStatus
}

export interface GitHubCopilotSpendPerson {
  login: string
  budget_amount: number
  consumed_amount: number | null
  pct_used: number | null
  prevent_further_usage: boolean
  expires_at: string | null
  status: CopilotBudgetStatus
}

export interface GitHubCopilotSpend {
  enterprise: string
  cost_centers: GitHubCostCenterSpend[]
  cost_centers_at_risk: number
  cost_centers_individual: GitHubCostCenterIndividualBudgets[]
  unbudgeted_cost_centers: GitHubUnbudgetedCostCenter[]
  people: GitHubCopilotSpendPerson[]
  people_at_risk: number
  error?: string | null
}

export async function getGitHubCopilotSpend(): Promise<GitHubCopilotSpend> {
  const { data } = await apiClient.get('/github/copilot/spend')
  return data
}

export interface GitHubCopilotBillingMonth {
  year: number
  month: number
  net_amount: number
  line_items: number
}

export interface GitHubCopilotBillingSku {
  sku: string
  net_amount: number
  quantity: number
}

export interface GitHubCopilotBillingSpend {
  enterprise: string
  monthly: GitHubCopilotBillingMonth[]
  by_sku: GitHubCopilotBillingSku[]
  total_net_amount: number
  error?: string | null
}

export async function getGitHubCopilotBillingSpend(): Promise<GitHubCopilotBillingSpend> {
  const { data } = await apiClient.get('/github/copilot/billing-spend')
  return data
}

export interface GitHubCopilotIdeUsage {
  ide: string
  interactions: number
  generations: number
  acceptances: number
  lines_added: number
}

export interface GitHubCopilotModelUsage {
  model: string
  interactions: number
  generations: number
  acceptances: number
  lines_added: number
}

export interface GitHubCopilotLanguageUsage {
  language: string
  generations: number
  acceptances: number
  lines_added: number
  lines_suggested: number
}

export interface GitHubCopilotFeatureUsage {
  feature: string
  label: string
  interactions: number
  generations: number
  acceptances: number
}

export interface GitHubCopilotUsageAdoption {
  enterprise: string
  report_start_day: string
  report_end_day: string
  latest_day: string
  daily_active_users: number
  weekly_active_users: number
  monthly_active_users: number
  monthly_active_chat_users: number
  monthly_active_agent_users: number
  total_interactions: number
  total_generations: number
  total_acceptances: number
  acceptance_rate: number | null
  daily_active_users_trend: { day: string; active_users: number }[]
  by_ide: GitHubCopilotIdeUsage[]
  by_model: GitHubCopilotModelUsage[]
  by_language: GitHubCopilotLanguageUsage[]
  by_feature: GitHubCopilotFeatureUsage[]
  chat_interactions: number
  chat_generations: number
  chat_acceptances: number
  chat_acceptance_rate: number | null
  error?: string | null
}

export async function getGitHubCopilotUsageAdoption(): Promise<GitHubCopilotUsageAdoption> {
  const { data } = await apiClient.get('/github/copilot/usage-adoption')
  return data
}

export interface GitHubCopilotPerson {
  login: string
  interactions: number
  generations: number
  acceptances: number
  lines_added: number
  lines_suggested: number
  line_acceptance_rate: number | null
  active_days: number
  acceptance_rate: number | null
  ai_credits_used: number
  top_model: string | null
  models_used: string[]
}

export interface GitHubCopilotPeople {
  enterprise: string
  report_start_day: string
  report_end_day: string
  total_users: number
  total_ai_credits_used: number
  people: GitHubCopilotPerson[]
  error?: string | null
}

export async function getGitHubCopilotPeople(): Promise<GitHubCopilotPeople> {
  const { data } = await apiClient.get('/github/copilot/people')
  return data
}

export interface GitHubCopilotPersonSeat {
  idle_days: number | null
  never_used: boolean
  editor: string | null
  organization: string | null
}

export interface GitHubCopilotPersonBudget {
  login: string
  budget_amount: number
  consumed_amount: number | null
  pct_used: number | null
  prevent_further_usage: boolean
  expires_at: string | null
  status: CopilotBudgetStatus
}

export interface GitHubCopilotBudgetPacing {
  label: 'over_budget' | 'ahead_of_pace' | 'well_behind_pace' | 'behind_pace' | 'on_pace'
  tone: 'bad' | 'warn' | 'neutral' | 'good'
  gap: number
  note: string | null
  month_elapsed_pct: number
}

export interface GitHubCopilotModelFeatureCell {
  value: number
  share: number | null
}

export interface GitHubCopilotModelFeatureRow {
  model: string
  cells: GitHubCopilotModelFeatureCell[]
}

export interface GitHubCopilotModelFeatureColumn {
  id: string
  label: string
  total: number
  unit: 'prompts' | 'suggestions'
}

export interface GitHubCopilotModelFeatureFavourite {
  feature: string
  model: string
  share: number
  value: number
  unit: 'prompts' | 'suggestions'
}

export interface GitHubCopilotModelFeatureMatrix {
  empty: boolean
  columns: GitHubCopilotModelFeatureColumn[]
  rows: GitHubCopilotModelFeatureRow[]
  favourites: GitHubCopilotModelFeatureFavourite[]
  top_model: string
  top_feature: string
}

export interface GitHubCopilotModelFeatureDetailRow {
  model: string
  feature: string
  prompts: number
  suggestions: number
  acceptances: number
  lines: number
}

export interface GitHubCopilotPersonDetail {
  login: string
  report_start_day: string
  report_end_day: string
  active_days: number
  interactions: number
  generations: number
  acceptances: number
  acceptance_rate: number | null
  lines_added: number
  lines_suggested: number
  line_acceptance_rate: number | null
  ai_credits_used: number
  seat: GitHubCopilotPersonSeat | null
  budget: GitHubCopilotPersonBudget | null
  budget_pacing: GitHubCopilotBudgetPacing | null
  model_feature_matrix: GitHubCopilotModelFeatureMatrix
  model_feature_rows: GitHubCopilotModelFeatureDetailRow[]
  error?: string | null
}

export async function getGitHubCopilotPerson(login: string): Promise<GitHubCopilotPersonDetail> {
  const { data } = await apiClient.get(`/github/copilot/people/${encodeURIComponent(login)}`)
  return data
}

// ─── CLDSPT GitHub access requests ───────────────────────────────────────────

export interface CldsptEngineer {
  username: string
  name: string
  open: number
  all_time: number
  completed_since_yesterday?: number
  buckets: Record<string, number>
  categories: Record<string, number>
  cross: Record<string, number>
  bo_approval: Record<string, number>
}

export interface CldsptQueue {
  generated_at: string | null
  match?: string
  all_time_total: number | null
  accounted_total?: number
  unaccounted?: number | null
  open_total: number | null
  done_total?: number | null
  unassigned_open?: number
  by_status?: Record<string, number>
  by_bucket?: Record<string, number>
  by_bucket_open?: Record<string, number>
  by_category?: Record<string, number>
  status_categories?: Record<string, string>
  unmapped_statuses?: string[]
  bucket_labels: Record<string, string>
  category_labels?: Record<string, string>
  open_buckets?: string[]
  application_set?: number
  application_blank?: number
  application_inferred_confirmed?: number
  throughput?: {
    since_yesterday: number
    today: number
    canceled_since_yesterday: number
  }
  bo_approval_totals?: Record<string, number>
  bo_approval_labels?: Record<string, string>
  last_nudged?: Record<string, { at: string | null; by: string | null; tickets: string[] }>
  engineers: CldsptEngineer[]
  error: string | null
}

export interface CldsptComment {
  author: string | null
  created: string | null
  body: string
  truncated: boolean
  count: number
}

export interface CldsptApprover {
  username: string
  name: string
}

export interface CldsptTicket {
  key: string
  summary: string | null
  status: string
  bucket: string
  category: string
  updated: string | null
  created: string | null
  url: string
  approvers: CldsptApprover[]
  application_name: string | null
  application_inferred?: {
    name: string | null
    source: 'justification' | 'ad_groups' | null
    matched_on: string | null
    confirmed: boolean
    candidates: { justification: string[]; ad_groups: string[] }
    users?: string[]
  } | null
  business_owner: string | null
  bo_approval: {
    state: 'approved' | 'second_stage_requested' | 'bo_approved' | 'requested' | 'required' | 'not_required'
    requested_on: string | null
    bo_requested_on: string | null
    approved_by: string | null
    approved_on: string | null
    approved_is_bo: boolean
    second_stage_approver: string
    second_stage_requested_on: string | null
    second_stage_approved_by: string | null
    second_stage_approved_on: string | null
  }
  latest_comment: CldsptComment | null
}

export interface CldsptEngineerTickets {
  username: string
  name?: string
  include_done?: boolean
  total: number | null
  returned?: number
  tickets: CldsptTicket[]
  error: string | null
}

export async function getCldsptQueue(): Promise<CldsptQueue> {
  const { data } = await apiClient.get('/jira/cldspt/queue')
  return data
}

export async function startCldsptSweep(): Promise<{ started: boolean; reason?: string }> {
  const { data } = await apiClient.post('/jira/cldspt/sweep')
  return data
}

export async function getCldsptSweepStatus(): Promise<{
  running: boolean
  started_at: string | null
  last_error: string | null
  generated_at: string | null
  all_time_total: number | null
  open_total: number | null
}> {
  const { data } = await apiClient.get('/jira/cldspt/sweep-status')
  return data
}

export async function requestBoApproval(issueKey: string): Promise<{
  posted: boolean
  key: string
  mentioned?: string
  business_owner?: string | null
  body?: string
}> {
  const { data } = await apiClient.post(`/jira/cldspt/${issueKey}/request-bo-approval`)
  return data
}

export async function requestSecondStageApproval(issueKey: string): Promise<{
  posted: boolean
  key: string
  mentioned?: string
  approver?: string
  body?: string
}> {
  const { data } = await apiClient.post(`/jira/cldspt/${issueKey}/request-second-stage-approval`)
  return data
}

export interface CldsptSlackNudge {
  posted: boolean
  channel: string
  channel_url: string
  approver: string
  engineer: string
  tickets: string[]
  message: string
  can_post: boolean
}

export async function sendCldsptSlackNudge(username: string): Promise<CldsptSlackNudge> {
  const { data } = await apiClient.post(`/jira/cldspt/engineer/${username}/slack-nudge`)
  return data
}

export async function getCldsptEngineer(
  username: string,
  includeDone = false,
): Promise<CldsptEngineerTickets> {
  const { data } = await apiClient.get(`/jira/cldspt/engineer/${username}`, {
    params: { include_done: includeDone },
  })
  return data
}

export interface CldsptQueueTicket {
  key: string
  summary: string
  status: string
  issue_type: string
  assignee: string | null
  assignee_name: string | null
  needs_pickup: boolean
  reporter: string | null
  reporter_name: string | null
  created: string
  updated: string
  url: string
}

export interface CldsptSelfServiceQueue {
  total: number | null
  returned: number
  needs_pickup: number
  tickets: CldsptQueueTicket[]
  error?: string | null
}

export async function getCldsptSelfServiceQueue(): Promise<CldsptSelfServiceQueue> {
  const { data } = await apiClient.get('/jira/cldspt/self-service-queue')
  return data
}

export interface CldsptTransition {
  id: string
  name: string
  to_status: string
}

export interface CldsptTransitions {
  key: string
  transitions: CldsptTransition[]
  error?: string | null
}

export async function getCldsptTransitions(issueKey: string): Promise<CldsptTransitions> {
  const { data } = await apiClient.get(`/jira/cldspt/${issueKey}/transitions`)
  return data
}

export async function assignCldsptToMe(issueKey: string): Promise<{ assigned: boolean; key: string; assignee?: string }> {
  const { data } = await apiClient.post(`/jira/cldspt/${issueKey}/assign-to-me`)
  return data
}

export async function transitionCldsptTicket(
  issueKey: string,
  transitionId: string,
  comment?: string,
): Promise<{ transitioned: boolean; key: string }> {
  const { data } = await apiClient.post(`/jira/cldspt/${issueKey}/transition`, {
    transition_id: transitionId,
    comment: comment || undefined,
  })
  return data
}
