import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, Download, Loader2 } from 'lucide-react'
import {
  apiErrorMessage,
  downloadTeamCopilotCsv,
  getGitHubEnterpriseTeams,
  type GitHubEnterpriseTeam,
} from '../../api/client'

/** Copilot reporting per enterprise team.
 *
 *  Enterprise teams are the unit worth reporting on because the billing cost
 *  centers point at them, so a team's roster is also who draws on its credit
 *  pool. The CSV is rendered server-side, so what downloads is the same data
 *  the counts are taken from.
 */
export default function GitHubReporting() {
  const [teams, setTeams] = useState<GitHubEnterpriseTeam[] | null>(null)
  const [team, setTeam] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await getGitHubEnterpriseTeams()
      if (res.error) setError(res.error)
      const withMembers = (res.teams ?? []).filter(t => t.members > 0)
      setTeams(withMembers)
      // Largest team first from the API, which is the one most likely wanted.
      if (withMembers.length > 0) setTeam(withMembers[0].slug)
    } catch (err: unknown) {
      setError(apiErrorMessage(err, 'Could not list the enterprise teams.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function download() {
    if (!team) return
    setBusy(true)
    setError('')
    setDone('')
    try {
      setDone(await downloadTeamCopilotCsv(team))
    } catch (err: unknown) {
      setError(apiErrorMessage(err, `Could not build the report for ent:${team}.`))
    } finally {
      setBusy(false)
    }
  }

  const selected = (teams ?? []).find(t => t.slug === team)

  return (
    <section>
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-4">
        <p className="text-xs ds-u-color--muted">Copilot adoption by enterprise team</p>

        {loading ? (
          <p className="mt-3 flex items-center gap-2 text-sm ds-u-color--muted">
            <Loader2 size={14} className="animate-spin" /> Reading the enterprise teams…
          </p>
        ) : (teams ?? []).length === 0 ? (
          <p className="mt-3 text-xs ds-u-color--muted">No enterprise teams have members yet.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <select
                value={team}
                onChange={(e) => { setTeam(e.target.value); setDone('') }}
                disabled={busy}
                className="border border-gray-300 dark:border-gray-600 dark:bg-gray-700 rounded-lg px-2.5 py-1.5 text-sm min-w-[16rem] disabled:opacity-50"
              >
                {(teams ?? []).map(t => (
                  <option key={t.slug} value={t.slug}>
                    ent:{t.slug} ({t.members} {t.members === 1 ? 'member' : 'members'})
                  </option>
                ))}
              </select>
              <button
                onClick={download}
                disabled={busy || !team}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium bg-cms-blue text-white hover:opacity-90 disabled:opacity-50"
              >
                {busy
                  ? <><Loader2 size={14} className="animate-spin" /> Building…</>
                  : <><Download size={14} /> Download CSV</>}
              </button>
              {done && (
                <span className="inline-flex items-center gap-1 text-xs text-green-700">
                  <CheckCircle size={12} /> {done}
                </span>
              )}
            </div>

            {selected && (
              <p className="text-[11px] ds-u-color--muted mt-2">
                A row per member: name, email, EUA, organization, whether they hold a Copilot
                seat, when they last used it, and any dedicated AI-credit budget. The people
                needing attention sort to the top.
                {selected.members > 100 && ' This one is large, so the first build takes a moment.'}
              </p>
            )}
          </>
        )}

        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-xs mt-3">
            <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
            {error}
          </div>
        )}
      </div>
    </section>
  )
}
