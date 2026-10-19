import { useState } from 'react'
import CbjResourceAnalysisWidget from '../components/widgets/CbjResourceAnalysisWidget'
import CbjPodTemplateConfigWidget from '../components/widgets/CbjPodTemplateConfigWidget'
import { CbjAnalysisTarget, CbjEnv } from '../api/client'

const ENVS: { key: CbjEnv; label: string }[] = [
  { key: 'prod-east', label: 'Prod East' },
  { key: 'gc-prod-west', label: 'GovCloud Prod (West)' },
]

const TARGETS: { key: CbjAnalysisTarget | 'podtemplate-config'; label: string }[] = [
  { key: 'agents', label: 'Build/Agent Containers' },
  { key: 'controllers', label: 'Controllers' },
  { key: 'podtemplate-config', label: 'podTemplate Config' },
]

export default function Monitoring() {
  const [env, setEnv] = useState<CbjEnv>('prod-east')
  const [target, setTarget] = useState<CbjAnalysisTarget | 'podtemplate-config'>('agents')

  const envLabel = ENVS.find((e) => e.key === env)?.label ?? env

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100">CBJ Monitoring</h2>
            <p className="text-sm ds-u-color--muted mt-0.5 max-w-3xl">
              What each CloudBees Jenkins container reserved vs. what it actually used at peak, so
              over-provisioned ADO teams can be asked to right-size. Pick an environment below —
              Prod East and GovCloud Prod are kept separate (different AWS accounts, never combined).
            </p>
          </div>
          {target !== 'podtemplate-config' && (
            <label className="flex items-center gap-2 text-sm">
              <span className="ds-u-color--muted">Environment</span>
              <select
                value={env}
                onChange={(e) => setEnv(e.target.value as CbjEnv)}
                className="border border-gray-300 dark:border-gray-700 rounded-md px-3 py-1.5 text-sm bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-cms-blue"
              >
                {ENVS.map((e) => (
                  <option key={e.key} value={e.key}>{e.label}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div className="flex gap-1 mb-6 border-b border-gray-200 dark:border-gray-800">
          {TARGETS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTarget(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                target === t.key
                  ? 'border-cms-blue text-cms-blue'
                  : 'border-transparent ds-u-color--muted hover:text-gray-700 dark:hover:text-gray-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {target === 'podtemplate-config' ? (
          <CbjPodTemplateConfigWidget />
        ) : (
          <CbjResourceAnalysisWidget
            key={`${env}-${target}`}
            env={env}
            target={target}
            title={`CBJ ${target === 'agents' ? 'Build/Agent' : 'Controller'} Analysis — ${envLabel}`}
          />
        )}
      </section>
    </div>
  )
}
