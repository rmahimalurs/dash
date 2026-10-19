import { useState, useEffect } from 'react'
import { Wrench, Lock, ExternalLink, Loader2, CheckCircle, AlertTriangle, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import { useAuth } from '../../App'
import {
  getMaintPrepParams,
  createMaintPrepTickets,
  type MaintPrepParams,
  type MaintPrepTicket, apiErrorMessage } from '../../api/client'


const SERVICE_LABELS: Record<string, { label: string; sp: number }> = {
  jfrog:     { label: 'JFrog',     sp: 3 },
  cloudbees: { label: 'CloudBees', sp: 5 },
  sonarqube: { label: 'SonarQube', sp: 2 },
}

export default function MaintenancePrepWidget() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <ActionCard
        icon={<Wrench size={20} className="text-white" />}
        label="Maintenance Prep"
        description="Create monthly prep tickets with auto-rotation"
        color="bg-cms-blue"
        onClick={() => setOpen(true)}
      />
      <MaintPrepModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function MaintPrepModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user } = useAuth()
  const isAuthorized = !!user?.jira_authorized
  const [params, setParams] = useState<MaintPrepParams | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  // Selection value: String(sprint.id) for real sprints, 'new' for the projected sprint.
  const [selected, setSelected] = useState<string>('')
  const [autoDetected, setAutoDetected] = useState(false)
  const [result, setResult] = useState<MaintPrepTicket[] | null>(null)

  useEffect(() => {
    if (!open || !isAuthorized) return
    setLoading(true)
    getMaintPrepParams()
      .then(p => {
        setParams(p)
        // Prefer the sprint overlapping the maintenance window; else offer the
        // projected sprint (create-new); else fall back to the first real sprint.
        if (p.recommended_sprint_id != null) {
          setSelected(String(p.recommended_sprint_id))
          setAutoDetected(true)
        } else if (p.projected_sprint) {
          setSelected('new')
          setAutoDetected(false)
        } else {
          const first = p.sprints.find(s => s.id != null)
          if (first?.id != null) setSelected(String(first.id))
        }
      })
      .catch((e: any) => setError(apiErrorMessage(e, 'Failed to load params.')))
      .finally(() => setLoading(false))
  }, [open, isAuthorized])

  function handleClose() {
    setParams(null)
    setError('')
    setResult(null)
    setSelected('')
    setAutoDetected(false)
    onClose()
  }

  const creatingNewSprint = selected === 'new'

  async function handleCreate() {
    if (!params || !selected) return
    if (creatingNewSprint && !params.projected_sprint) return
    setError('')
    setCreating(true)
    try {
      const proj = params.projected_sprint
      const res = await createMaintPrepTickets({
        sprint_id: creatingNewSprint ? null : Number(selected),
        ...(creatingNewSprint && proj
          ? {
              new_sprint_name:  proj.name,
              new_sprint_start: proj.startDate,
              new_sprint_end:   proj.endDate,
            }
          : {}),
        maint_date_str: params.maint_date_str,
        jfrog_assignee:     params.rotation.jfrog.username,
        cloudbees_assignee: params.rotation.cloudbees.username,
        sonarqube_assignee: params.rotation.sonarqube.username,
      })
      setResult(res.tickets)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to create tickets.'))
    } finally {
      setCreating(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Maintenance Prep Tickets">
      {!isAuthorized ? (
        <div className="text-center space-y-4 py-6">
          <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto">
            <Lock size={24} className="ds-u-color--muted" />
          </div>
          <div>
            <p className="font-semibold text-gray-800">Restricted Action</p>
            <p className="text-sm ds-u-color--muted mt-1">
              Maintenance prep ticket creation is restricted to Patrick Hendren.
            </p>
          </div>
          <button onClick={handleClose} className="btn-secondary">Close</button>
        </div>
      ) : result ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 bg-green-50 border border-green-200 rounded-lg p-4">
            <CheckCircle size={18} className="text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold text-green-800">3 tickets created!</p>
              <p className="text-xs text-green-700 mt-0.5">Added to sprint and linked to DMSC-399.</p>
            </div>
          </div>
          <div className="space-y-2">
            {result.map(t => (
              <a key={t.key} href={t.url} target="_blank" rel="noopener noreferrer"
                 className="flex items-center justify-between p-2.5 rounded-lg border border-gray-100 hover:bg-gray-50 group">
                <div>
                  <span className="text-xs font-mono font-medium text-cms-blue">{t.key}</span>
                  <span className="text-xs ds-u-color--muted ml-2">{SERVICE_LABELS[t.service]?.label} → {t.assignee}</span>
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
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3">
                <p className="text-xs text-blue-700 font-medium">Next maintenance window</p>
                <p className="text-sm font-semibold text-blue-900 mt-0.5">{params.maint_date_str}</p>
              </div>

              <div>
                <p className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide mb-2">Assignee rotation</p>
                <div className="rounded-lg border border-gray-100 overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-50 ds-u-color--muted">
                        <th className="text-left px-3 py-2 font-medium">Service</th>
                        <th className="text-left px-3 py-2 font-medium">Assignee</th>
                        <th className="text-right px-3 py-2 font-medium">SP</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(['jfrog', 'cloudbees', 'sonarqube'] as const).map(svc => (
                        <tr key={svc} className="border-t border-gray-100">
                          <td className="px-3 py-2 font-medium text-gray-700">{SERVICE_LABELS[svc].label}</td>
                          <td className="px-3 py-2 text-gray-600">{params.rotation[svc].name}</td>
                          <td className="px-3 py-2 text-right ds-u-color--muted">{SERVICE_LABELS[svc].sp}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <label className="text-xs font-semibold ds-u-color--muted uppercase tracking-wide">Sprint</label>
                  {autoDetected && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-green-700 bg-green-50 border border-green-200 rounded px-1.5 py-0.5">
                      <CheckCircle size={10} /> Detected for window
                    </span>
                  )}
                </div>
                <div className="relative">
                  <select
                    className="input-field pr-8 appearance-none"
                    value={selected}
                    onChange={e => { setSelected(e.target.value); setAutoDetected(false) }}
                  >
                    {params.sprints.map(s => (
                      <option key={s.id ?? 'new'} value={s.id == null ? 'new' : String(s.id)}>
                        {s.id == null ? `${s.name} — create new sprint` : `${s.name} (${s.state})`}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
                </div>
                {creatingNewSprint && params.projected_sprint && (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2.5 py-1.5 mt-1.5">
                    No existing sprint covers this maintenance window. A new sprint{' '}
                    <span className="font-semibold">{params.projected_sprint.name}</span> will be created.
                  </p>
                )}
              </div>

              <div className="flex gap-3">
                <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
                <button
                  onClick={handleCreate}
                  disabled={creating || !selected || (creatingNewSprint && !params.projected_sprint)}
                  className="btn-primary flex-1 flex items-center justify-center gap-2"
                >
                  {creating && <Loader2 size={14} className="animate-spin" />}
                  {creating ? 'Creating…' : creatingNewSprint ? 'Create Sprint + 3 Tickets' : 'Create 3 Tickets'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
