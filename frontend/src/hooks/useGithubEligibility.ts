import { useEffect, useState } from 'react'
import { getAccessibleOrgs, type OrgInviteEligibility } from '../api/client'

export function useGithubEligibility(checkEligibility: () => Promise<OrgInviteEligibility>, withOrgs = false) {
  const [eligibility, setEligibility] = useState<OrgInviteEligibility | null>(null)
  const [checking, setChecking] = useState(true)
  const [orgs, setOrgs] = useState<string[]>([])
  const [org, setOrg] = useState('')

  useEffect(() => {
    checkEligibility()
      .then(setEligibility)
      .catch(() => setEligibility({ can_send: false, login: null }))
      .finally(() => setChecking(false))
    if (withOrgs) {
      getAccessibleOrgs()
        .then(a => { setOrgs(a.orgs); setOrg(a.default) })
        .catch(() => {})
    }
    // Runs once on mount; `checkEligibility` is always a stable module-level function reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { eligibility, checking, orgs, org, setOrg }
}
