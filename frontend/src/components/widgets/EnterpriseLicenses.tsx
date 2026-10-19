import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle, Loader2, Mail, Zap } from 'lucide-react'
import {
  apiErrorMessage,
  getGitHubCopilotIdentities,
  getGitHubCopilotPowerUsers,
  nudgeGitHubCopilotSeats,
  type GitHubCopilot,
  type GitHubCopilotIdentities,
  type GitHubCopilotPowerUsers,
  type GitHubLicenses,
} from '../../api/client'
import { RevealTile, StatTile } from './StatTile'

function lastNudge(idents: GitHubCopilotIdentities | null, login: string) {
  const hist = idents?.reminders?.[login]
  if (!hist || hist.length === 0) return null
  const last = hist[hist.length - 1]
  return { ordinal: last.ordinal, on: new Date(last.sent_at).toLocaleDateString() }
}

function activityLabel(u: { has_seat: boolean; never_used: boolean; idle_days: number | null }) {
  if (!u.has_seat) return { text: 'no Copilot seat', tone: 'text-red-600 font-medium' }
  if (u.never_used) return { text: 'never used', tone: 'text-red-600 font-medium' }
  if (u.idle_days === null) return { text: 'unknown', tone: 'ds-u-color--muted' }
  if (u.idle_days === 0) return { text: 'today', tone: 'text-green-700' }
  return {
    text: `${u.idle_days}d ago`,
    tone: u.idle_days >= 30 ? 'text-amber-700' : 'text-gray-600',
  }
}

