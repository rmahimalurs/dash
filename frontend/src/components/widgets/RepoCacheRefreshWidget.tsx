import { useState, useEffect, useMemo } from 'react'
import { RefreshCw, Loader2, CheckCircle, AlertTriangle, XCircle, X } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  listRefreshRepos,
  refreshRepos,
  type RefreshRepo,
  type RepoRefreshResult, apiErrorMessage } from '../../api/client'

const TYPE_BADGE: Record<string, string> = {
  REMOTE: 'bg-blue-100 text-blue-700',
  LOCAL: 'bg-green-100 text-green-700',
  VIRTUAL: 'bg-purple-100 text-purple-700',
}

export default function RepoCacheRefreshWidget() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<RefreshCw size={20} className="text-white" />}
        label="Refresh Repo Cache / Reindex"
        description="Zap remote proxy caches or recalculate index (prod)"
        color="bg-teal-600"
        onClick={() => setOpen(true)}
      />
      <RepoRefreshModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}

function RepoRefreshModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [repos, setRepos] = useState<RefreshRepo[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pkg, setPkg] = useState('')
  const [confirmWipe, setConfirmWipe] = useState(false)
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<RepoRefreshResult[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setLoadError('')
    listRefreshRepos()
      .then(setRepos)
      .catch((e: any) => setLoadError(apiErrorMessage(e, 'Failed to load repositories.')))
      .finally(() => setLoading(false))
  }, [open])

  function handleClose() {
    setSearch('')
    setSelected(new Set())
    setPkg('')
    setConfirmWipe(false)
    setResults(null)
    setError('')
    onClose()
  }

  const byKey = useMemo(() => new Map(repos.map(r => [r.key, r])), [repos])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return repos.slice(0, 40)
    return repos
      .filter(r => r.key.toLowerCase().includes(q) || r.package_type.toLowerCase().includes(q))
      .slice(0, 40)
  }, [repos, search])

  const selectedRepos = useMemo(
    () => [...selected].map(k => byKey.get(k)).filter(Boolean) as RefreshRepo[],
    [selected, byKey],
  )
  const anyRemote = selectedRepos.some(r => r.type === 'REMOTE')
  const fullWipe = anyRemote && !pkg.trim()

  function toggle(key: string) {
    setSelected(s => {
      const n = new Set(s)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
    setResults(null)
  }

  async function handleRun() {
    setError('')
    setRunning(true)
    try {
      const r = await refreshRepos([...selected], pkg.trim() || undefined)
      setResults(r)
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Refresh failed.'))
    } finally {
      setRunning(false)
    }
  }

  const canRun =
    selected.size > 0 && !running && (!fullWipe || confirmWipe)

  return (
    <Modal open={open} onClose={handleClose} title="Refresh Repository Cache / Reindex" wide>
      {results ? (
        <div className="space-y-4 py-1">
          <div className="rounded-lg border border-gray-100 overflow-hidden text-sm">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 text-xs ds-u-color--muted">
                  <th className="text-left px-3 py-2 font-medium">Repository</th>
                  <th className="text-left px-3 py-2 font-medium">Type</th>
                  <th className="text-left px-3 py-2 font-medium">Action</th>
                  <th className="text-left px-3 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={r.repo} className={i > 0 ? 'border-t border-gray-100' : ''}>
                    <td className="px-3 py-2 font-mono text-xs">{r.repo}</td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${TYPE_BADGE[r.type] || 'bg-gray-100 text-gray-600'}`}>{r.type}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600">{r.action}</td>
                    <td className="px-3 py-2 text-xs">
                      <span className="inline-flex items-start gap-1.5">
                        {r.ok ? <CheckCircle size={13} className="text-green-600 flex-shrink-0 mt-0.5" /> : <XCircle size={13} className="text-red-600 flex-shrink-0 mt-0.5" />}
                        <span className={r.ok ? 'text-gray-700' : 'text-red-700'}>{r.detail}</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setResults(null)} className="btn-secondary flex-1">Back</button>
            <button onClick={handleClose} className="btn-primary flex-1">Done</button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 text-xs text-blue-800">
            <span className="font-semibold">Prod Artifactory.</span> Remote (proxy) repos are refreshed by clearing cached content so new upstream packages are fetched on the next request. Local/virtual repos have their index recalculated.
          </div>

          {loadError && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} /> {loadError}
            </div>
          )}

          {/* Selected chips */}
          {selectedRepos.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selectedRepos.map(r => (
                <span key={r.key} className="inline-flex items-center gap-1 bg-gray-100 dark:bg-gray-700 rounded-full pl-2 pr-1 py-0.5 text-xs">
                  <span className="font-mono">{r.key}</span>
                  <span className={`text-[9px] font-semibold px-1 rounded ${TYPE_BADGE[r.type] || 'bg-gray-200 text-gray-600'}`}>{r.type[0]}</span>
                  <button onClick={() => toggle(r.key)} className="ds-u-color--muted hover:text-gray-700"><X size={11} /></button>
                </span>
              ))}
            </div>
          )}

          {/* Search + list */}
          <div>
            <label className="label">Repositories {selected.size > 0 && <span className="ds-u-color--muted">({selected.size} selected)</span>}</label>
            <input
              className="input-field"
              placeholder={loading ? 'Loading repositories…' : 'Search by name or package type…'}
              value={search}
              onChange={e => setSearch(e.target.value)}
              disabled={loading}
            />
            <div className="mt-2 max-h-52 overflow-y-auto rounded-lg border border-gray-100 divide-y divide-gray-50">
              {loading ? (
                <div className="flex items-center gap-2 px-3 py-3 text-xs ds-u-color--muted"><Loader2 size={12} className="animate-spin" /> Loading…</div>
              ) : filtered.length === 0 ? (
                <div className="px-3 py-3 text-xs ds-u-color--muted">No matches.</div>
              ) : (
                filtered.map(r => (
                  <label key={r.key} className="flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer hover:bg-gray-50">
                    <input type="checkbox" checked={selected.has(r.key)} onChange={() => toggle(r.key)} className="rounded border-gray-300" />
                    <span className="font-mono flex-1 truncate">{r.key}</span>
                    <span className="ds-u-color--muted">{r.package_type}</span>
                    <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded ${TYPE_BADGE[r.type] || 'bg-gray-100 text-gray-600'}`}>{r.type}</span>
                  </label>
                ))
              )}
            </div>
            {!loading && (search.trim() ? repos.filter(r => r.key.toLowerCase().includes(search.trim().toLowerCase()) || r.package_type.toLowerCase().includes(search.trim().toLowerCase())).length > 40 : repos.length > 40) && (
              <p className="text-[11px] ds-u-color--muted mt-1">Showing first 40. Refine the search to narrow the list.</p>
            )}
          </div>

          {/* Optional package/path */}
          <div>
            <label className="label">Package / path <span className="ds-u-color--muted">(optional, remote repos only)</span></label>
            <input
              className="input-field font-mono"
              placeholder="e.g. amazon/aws-cli/2.15.30  or  xml2js"
              value={pkg}
              onChange={e => { setPkg(e.target.value); setResults(null) }}
            />
            <p className="text-[11px] ds-u-color--muted mt-1">Targets a single cached package/path on remote repos. Leave blank to clear the whole repo cache.</p>
          </div>

          {/* Full-wipe warning + confirm */}
          {fullWipe && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 text-xs text-amber-800 space-y-2">
              <div className="flex items-start gap-2">
                <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
                <span>No package specified, so the <strong>entire cache</strong> will be cleared for the selected remote repo(s). This forces a re-download from upstream and can cause brief 404s while artifacts refetch.</span>
              </div>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input type="checkbox" checked={confirmWipe} onChange={e => setConfirmWipe(e.target.checked)} className="rounded border-amber-300" />
                I understand this clears the full cache for the selected remote repos.
              </label>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} /> {error}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button onClick={handleRun} disabled={!canRun} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {running && <Loader2 size={15} className="animate-spin" />}
              {running ? 'Refreshing…' : `Refresh ${selected.size || ''} repo${selected.size === 1 ? '' : 's'}`.trim()}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
