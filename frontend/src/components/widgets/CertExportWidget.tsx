import { useState, useEffect } from 'react'
import { ShieldCheck, Loader2, CheckCircle, AlertTriangle, ExternalLink, ChevronDown } from 'lucide-react'
import ActionCard from '../ui/ActionCard'
import Modal from '../ui/Modal'
import {
  getCertExportTargets,
  runCertExport,
  type CertExportTarget,
  type CertExportResult, apiErrorMessage } from '../../api/client'

export default function CertExportWidget({ tool, label }: { tool: 'jfrog' | 'cbj'; label: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <ActionCard
        icon={<ShieldCheck size={20} className="text-white" />}
        label={label}
        description="Export the wildcard cert to 1Password + open a PR"
        color="bg-emerald-600"
        onClick={() => setOpen(true)}
      />
      <CertExportModal tool={tool} open={open} onClose={() => setOpen(false)} />
    </>
  )
}

const ENV_LABELS: Record<string, string> = {
  dev: 'Dev', prod: 'Prod',
  'dev-east': 'Dev East', 'prod-east': 'Prod East',
  'gc-dev-west': 'GovCloud Dev West', 'gc-prod-west': 'GovCloud Prod West',
}

function CertExportModal({ tool, open, onClose }: { tool: string; open: boolean; onClose: () => void }) {
  const [targets, setTargets] = useState<CertExportTarget[]>([])
  const [env, setEnv] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<CertExportResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    getCertExportTargets()
      .then(ts => {
        setTargets(ts)
        // Default to the first env for this tool
        const first = ts.find(t => t.tool === tool)
        if (first) setEnv(prev => prev || first.env)
      })
      .catch(() => setTargets([]))
  }, [open, tool])

  function handleClose() {
    setEnv(''); setResult(null); setError(''); onClose()
  }

  const toolTargets = targets.filter(t => t.tool === tool)
  const current = toolTargets.find(t => t.env === env)
  const thisConfigured = current?.configured

  async function handleRun() {
    setError(''); setRunning(true)
    try {
      setResult(await runCertExport(tool, env))
    } catch (e: any) {
      setError(apiErrorMessage(e, 'Export failed.'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Export Wildcard Certificate">
      {result ? (
        <div className="space-y-4 py-2">
          {result.status === 'unchanged' ? (
            <>
              <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300">
                <CheckCircle size={18} className="ds-u-color--muted" /> <span className="font-semibold">No change</span>
              </div>
              <p className="text-sm text-gray-600">
                {result.message || 'Certificate unchanged since last export — nothing stored, no PR opened.'}
              </p>
              <p className="text-xs ds-u-color--muted"><code className="break-all">{result.cert_arn}</code></p>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-green-700">
                <CheckCircle size={18} /> <span className="font-semibold">Export complete</span>
              </div>
              <div className="text-sm space-y-1.5 text-gray-700 dark:text-gray-300">
                <p><span className="font-medium">Cert:</span> <code className="text-xs break-all">{result.cert_arn}</code></p>
                <p><span className="font-medium">1Password:</span> {result.op_items.join(', ')}</p>
                <div>
                  <span className="font-medium">Enc file{result.enc_paths.length > 1 ? 's' : ''}:</span>
                  {result.enc_paths.map(p => (
                    <div key={p}><code className="text-xs break-all">{p}</code></div>
                  ))}
                </div>
              </div>
              {result.pr_url && (
                <a href={result.pr_url} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1.5 text-sm font-medium text-cms-blue hover:underline">
                  Review the PR <ExternalLink size={13} />
                </a>
              )}
            </>
          )}
          <div className="pt-1">
            <button onClick={handleClose} className="btn-primary w-full">Done</button>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 text-xs text-blue-800">
            Exports the shared <code>*.cloud.cms.gov</code> ACM cert for this environment, stores the cert, chain, and passphrase-free TLS key in 1Password, then opens a PR with the SOPS-encrypted secret. Merge the PR and apply to the cluster.
          </div>

          <div>
            <label className="label">Environment</label>
            <div className="relative">
              <select className="input-field pr-8 appearance-none" value={env} onChange={e => { setEnv(e.target.value); setResult(null) }}>
                {toolTargets.map(t => (
                  <option key={t.env} value={t.env}>{ENV_LABELS[t.env] ?? t.env}{t.configured ? '' : ' (not ready)'}</option>
                ))}
              </select>
              <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 ds-u-color--muted pointer-events-none" />
            </div>
          </div>

          {thisConfigured === false && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2 text-xs">
              <AlertTriangle size={14} className="flex-shrink-0 mt-0.5" />
              <span>{tool.toUpperCase()} {ENV_LABELS[env] ?? env} isn&apos;t ready yet{current?.reason ? `: ${current.reason}` : ''}. This target is disabled until then.</span>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-3 py-2 text-sm">
              <AlertTriangle size={14} /> {error}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button onClick={handleClose} className="btn-secondary flex-1">Cancel</button>
            <button onClick={handleRun} disabled={running || thisConfigured === false}
                    className="btn-primary flex-1 flex items-center justify-center gap-2">
              {running && <Loader2 size={15} className="animate-spin" />}
              {running ? 'Exporting…' : `Export ${ENV_LABELS[env] ?? env}`}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
