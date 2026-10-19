import { useEffect, useRef, useState } from 'react'
import { getBulkJob, type BulkJob } from '../api/client'

const POLL_MS = 1000

function placeholderJob<TResult, TExtra>(jobId: string): BulkJob<TResult, TExtra> {
  return {
    id: jobId, kind: '', status: 'running', total: 0, done: 0,
    current: null, results: [], extra: {} as TExtra, error: null,
  }
}

export function useBulkJob<TResult = unknown, TExtra = Record<string, unknown>>() {
  const [job, setJob] = useState<BulkJob<TResult, TExtra> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Bumped on every start/stop/reset so an in-flight request from a prior
  // generation can tell it's stale once it resolves, and skip updating
  // state or scheduling another poll instead of resurrecting polling after
  // the modal hosting this hook has already unmounted it.
  const generation = useRef(0)

  function stop() {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    generation.current += 1
  }

  useEffect(() => stop, [])

  function poll(jobId: string, gen: number) {
    getBulkJob<TResult, TExtra>(jobId)
      .then(j => {
        if (gen !== generation.current) return
        setJob(j)
        if (j.status === 'running') timer.current = setTimeout(() => poll(jobId, gen), POLL_MS)
      })
      .catch((err: unknown) => {
        if (gen !== generation.current) return
        const status = (err as { response?: { status?: number } })?.response?.status
        if (status === 404) {
          // The backend has no record of this job -- a restart evicted its
          // in-memory state, or it finished long enough ago to be cleaned
          // up. Retrying forever would leave the form disabled with no
          // explanation; surface it through the same "error" rendering
          // every widget already has; no change needed there.
          setJob({
            id: jobId, kind: '', status: 'error', total: 0, done: 0, current: null,
            results: [], extra: {} as TExtra,
            error: "This job is no longer available (the backend may have restarted, or too much "
              + "time has passed since it finished). If you're not sure whether it completed, check "
              + "the audit log or the Slack report before retrying.",
          })
          return
        }
        timer.current = setTimeout(() => poll(jobId, gen), POLL_MS * 2)
      })
  }

  function start(jobId: string) {
    stop()
    const gen = generation.current
    // A placeholder with status "running" from the moment the job id
    // arrives, not null -- every widget derives its submit-button guard
    // from job?.status, and leaving it null until the first poll resolves
    // left a window where that guard reads "not running" and a second
    // submission could start a duplicate batch.
    setJob(placeholderJob(jobId))
    poll(jobId, gen)
  }

  function reset() {
    stop()
    setJob(null)
  }

  return { job, start, reset }
}
