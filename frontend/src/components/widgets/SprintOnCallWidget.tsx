import { useState, useEffect } from 'react'
import { TicketCheck, Lock, ExternalLink, Loader2, CheckCircle, AlertTriangle, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { useAuth } from '../../App'
import {
  getOnCallParams,
  createOnCallTickets,
  type OnCallParams,
  type OnCallTicket, apiErrorMessage } from '../../api/client'


export default function SprintOnCallWidget() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <ActionCard
        icon={<TicketCheck size={20} className="text-white" />}
        label="Sprint & On-Call"
        description="Create on-call support tickets for the sprint"
        color="bg-purple-500"
        onClick={() => setOpen(true)}
      />
      <OnCallModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function OnCallModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const isAuthorized = !!user?.jira_authorized
  const [params, setParams] = useState<OnCallParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [sprintId, setSprintId] = useState<number | 'projected' | ''>('')
  const [weeks, setWeeks] = useState([
    { week: 1, assignee: '' },
    { week: 2, assignee: '' },
    { week: 3, assignee: '' },
  ])
  const [result, setResult] = useState<OnCallTicket[] | null>(null)

  useEffect(() => {
    if (!open || !isAuthorized) return
    setLoading(true)
    setError('')
    setResult(null)
    setSprintId('')
    setWeeks([{ week: 1, assignee: '' }, { week: 2, assignee: '' }, { week: 3, assignee: '' }])
    getOnCallParams()
      .then(p => {
        setParams(p)
        // prefer future or projected sprint, fall back to active
        const target = p.sprints.find(s => s.state === 'future' || s.state === 'projected')
          ?? p.sprints.find(s => s.state === 'active')
          ?? p.sprints[0]
        if (target) setSprintId(target.id ?? 'projected')

        if (p.suggestions.length > 0) {
          setWeeks(p.suggestions.map(s => ({
            week:     s.week,
            assignee: s.jira_user || (p.team[s.week - 1]?.username ?? ''),
          })))
        } else if (p.team.length) {
          setWeeks([
            { week: 1, assignee: p.team[0]?.username ?? '' },
            { week: 2, assignee: p.team[1]?.username ?? p.team[0]?.username ?? '' },
            { week: 3, assignee: p.team[2]?.username ?? p.team[0]?.username ?? '' },
          ])
        }
      })
      .catch((e: any) => setError(apiErrorMessage(e, 'Failed to load params.')))
      .finally(() => setLoading(false))
  }, [open, isAuthorized])

  function handleClose() {
    setParams(null)
    setError('')
    setResult(null)
    setSprintId('')
    setWeeks([{ week: 1, assignee: '' }, { week: 2, assignee: '' }, { week: 3, assignee: '' }])
    onClose()
  }

  function setWeekAssignee(week: number, assignee: string) {
    setWeeks(prev => prev.map(w => w.week === week ? { ...w, assignee } : w))
  }

  // The selected sprint object
  const selectedSprint = params?.sprints.find(s =>
    sprintId === 'projected' ? s.state === 'projected' : s.id === Number(sprintId)
  )
  const isProjected = selectedSprint?.state === 'projected'

  async function handleCreate() {
    if (!params || !selectedSprint || weeks.some(w => !w.assignee)) return
    setError('')
    setCreating(true)
    try {
      const payload = isProjected
        ? {
            sprint_id:        null,
            new_sprint_name:  selectedSprint.name,
            new_sprint_start: selectedSprint.startDate,
            new_sprint_end:   selectedSprint.endDate,
            weeks,
          }
        : { sprint_id: selectedSprint.id as number, weeks }
      const res = await createOnCallTickets(payload)
      setResult(res.tickets)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to create tickets.'))
    } finally {
      setCreating(false)
    }
  }

  const memberName = (username: string) =>
    params?.team.find(m => m.username === username)?.name ?? username

  return (
    <Modal open={open} onClose={handleClose} title="On-Call Support Tickets">
      {!isAuthorized ? (
        <div className="text-center space-y-4 py-6">
          <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <Lock size={24} className="ds-u-color--muted" />
          </div>
          <div>
            <p className="font-semibold text-gray-800">Restricted Action</p>
            <p className="text-sm ds-u-color--muted mt-1">
              On-call ticket creation is restricted to authorized users.
            </p>
          </div>
          <button onClick={handleClose} className="btn-secondary">Close</button>
        </div>
      ) : result ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={18} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">3 on-call tickets created!</p>
              <p className="text-xs text-green-700 mt-0.5">Added to sprint with full description and acceptance criteria.</p>
            </div>
          </div>
          <div className="space-y-2">
            {result.map(t => (
              <a key={t.key} href={t.url} target="_blank" rel="noopener noreferrer"
                 className="flex items-center justify-between p-2.5 rounded-lg border border-gray-100 hover:bg-gray-50 group">
                <div>
                  <span className="text-xs font-mono font-medium text-cms-blue">{t.key}</span>
                  <span className="text-xs ds-u-color--muted ml-2">Week {t.week} → {t.assignee}</span>
                </div>
                <ExternalLink size={11} className="text-gray-300 group-hover:text-cms-blue" />
              </a>
            ))}
          </div>
          <button onClick={handleClose} className="btn-secondary w-full">Close</button>
        </div>
      ) : (
        <div className="space-y-4">
          {loading && (
            <div className="flex items-center gap-2 text-sm ds-u-color--muted py-4 justify-center">
              <Loader2 size={15} className="animate-spin" /> Loading…
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" /> {error}
            </div>
          )}
          {params && (
            <>
              {params.sprints.find(s => s.state === 'active') && (
                <div className="flex items-center gap-2 text-xs ds-u-color--muted bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
                  <span className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />
                  <span>Active sprint: <span className="font-medium text-gray-700">{params.sprints.find(s => s.state === 'active')!.name}</span></span>
                </div>
              )}
              {isProjected && (
                <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  <AlertTriangle size={13} className="flex-shrink-0 mt-0.5" />
                  <span>No future sprint exists yet. A new sprint <strong>{selectedSprint?.name}</strong> will be created in Jira.</span>
                </div>
              )}
              <div>
                <label className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide block mb-1.5">Create tickets in sprint</label>
                <div className="relative">
                  <select
                    className="input-field pr-8 appearance-none"
                    value={sprintId}
                    onChange={e => { const v = e.target.value; setSprintId(v === 'projected' ? 'projected' : Number(v)) }}
                  >
                    {params.sprints.map(s => (
                      <option key={s.id ?? 'projected'} value={s.id ?? 'projected'}>{s.name} ({s.state})</option>
                    ))}
                  </select>
                  <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide">On-call assignments</p>
                  {params.suggestions.length > 0 && (
                    <span className="text-xs text-purple-600 bg-purple-50 border border-purple-200 px-2 py-0.5 rounded-full font-medium">
                      Auto-filled from VictorOps
                    </span>
                  )}
                </div>
                <div className="space-y-2">
                  {weeks.map(w => (
                    <div key={w.week} className="flex items-center gap-3">
                      <span className="text-xs ds-u-color--muted w-14 flex-shrink-0">Week {w.week}</span>
                      <div className="relative flex-1">
                        <select
                          className="input-field pr-8 appearance-none text-sm"
                          value={w.assignee}
                          onChange={e => setWeekAssignee(w.week, e.target.value)}
                        >
                          {params.team.map(m => (
                            <option key={m.username} value={m.username}>{m.name}</option>
                          ))}
                        </select>
                        <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-gray-50 rounded-lg px-3 py-2.5 text-xs ds-u-color--muted space-y-0.5">
                {weeks.map(w => (
                  <p key={w.week}>
                    <span className="font-medium text-gray-700">Week {w.week}:</span>{' '}
                    On-Call Support Week {w.week} → {memberName(w.assignee)}
                  </p>
                ))}
              </div>

              <div className="flex gap-3">
                <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleCreate}
                  disabled={creating || !selectedSprint || weeks.some(w => !w.assignee)}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {creating && <Loader2 size={14} className="animate-spin" />}
                  {creating ? 'Creating…' : isProjected ? 'Create Sprint + Tickets' : 'Create 3 Tickets'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