export default function EnterpriseLicenses({ copilot, licenses }: {
  copilot: GitHubCopilot | null
  licenses: GitHubLicenses | null
}) {
  const [openOrgs, setOpenOrgs] = useState(false)
  const [openUnused, setOpenUnused] = useState(false)
  const [openPower, setOpenPower] = useState(false)
  const [power, setPower] = useState<GitHubCopilotPowerUsers | null>(null)
  const [powerLoading, setPowerLoading] = useState(false)
  const [idents, setIdents] = useState<GitHubCopilotIdentities | null>(null)
  const [identsLoading, setIdentsLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  const seats = copilot?.seats ?? []
  const unusedCount = (copilot?.never_used_count ?? 0) + (copilot?.idle_count ?? 0)

  const loadPower = useCallback(async () => {
    setPowerLoading(true)
    try {
      setPower(await getGitHubCopilotPowerUsers())
    } catch (err: unknown) {
      setNotice({ kind: 'err', text: apiErrorMessage(err, 'Could not read the credit budgets.') })
    } finally {
      setPowerLoading(false)
    }
  }, [])

  useEffect(() => { if (copilot && !copilot.error && !power) loadPower() }, [copilot, power, loadPower])

  const loadIdentities = useCallback(async () => {
    if (seats.length === 0) return
    setIdentsLoading(true)
    try {
      setIdents(await getGitHubCopilotIdentities(seats.map(s => s.login)))
    } catch (err: unknown) {
      setNotice({ kind: 'err', text: apiErrorMessage(err, 'Could not resolve seat holders.') })
    } finally {
      setIdentsLoading(false)
    }
  }, [seats.map(s => s.login).join(',')])

  useEffect(() => { if (openUnused && !idents) loadIdentities() }, [openUnused, idents, loadIdentities])

  async function nudge(logins: string[]) {
    setBusy(logins.length === 1 ? `mail:${logins[0]}` : 'mail:all')
    setNotice(null)
    try {
      const res = await nudgeGitHubCopilotSeats(logins)
      const failed = res.results.filter(r => !r.sent)
      setNotice(
        failed.length === 0
          ? { kind: 'ok', text: `Nudged ${res.sent} seat holder${res.sent === 1 ? '' : 's'} to start using Copilot.` }
          : {
              kind: 'err',
              text: `Sent ${res.sent} of ${res.requested}. Could not reach: ` +
                failed.map(f => `${f.login} (${f.error})`).join('; '),
            },
      )
      await loadIdentities()
    } catch (err: unknown) {
      setNotice({ kind: 'err', text: apiErrorMessage(err, 'The nudge could not be sent.') })
    } finally {
      setBusy(null)
    }
  }

  if (!copilot?.total_seats && !licenses?.purchased) return null

  const mailable = seats.filter(s => idents?.identities?.[s.login]?.email).map(s => s.login)

  return (
    <section>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        {licenses && !licenses.error && (
          <StatTile
            label="Enterprise seats"
            value={`${licenses.consumed.toLocaleString()} / ${licenses.purchased.toLocaleString()}`}
            sub={`${licenses.available.toLocaleString()} available · ${licenses.used_pct}% of purchased consumed`}
            tone={licenses.used_pct >= 95 ? 'text-red-600' : 'text-gray-900 dark:text-gray-100'}
          />
        )}
        {copilot && !copilot.error && (
          <>
            <RevealTile
              label="Copilot seats"
              value={copilot.total_seats.toLocaleString()}
              revealLabel={`${copilot.by_org?.length ?? 0} organizations`}
              disabled={(copilot.by_org?.length ?? 0) === 0}
              open={openOrgs}
              onToggle={() => setOpenOrgs(o => !o)}
            />
            <RevealTile
              label="Using Copilot"
              value={`${copilot.active_count ?? 0} / ${copilot.fetched}`}
              tone="text-green-700"
              revealLabel={unusedCount > 0 ? `${unusedCount} not using it yet` : 'everyone is using it'}
              disabled={unusedCount === 0}
              open={openUnused}
              onToggle={() => setOpenUnused(o => !o)}
            />
            <RevealTile
              label="Copilot power users"
              value={power?.total ?? (powerLoading ? '…' : 0)}
              tone={(power?.downgrade_candidates ?? 0) > 0 ? 'text-amber-600' : 'text-gray-900 dark:text-gray-100'}
              revealLabel={
                (power?.total ?? 0) === 0
                  ? 'none with their own budget'
                  : (power?.downgrade_candidates ?? 0) > 0
                    ? `${power!.downgrade_candidates} worth a look`
                    : 'all of them active'
              }
              disabled={(power?.total ?? 0) === 0}
              open={openPower}
              onToggle={() => setOpenPower(o => !o)}
            />
            {copilot.avg_idle_days !== null && (
              <StatTile
                label="Avg days idle"
                value={copilot.avg_idle_days}
                tone={copilot.avg_idle_days >= copilot.idle_days_threshold ? 'text-amber-600' : 'text-gray-900 dark:text-gray-100'}
                sub="across seats that have ever been used"
              />
            )}
          </>
        )}
      </div>

      {notice && (
        <div className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-xs border ${
          notice.kind === 'ok'
            ? 'bg-green-50 border-green-200 text-green-800'
            : 'bg-red-50 border-red-200 text-red-800'
        }`}>
          {notice.kind === 'ok'
            ? <CheckCircle size={13} className="flex-shrink-0 mt-0.5" />
            : <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />}
          <span>{notice.text}</span>
        </div>
      )}

      {openOrgs && copilot?.by_org && (
        <div className="mt-4 rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">Organization</th>
                <th className="text-left px-3 py-2 font-medium">Seats</th>
                <th className="text-left px-3 py-2 font-medium">Using it</th>
                <th className="text-left px-3 py-2 font-medium">Idle {copilot.idle_days_threshold}d+</th>
                <th className="text-left px-3 py-2 font-medium">Never used</th>
              </tr>
            </thead>
            <tbody>
              {copilot.by_org.map((o, i) => (
                <tr key={o.organization} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                  <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">{o.organization}</td>
                  <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">{o.seats}</td>
                  <td className="px-3 py-2 text-xs">
                    <span className={o.active_pct >= 75 ? 'text-green-700' : 'text-amber-700'}>
                      {o.active} ({o.active_pct}%)
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs ds-u-color--muted">{o.idle || '—'}</td>
                  <td className="px-3 py-2 text-xs">
                    {o.never_used
                      ? <span className="text-red-600">{o.never_used}</span>
                      : <span className="ds-u-color--muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openUnused && copilot && unusedCount > 0 && (
        <div className="mt-4 rounded-lg border border-amber-200 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-900">
            <span className="font-semibold">
              Seat holders not using Copilot ({copilot.never_used_count} never used,{' '}
              {copilot.idle_count} idle {copilot.idle_days_threshold}d+)
            </span>
            <span>CMS licenses Copilot for everyone, so these are nudged to use it, not reclaimed.</span>
          </div>

          <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700">
            <button
              onClick={() => nudge(mailable)}
              disabled={identsLoading || mailable.length === 0 || busy !== null}
              className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50"
            >
              {busy === 'mail:all' ? <Loader2 size={12} className="animate-spin" /> : <Mail size={12} />}
              Nudge all {mailable.length > 0 && `(${mailable.length})`}
            </button>
            {identsLoading && (
              <span className="inline-flex items-center gap-1.5 text-xs ds-u-color--muted">
                <Loader2 size={12} className="animate-spin" /> Resolving seat holders…
              </span>
            )}
            {idents && !identsLoading && (
              <span className="text-xs ds-u-color--muted">
                {idents.resolved} of {idents.requested} have an address on file
              </span>
            )}
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">User</th>
                <th className="text-left px-3 py-2 font-medium">Org</th>
                <th className="text-left px-3 py-2 font-medium">Last activity</th>
                <th className="text-left px-3 py-2 font-medium">Nudges</th>
                <th className="text-right px-3 py-2 font-medium">Nudge</th>
              </tr>
            </thead>
            <tbody>
              {seats.map((seat, i) => {
                const ident = idents?.identities?.[seat.login]
                const prior = lastNudge(idents, seat.login)
                return (
                  <tr key={seat.login} className={i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">
                      {seat.login}
                      {ident?.name && <span className="ml-2 ds-u-color--muted font-normal">{ident.name}</span>}
                      {ident?.email
                        ? <p className="text-[10px] ds-u-color--muted font-normal">{ident.email}</p>
                        : idents && <p className="text-[10px] ds-u-color--muted font-normal">no address on file</p>}
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{seat.organization || '—'}</td>
                    <td className="px-3 py-2 text-xs">
                      {seat.never_used
                        ? <span className="text-red-600 font-medium">never used</span>
                        : <span className="text-amber-700">{seat.idle_days}d ago</span>}
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">
                      {prior ? `${prior.ordinal}× · last ${prior.on}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => nudge([seat.login])}
                        disabled={!ident?.email || busy !== null}
                        title={ident?.email ? `Email ${ident.email}` : 'No address could be resolved for this login'}
                        className="p-1 rounded ds-u-color--muted hover:text-cms-blue hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:hover:bg-transparent"
                      >
                        {busy === `mail:${seat.login}`
                          ? <Loader2 size={13} className="animate-spin" />
                          : <Mail size={13} />}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {seats.length < unusedCount && (
            <p className="px-3 py-1.5 text-[11px] ds-u-color--muted border-t border-gray-100">
              Showing the {seats.length} least active of {unusedCount}.
            </p>
          )}
        </div>
      )}

      {openPower && power && !power.error && power.total > 0 && (
        <div className="mt-4 rounded-lg border border-gray-100 dark:border-gray-700 overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 bg-indigo-50 border-b border-indigo-200 text-xs text-indigo-900">
            <span className="font-semibold flex items-center gap-1.5">
              <Zap size={12} /> Copilot power users ({power.total})
            </span>
            <span>
              {power.downgrade_candidates > 0
                ? `${power.downgrade_candidates} not using Copilot, worth a conversation`
                : 'all of them are using Copilot'}
              {power.pools.length > 0 && (
                <> · pools: {power.pools.map(p => `${p.name} ${p.budget_amount}`).join(', ')}</>
              )}
            </span>
          </div>

          {power.usage_note && (
            <p className="px-3 py-2 text-[11px] ds-u-color--muted bg-gray-50 dark:bg-gray-800 border-b border-gray-100 dark:border-gray-700">
              {power.usage_note}
            </p>
          )}

          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-xs ds-u-color--muted">
                <th className="text-left px-3 py-2 font-medium">User</th>
                <th className="text-left px-3 py-2 font-medium">Org</th>
                <th className="text-left px-3 py-2 font-medium">Credit budget</th>
                <th className="text-left px-3 py-2 font-medium">Credits used</th>
                <th className="text-left px-3 py-2 font-medium">Last Copilot activity</th>
                <th className="text-left px-3 py-2 font-medium">Editor</th>
              </tr>
            </thead>
            <tbody>
              {power.users.map((u, i) => {
                const act = activityLabel(u)
                return (
                  <tr key={u.login}
                      className={`${i > 0 ? 'border-t border-gray-100 dark:border-gray-700' : ''} ${
                        u.downgrade_candidate ? 'bg-red-50/40' : ''}`}>
                    <td className="px-3 py-2 text-xs font-medium text-gray-800 dark:text-gray-200">
                      {u.login}
                      {u.downgrade_candidate && (
                        <span className="ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700">
                          review
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{u.organization || '—'}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 dark:text-gray-300">
                      {u.budget_amount}
                      {u.blocks_at_cap && <span className="ml-1 text-[10px] ds-u-color--muted">blocks at cap</span>}
                    </td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">
                      {u.credits_used ?? <span className="ds-u-color--muted">none yet</span>}
                    </td>
                    <td className={`px-3 py-2 text-xs ${act.tone}`}>{act.text}</td>
                    <td className="px-3 py-2 text-xs ds-u-color--muted">{u.editor || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {powerLoading && (
        <p className="mt-3 inline-flex items-center gap-1.5 text-xs ds-u-color--muted">
          <Loader2 size={12} className="animate-spin" /> Reading credit budgets…
        </p>
      )}
    </section>
  )
}
