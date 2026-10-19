import { useState, useEffect, useCallback } from 'react'
import {
  ClipboardCheck, ExternalLink, Loader2, XCircle, CheckCircle, AlertCircle,
  Zap, RefreshCw, Ticket, CheckSquare,
} from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getOEReadinessPreview, applyOEReadiness, closeOECcoe,
  type OEPreview, type OEPagePlan, type OESection, type OESreTicket,
  type OEApplyResultRow, type OECloseCcoeResult,
  apiErrorMessage,
} from '../../api/client'

const KIND_LABEL: Record<string, string> = {
  cbj: 'CloudBees / Jenkins',
  jfrog_sonar: 'JFrog / SonarQube',
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  auto: { label: 'Auto', cls: 'bg-green-100 text-green-700 border-green-200' },
  carry: { label: 'Verify', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  manual: { label: 'You update', cls: 'bg-gray-100 ds-u-color--muted border-gray-200' },
}

export default function OEReadinessWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<ClipboardCheck size={20} className="text-white" />}
        label="OE Readiness"
        description="Auto-fill the Open Enrollment DevOps readiness pages"
        color="bg-teal-600"
        onClick={() => setOpen(true)}
      />
      <OEReadinessModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function OEReadinessModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const defaultYear = new Date().getFullYear() + 1
  const [year, setYear] = useState(defaultYear)
  const [preview, setPreview] = useState<OEPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [overwrite, setOverwrite] = useState(false)
  const [applying, setApplying] = useState(false)
  const [rows, setRows] = useState<OEApplyResultRow[] | null>(null)
  const [sre, setSre] = useState<OESreTicket[] | null>(null)
  const [closing, setClosing] = useState<string | null>(null)
  const [closeResult, setCloseResult] = useState<Record<string, OECloseCcoeResult>>({})

  const load = useCallback((yr: number) => {
    setLoading(true); setError(''); setPreview(null); setRows(null); setSre(null); setCloseResult({})
    getOEReadinessPreview(yr)
      .then(data => {
        setPreview(data)
        // Default selection: every auto+carry section that isn't already filled.
        const sel: Record<string, Set<string>> = {}
        for (const p of data.pages) {
          if (!p.found) continue
          sel[p.kind] = new Set(
            p.sections
              .filter(s => s.status !== 'manual' && !s.already_filled)
              .map(s => s.key),
          )
        }
        setSelected(sel)
      })
      .catch(e => setError(apiErrorMessage(e, 'Could not load OE readiness pages.')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { if (open) load(year) }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(kind: string, key: string) {
    setSelected(prev => {
      const next = { ...prev }
      const set = new Set(next[kind] ?? [])
      set.has(key) ? set.delete(key) : set.add(key)
      next[kind] = set
      return next
    })
  }

  async function handleApply() {
    setApplying(true); setError('')
    try {
      const selections: Record<string, string[]> = {}
      for (const [kind, set] of Object.entries(selected)) selections[kind] = [...set]
      const res = await applyOEReadiness(year, selections, overwrite)
      setRows(res.results)
      setSre(res.sre)
      load(year) // refresh "already filled" state
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to update pages.'))
    } finally {
      setApplying(false)
    }
  }

  async function handleCloseCcoe(kind: string) {
    setClosing(kind); setError('')
    try {
      const res = await closeOECcoe(year, kind)
      setCloseResult(prev => ({ ...prev, [kind]: res }))
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Failed to close CCOE ticket.'))
    } finally {
      setClosing(null)
    }
  }

  function handleClose() {
    setPreview(null); setRows(null); setSre(null); setCloseResult({}); setError(''); onClose()
  }

  const totalSelected = Object.values(selected).reduce((n, s) => n + s.size, 0)

  return (
    <Modal open={open} onClose={handleClose} title="Open Enrollment DevOps Readiness">
      <div className="space-y-4">
        {/* Year selector */}
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-gray-700">OE Year</label>
          <select
            value={year}
            onChange={e => { const y = Number(e.target.value); setYear(y); load(y) }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm"
          >
            {[defaultYear - 1, defaultYear, defaultYear + 1].map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <button
            onClick={() => load(year)}
            className="ml-auto inline-flex items-center gap-1 text-xs ds-u-color--muted hover:text-gray-700"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>

        {loading && (
          <div className="flex items-center gap-2 py-3 text-sm ds-u-color--muted">
            <Loader2 size={15} className="animate-spin" /> Finding pages and gathering live data…
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
            <XCircle size={14} className="flex-shrink-0" /> {error}
          </div>
        )}

        {preview && preview.pages.map(p => {
          const row = rows?.find(r => r.kind === p.kind) ?? null
          return (
            <PagePanel
              key={p.kind}
              plan={p}
              selected={selected[p.kind] ?? new Set()}
              overwrite={overwrite}
              justWritten={row?.written ?? null}
              ccoe={row?.ccoe ?? null}
              closing={closing === p.kind}
              closeResult={closeResult[p.kind] ?? null}
              onCloseCcoe={() => handleCloseCcoe(p.kind)}
              onToggle={key => toggle(p.kind, key)}
            />
          )
        })}

        {preview && preview.pages.some(p => p.found) && (
          <>
            <label className="flex items-center gap-2 text-xs text-gray-600">
              <input type="checkbox" checked={overwrite} onChange={e => setOverwrite(e.target.checked)} />
              Overwrite sections that already have content (default: only fill empty ones)
            </label>

            <div className="flex gap-3 pt-1">
              <button onClick={handleClose} className="btn-secondary flex-1">Close</button>
              <button
                onClick={handleApply}
                disabled={applying || totalSelected === 0}
                className="btn-primary flex-1 flex items-center justify-center gap-2 bg-teal-600 hover:bg-teal-700 disabled:opacity-50"
              >
                {applying ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                Fill {totalSelected} section{totalSelected === 1 ? '' : 's'}
              </button>
            </div>
            <p className="text-[11px] ds-u-color--muted -mt-1">
              Fill also creates one SRE readiness ticket (CLDSRE) per tool and links
              it on the page. Re-running is safe — existing tickets are reused.
            </p>

            {/* SRE tickets created/reused by Fill */}
            {sre && sre.length > 0 && (
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-3 space-y-2">
                <p className="text-xs font-semibold text-gray-600 flex items-center gap-1.5">
                  <Ticket size={12} /> SRE readiness tickets (CLDSRE)
                </p>
                <ul className="space-y-1">
                  {sre.map(t => (
                    <li key={t.tool} className="text-xs flex items-center gap-2">
                      <span className="font-medium text-gray-700 w-20">{t.tool}</span>
                      {t.key ? (
                        <a href={t.url!} target="_blank" rel="noopener noreferrer"
                           className="inline-flex items-center gap-1 text-cms-blue hover:underline">
                          {t.key} <ExternalLink size={10} />
                          {t.existing && <span className="ds-u-color--muted">(reused)</span>}
                        </a>
                      ) : (
                        <span className="text-red-600">{t.error || 'failed'}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}

function PagePanel({
  plan, selected, overwrite, justWritten, ccoe, closing, closeResult, onCloseCcoe, onToggle,
}: {
  plan: OEPagePlan
  selected: Set<string>
  overwrite: boolean
  justWritten: string[] | null
  ccoe: OEApplyResultRow['ccoe']
  closing: boolean
  closeResult: OECloseCcoeResult | null
  onCloseCcoe: () => void
  onToggle: (key: string) => void
}) {
  if (!plan.found) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 flex items-center gap-2">
        <AlertCircle size={15} className="flex-shrink-0" />
        No <strong>{KIND_LABEL[plan.kind]}</strong> readiness page found for this year.
      </div>
    )
  }
  const auto = plan.sections.filter(s => s.status !== 'manual')
  const manual = plan.sections.filter(s => s.status === 'manual')

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-3 py-2 flex items-center justify-between border-b border-gray-100">
        <div>
          <p className="text-sm font-semibold text-gray-800">{KIND_LABEL[plan.kind]}</p>
          {plan.page && (
            <a href={plan.page.url} target="_blank" rel="noopener noreferrer"
               className="text-xs text-cms-blue hover:underline inline-flex items-center gap-1">
              {plan.page.title} <ExternalLink size={10} />
            </a>
          )}
        </div>
        {justWritten && (
          <span className="inline-flex items-center gap-1 text-xs text-green-700">
            <CheckCircle size={13} /> {justWritten.length} written
          </span>
        )}
      </div>

      <ul className="divide-y divide-gray-50">
        {auto.map(s => (
          <SectionRow
            key={s.key} s={s}
            checked={selected.has(s.key)}
            disabled={s.already_filled && !overwrite}
            onToggle={() => onToggle(s.key)}
          />
        ))}
      </ul>

      {manual.length > 0 && (
        <div className="px-3 py-2 bg-gray-50/60 border-t border-gray-100">
          <p className="text-[11px] uppercase tracking-wide ds-u-color--muted font-semibold mb-1">
            Needs your input
          </p>
          <div className="flex flex-wrap gap-1.5">
            {manual.map(s => (
              <span key={s.key} className="text-[11px] px-2 py-0.5 rounded border border-gray-200 bg-white ds-u-color--muted">
                {s.label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* CCOE ticket — shown after Fill; close it once every section is verified */}
      {ccoe && (
        <div className="px-3 py-2.5 border-t border-gray-100 flex items-center justify-between gap-2">
          <div className="text-xs text-gray-600">
            CCOE ticket:{' '}
            <a href={ccoe.url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-cms-blue hover:underline font-medium">
              {ccoe.key} <ExternalLink size={10} />
            </a>
            {ccoe.commented && <span className="ds-u-color--muted"> · comment added</span>}
          </div>
          {closeResult?.ok ? (
            <span className="inline-flex items-center gap-1 text-xs text-green-700">
              <CheckCircle size={13} /> Closed ({closeResult.status})
            </span>
          ) : (
            <button
              onClick={onCloseCcoe}
              disabled={closing}
              title="Close only after verifying every section on the page"
              className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded border border-teal-200 text-teal-700 hover:bg-teal-50 disabled:opacity-50"
            >
              {closing ? <Loader2 size={12} className="animate-spin" /> : <CheckSquare size={12} />}
              Close ticket (verified)
            </button>
          )}
        </div>
      )}
      {closeResult && !closeResult.ok && closeResult.error && (
        <div className="px-3 py-1.5 text-[11px] text-red-600 border-t border-gray-100">{closeResult.error}</div>
      )}
    </div>
  )
}

function SectionRow({
  s, checked, disabled, onToggle,
}: {
  s: OESection
  checked: boolean
  disabled: boolean
  onToggle: () => void
}) {
  const meta = STATUS_META[s.status]
  return (
    <li className="px-3 py-2 flex items-start gap-2.5">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked && !disabled}
        disabled={disabled}
        onChange={onToggle}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-800">{s.label}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${meta.cls}`}>{meta.label}</span>
          {s.already_filled && (
            <span className="text-[10px] ds-u-color--muted">already filled{disabled ? ' — skipped' : ' — overwrite'}</span>
          )}
        </div>
        {s.text && (
          <p className="text-[11px] ds-u-color--muted mt-0.5 whitespace-pre-line line-clamp-3">{s.text}</p>
        )}
      </div>
    </li>
  )
}
