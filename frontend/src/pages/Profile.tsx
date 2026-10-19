import { useState, useEffect, FormEvent, useRef } from 'react'
import { User, Mail, Users, Shield, MessageSquare, Phone, Save, CheckCircle, Loader2, Camera, Trash2, AlertCircle, Github, Eye, EyeOff } from 'lucide-react'
import { updateProfile, uploadAvatar, deleteAvatar, apiErrorMessage,
  getGithubPat, saveGithubPat, validateGithubPat, deleteGithubPat, type GithubPatStatus } from '../api/client'
import { useAuth } from '../App'

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

export default function Profile() {
  const { user, setUser } = useAuth()
  const [form, setForm] = useState({
    display_name: '',
    team: '',
    job_title: '',
    slack_handle: '',
    phone: '',
  })
  const [loading, setLoading] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [avatarUploading, setAvatarUploading] = useState(false)
  const [avatarError, setAvatarError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (user) {
      setForm({
        display_name: user.display_name ?? '',
        team: user.team ?? '',
        job_title: user.job_title ?? '',
        slack_handle: user.slack_handle ?? '',
        phone: user.phone ?? '',
      })
    }
  }, [user])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setSaved(false)
    setLoading(true)
    try {
      const updated = await updateProfile(form)
      setUser(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to save profile. Please try again.'))
    } finally {
      setLoading(false)
    }
  }

  async function handleAvatarPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''   // allow re-selecting the same file later
    if (!file) return
    setAvatarError('')
    setAvatarUploading(true)
    try {
      const { avatar_url } = await uploadAvatar(file)
      if (user) setUser({ ...user, avatar_url })
    } catch (err: any) {
      setAvatarError(apiErrorMessage(err, 'Avatar upload failed.'))
    } finally {
      setAvatarUploading(false)
    }
  }

  async function handleAvatarRemove() {
    setAvatarError('')
    setAvatarUploading(true)
    try {
      await deleteAvatar()
      if (user) setUser({ ...user, avatar_url: null })
    } catch (err: any) {
      setAvatarError(apiErrorMessage(err, 'Could not remove avatar.'))
    } finally {
      setAvatarUploading(false)
    }
  }

  const initials = getInitials(form.display_name || user?.username || '?')
  const avatarUrl = user?.avatar_url

  return (
    <div className="max-w-2xl mx-auto">
      {/* Avatar section */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mb-6">
        <div className="flex items-center gap-5">
          <div className="relative group flex-shrink-0">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={avatarUploading}
              className="w-20 h-20 rounded-full overflow-hidden bg-cms-blue flex items-center justify-center disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-cms-blue focus:ring-offset-2"
              title={avatarUrl ? 'Change profile picture' : 'Upload profile picture'}
            >
              {avatarUrl ? (
                <img src={avatarUrl} alt="Profile" className="w-full h-full object-cover" />
              ) : (
                <span className="text-white text-2xl font-bold">{initials}</span>
              )}
              <span className="absolute inset-0 rounded-full bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                {avatarUploading ? (
                  <Loader2 size={20} className="text-white animate-spin" />
                ) : (
                  <Camera size={20} className="text-white" />
                )}
              </span>
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={handleAvatarPick}
            />
            {avatarUrl && !avatarUploading && (
              <button
                type="button"
                onClick={handleAvatarRemove}
                className="absolute -bottom-1 -right-1 w-7 h-7 rounded-full bg-white border border-gray-200 shadow-sm flex items-center justify-center ds-u-color--muted hover:text-red-600 hover:border-red-200"
                title="Remove profile picture"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold text-gray-900">
              {form.display_name || user?.username}
            </h2>
            <p className="text-sm ds-u-color--muted">{user?.email}</p>
            <div className="flex items-center gap-2 mt-1">
              {form.team && (
                <span className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                  <Users size={10} />
                  {form.team}
                </span>
              )}
              {form.job_title && (
                <span className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
                  <Shield size={10} />
                  {form.job_title}
                </span>
              )}
            </div>
            {avatarError && (
              <div className="flex items-center gap-1.5 text-xs text-red-600 mt-2">
                <AlertCircle size={12} /> {avatarError}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Profile form */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h3 className="text-sm font-semibold text-gray-800 mb-5 flex items-center gap-2">
          <User size={16} className="text-cms-blue" />
          Profile Settings
        </h3>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              {error}
            </div>
          )}

          {/* Email (read-only) */}
          <div>
            <label className="label flex items-center gap-1.5">
              <Mail size={13} className="ds-u-color--muted" />
              Email
              <span className="text-xs ds-u-color--muted font-normal ml-1">(LDAP-managed)</span>
            </label>
            <input
              type="email"
              className="input-field bg-gray-50 ds-u-color--muted cursor-not-allowed"
              value={user?.email ?? ''}
              readOnly
              disabled
            />
          </div>

          {/* Display Name */}
          <div>
            <label className="label flex items-center gap-1.5">
              <User size={13} className="ds-u-color--muted" />
              Display Name
            </label>
            <input
              type="text"
              className="input-field"
              value={form.display_name}
              onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
              placeholder="Jane Smith"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Team */}
            <div>
              <label className="label flex items-center gap-1.5">
                <Users size={13} className="ds-u-color--muted" />
                Team
              </label>
              <input
                type="text"
                className="input-field"
                value={form.team}
                onChange={(e) => setForm((f) => ({ ...f, team: e.target.value }))}
                placeholder="DMSC"
              />
            </div>

            {/* Job Title */}
            <div>
              <label className="label flex items-center gap-1.5">
                <Shield size={13} className="ds-u-color--muted" />
                Job Title
              </label>
              <input
                type="text"
                className="input-field"
                value={form.job_title}
                onChange={(e) => setForm((f) => ({ ...f, job_title: e.target.value }))}
                placeholder="DevOps Engineer"
              />
            </div>
          </div>

          {/* Slack Handle */}
          <div>
            <label className="label flex items-center gap-1.5">
              <MessageSquare size={13} className="ds-u-color--muted" />
              Slack Handle
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 ds-u-color--muted text-sm">@</span>
              <input
                type="text"
                className="input-field pl-7"
                value={form.slack_handle}
                onChange={(e) =>
                  setForm((f) => ({ ...f, slack_handle: e.target.value.replace(/^@/, '') }))
                }
                placeholder="jane.smith"
              />
            </div>
          </div>

          {/* Phone */}
          <div>
            <label className="label flex items-center gap-1.5">
              <Phone size={13} className="ds-u-color--muted" />
              Phone
            </label>
            <input
              type="tel"
              className="input-field"
              value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
              placeholder="+1-555-0100"
            />
          </div>

          {/* Submit */}
          <div className="flex items-center gap-3 pt-2">
            <button
              type="submit"
              disabled={loading}
              className="btn-primary flex items-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save size={15} />
                  Save Changes
                </>
              )}
            </button>
            {saved && (
              <div className="flex items-center gap-1.5 text-green-600 text-sm">
                <CheckCircle size={15} />
                Saved!
              </div>
            )}
          </div>
        </form>
      </div>

      {/* Account info */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mt-6">
        <h3 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
          <Shield size={16} className="text-cms-blue" />
          Account Information
        </h3>
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between py-2 border-b border-gray-50">
            <span className="ds-u-color--muted">Username</span>
            <span className="text-gray-800 font-mono">{user?.username}</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-gray-50">
            <span className="ds-u-color--muted">Authentication</span>
            <span className="text-gray-800">LDAP</span>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="ds-u-color--muted">Access Level</span>
            <span className="inline-flex items-center gap-1 bg-cms-blue-light text-cms-blue px-2 py-0.5 rounded-full text-xs font-medium">
              <Shield size={10} />
              {user?.role || 'User'}
            </span>
          </div>
        </div>
      </div>

      <GithubPatSection />
    </div>
  )
}

function GithubPatSection() {
  const [status, setStatus] = useState<GithubPatStatus | null>(null)
  const [pat, setPat] = useState('')
  const [showPat, setShowPat] = useState(false)
  const [busy, setBusy] = useState('')       // 'save' | 'validate' | 'remove'
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => { getGithubPat().then(setStatus).catch(() => setStatus(null)) }, [])

  async function run(kind: string, fn: () => Promise<GithubPatStatus>, okMsg: string) {
    setError(''); setMsg(''); setBusy(kind)
    try {
      const s = await fn(); setStatus(s)
      if (kind === 'validate') setMsg(s.valid ? `Valid as ${s.login}` : `Invalid: ${s.error ?? 'check failed'}`)
      else setMsg(okMsg)
      if (kind !== 'validate') setPat('')
    } catch (e) { setError(apiErrorMessage(e, 'Request failed.')) }
    finally { setBusy('') }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mt-6">
      <h3 className="text-sm font-semibold text-gray-800 mb-1 flex items-center gap-2">
        <Github size={16} className="text-cms-blue" /> GitHub Personal Access Token
      </h3>
      <p className="text-xs ds-u-color--muted mb-4">
        Save a PAT so anything the dashboard does on your behalf — commits, org invites, Copilot seat
        assignment — is attributed to <strong>your</strong> GitHub account. Without one, commits fall
        back to the shared service account, and org invites / Copilot seat assignment simply won't run
        for you until you add one. Your token is encrypted with a key derived from your login password,
        stored write-only, and never shown again — no one else (including admins) can read it.
      </p>

      {/* Status pill */}
      <div className="mb-4 text-sm">
        {status?.locked ? (
          <span className="inline-flex items-center gap-1.5 text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full text-xs">
            <AlertCircle size={12} /> Vault locked — log out and back in to manage your PAT
          </span>
        ) : status?.needs_reentry ? (
          <span className="inline-flex items-center gap-1.5 text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full text-xs">
            <AlertCircle size={12} /> Your password changed — re-enter your PAT
          </span>
        ) : status?.set ? (
          <span className="inline-flex items-center gap-1.5 text-green-700 bg-green-50 border border-green-200 px-2.5 py-1 rounded-full text-xs">
            <CheckCircle size={12} /> Set{status.login ? ` — ${status.login}` : ''}{status.validated_at ? ` · validated ${new Date(status.validated_at).toLocaleDateString()}` : ''}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-gray-600 bg-gray-50 border border-gray-200 px-2.5 py-1 rounded-full text-xs">
            Not set — commits use the service account
          </span>
        )}
      </div>

      <div className="flex gap-2 items-stretch max-w-xl">
        <div className="relative flex-1">
          <input
            type={showPat ? 'text' : 'password'}
            className="input-field font-mono text-sm pr-9 w-full"
            placeholder="ghp_… or github_pat_…"
            value={pat}
            onChange={e => setPat(e.target.value)}
            autoComplete="off"
            disabled={!!status?.locked}
          />
          <button type="button" onClick={() => setShowPat(v => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 ds-u-color--muted hover:text-gray-600">
            {showPat ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        </div>
        <button type="button" className="btn-primary flex items-center gap-1.5"
          disabled={!pat.trim() || !!busy || !!status?.locked}
          onClick={() => run('save', () => saveGithubPat(pat.trim()), 'Saved and validated')}>
          {busy === 'save' && <Loader2 size={14} className="animate-spin" />} Save
        </button>
        {status?.set && !status?.needs_reentry && (
          <button type="button" className="btn-secondary flex items-center gap-1.5"
            disabled={!!busy || !!status?.locked}
            onClick={() => run('validate', validateGithubPat, '')}>
            {busy === 'validate' && <Loader2 size={14} className="animate-spin" />} Validate
          </button>
        )}
        {status?.set && (
          <button type="button" className="btn-secondary text-red-600 flex items-center gap-1.5"
            disabled={!!busy}
            onClick={() => run('remove', deleteGithubPat, 'Removed')}>
            {busy === 'remove' ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Remove
          </button>
        )}
      </div>

      {msg && <p className="mt-3 text-sm text-green-700 flex items-center gap-1.5"><CheckCircle size={14} /> {msg}</p>}
      {error && <p className="mt-3 text-sm text-red-600 flex items-center gap-1.5"><AlertCircle size={14} /> {error}</p>}
      <p className="mt-3 text-xs ds-u-color--muted">Needs a token with <code>repo</code> scope. Create at github.com → Settings → Developer settings → Personal access tokens.</p>
    </div>
  )
}
