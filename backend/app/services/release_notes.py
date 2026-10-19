"""What's-new release notes and per-user acknowledgment.

The notes ship with the backend image, so the version a user is told about is
always the version actually serving them. Acknowledgment is stored per user in
their profile as the version they dismissed, which means a new release makes the
popup reappear on its own with no extra bookkeeping.

To add a release: put it at the top of RELEASES and bump APP_VERSION to match.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Newest first. `version` must match the deployed image tag so the popup and the
# running build can never disagree.
RELEASES: list[dict] = [
    {
        "version": "3.20.0",
        "date": "2026-10-19",
        "title": "A refreshed look for the dark theme",
        "highlights": [
            {
                "title": "Deeper blue shell, and cards that read as cards",
                "body": "The dark theme moves from blue-gray to the saturated blue of the "
                        "approved maintenance mockup, with the header and cards picking up "
                        "the same gradient so panels separate from the background instead of "
                        "sitting flat against it.",
            },
            {
                "title": "The dropdowns are solid again",
                "body": "A select menu was drawing over the page with a see-through panel, so "
                        "whatever sat underneath showed through the options.",
            },
        ],
    },
    {
        "version": "3.19.0",
        "date": "2026-10-18",
        "title": "The JFrog entitlement token refreshes itself on one click",
        "highlights": [
            {
                "title": "Nothing to paste",
                "body": "The JFrog Entitlement Credential tile asked for a username and "
                        "password that someone had to regenerate on the JFrog user page "
                        "first. JFrog will mint a replacement from a refresh token, and that "
                        "refresh is authenticated with the token being replaced, which is "
                        "already in the pull secret. Request and rotate does the whole thing, "
                        "verifies the result against the registry and commits the three "
                        "secrets as before. The manual fields stay for when JFrog refuses.",
            },
            {
                "title": "A reminder in the bell before it expires",
                "body": "The refresh is one click, but nothing used to say it was due. The "
                        "bell now warns 14 days out and escalates at 5, naming the click. It "
                        "stays quiet above 14 days on purpose: the token lives about a month, "
                        "so an earlier warning would sit there for most of its life and stop "
                        "reading as a reminder. The token in force expires 2026-11-17.",
            },
            {
                "title": "The commands to put it live",
                "body": "This tile commits and does not apply, which has quietly left "
                        "credentials looking done while the clusters still held the old one. "
                        "The result now lists the sops and kubectl commands for the "
                        "environment it just wrote, including the Artifactory and Xray "
                        "restarts.",
            },
            {
                "title": "The refresh token lives in one place",
                "body": "JFrog retires a refresh token when it is spent and issues a "
                        "replacement, so a copy in a Kubernetes secret would be stale the "
                        "moment it was used. It is read from the JFrog 1Password vault at the "
                        "point of use and the replacement is written straight back, so there "
                        "is nothing to commit or apply to keep the tile working.",
            },
        ],
    },
    {
        "version": "3.18.0",
        "date": "2026-10-18",
        "title": "A GitHub request queue, bulk GitHub actions, and GitHub\u2019s own status",
        "highlights": [
            {
                "title": "Ticket Tracker: the requests still waiting on us",
                "body": "A new tab on the GitHub page lists every open developer-submitted "
                        "GitHub request, oldest first, read live from Jira rather than from the "
                        "nightly sweep. You can take a ticket and move it through its real "
                        "workflow statuses without leaving the dashboard, so requests stop "
                        "sitting on the default assignee waiting to be noticed.",
            },
            {
                "title": "Org invites, Copilot seats and repo creation in bulk",
                "body": "The Automation page can now send org invitations, assign Copilot seats "
                        "and create repositories with the team\u2019s standard baseline access, "
                        "a batch at a time. Each runs with your own GitHub token rather than the "
                        "shared service account, so GitHub attributes the action to you, and "
                        "each is a background job with live progress instead of a request that "
                        "hangs for hundreds of sequential calls. Anything that fails is retried "
                        "once and then reported, and a summary of every batch goes to the team "
                        "channel.",
            },
            {
                "title": "Repo creation checks its own work",
                "body": "A name that already exists stops the run and says so rather than "
                        "quietly granting access to a repository that may not be the one the "
                        "requestor meant, and every team and collaborator grant is read back "
                        "afterwards to confirm it took effect, instead of trusting that the "
                        "write returned success.",
            },
            {
                "title": "GitHub\u2019s own status, on the page",
                "body": "A banner shows what githubstatus.com currently reports, so a failing "
                        "action can be told apart from GitHub having a bad day. A background "
                        "check posts to the team channel when the overall status changes, twice "
                        "per incident rather than per component or per poll.",
            },
        ],
    },
    {
        "version": "3.17.1",
        "date": "2026-10-18",
        "title": "A release cannot announce itself twice",
        "highlights": [
            {
                "title": "The same release reached the channel twice",
                "body": "3.17.0 was posted on the first start after its deploy and then again "
                        "by hand four minutes later, because neither side could see what the "
                        "other had done. Asking for a release that has already gone out is now "
                        "refused and says when it went and who sent it; sending a second copy "
                        "takes a deliberate second click.",
            },
            {
                "title": "Holding a release back is recorded, not remembered",
                "body": "Keeping a release out of Slack previously meant editing its marker to "
                        "look like a post that had already happened, which is what let 3.17.0 "
                        "slip out. A held release is now marked as held: it does not announce "
                        "itself on deploy, the Admin card says so instead of claiming it was "
                        "announced, and posting it when you want it still works in one click.",
            },
        ],
    },
    {
        "version": "3.17.0",
        "date": "2026-10-18",
        "title": "The maintenance modals stop writing wrong AMI comments and stale branches",
        "highlights": [
            {
                "title": "A GovCloud AMI is no longer labeled us-east-1",
                "body": "The EKS upgrade path reused JFrog's patcher, which hardcodes its own "
                        "region, so a GovCloud image id was written with a us-east-1 comment "
                        "beside it. The id was right and the label pointed at an image that "
                        "does not exist in the region it named. The region now follows the "
                        "cluster being upgraded, and CloudBees and the upgrade path write the "
                        "same comment format instead of two.",
            },
            {
                "title": "Conflict markers are refused instead of edited around",
                "body": "Six files reached main with conflict markers committed into them. The "
                        "patchers are regexes, so they will happily rewrite an AMI id inside a "
                        "conflict block and commit it back, which keeps the damage and makes it "
                        "look deliberate. Every write path now checks for markers first and "
                        "stops with the file named.",
            },
            {
                "title": "main is merged in on every apply",
                "body": "Bringing the branch up to date was an unchecked box, so commits landed "
                        "on whatever the branch last held. Two different AMI steps then existed "
                        "on the same lines and git turned them into the conflict above. It now "
                        "happens every time, and a conflict is reported rather than committed "
                        "on top of.",
            },
            {
                "title": "A comment that names the old image is dropped",
                "body": "When the image name could not be read the id was swapped and the old "
                        "comment left in place, which is how jfrog/prod ended up with the "
                        "October 1.35 id under a 1.34 label. A comment naming the replaced "
                        "image is now removed; an unrelated one is kept.",
            },
        ],
    },
    {
        "version": "3.16.0",
        "date": "2026-10-18",
        "title": "Sign-in says what is actually wrong, and the unlock check works",
        "highlights": [
            {
                "title": "A locked account no longer looks like a wrong password",
                "body": "Active Directory distinguishes a locked account, an expired password, a "
                        "disabled account and a genuinely wrong password, but every one of them "
                        "arrived at the login page as \u201cInvalid username or password\u201d. "
                        "The reason AD gives is now read and shown, so a locked account says so "
                        "and tells you it clears itself after 120 minutes. Only a real wrong "
                        "password still gets the generic message, on purpose, since naming it "
                        "would confirm the account exists to someone guessing.",
            },
            {
                "title": "The AD unlock card reported every account as unlocked",
                "body": "The lock check expected a raw AD timestamp integer but is handed a date "
                        "object, and the parse failure was swallowed as \u201cnot locked\u201d. "
                        "A cleared lockout also arrives as the year 1601 rather than zero, so "
                        "neither branch could ever report a lock. It now asks the domain "
                        "controller for the lockout bit it computes itself, which is also "
                        "correct once a lockout has aged out, and shows when the account was "
                        "locked.",
            },
        ],
    },
    {
        "version": "3.15.1",
        "date": "2026-10-17",
        "title": "Only the real deployment emails the team",
        "highlights": [
            {
                "title": "No more wrong-date maintenance reminders",
                "body": "The maintenance reminder and the SonarQube license alert now only "
                        "run in the deployment that owns them. Any other copy of the "
                        "dashboard \u2014 a beta build, or the app started on an engineer's "
                        "laptop \u2014 reaches the real mail relay but has none of the "
                        "maintenance-date override on disk, so it worked out the standard "
                        "third-Saturday date and emailed the whole team about the wrong day. "
                        "Those timers now stop before sending anything.",
            },
        ],
    },
    {
        "version": "3.15.0",
        "date": "2026-10-17",
        "title": "The deployed version is on the page, and releases announce themselves",
        "highlights": [
            {
                "title": "The version is in the footer",
                "body": "Every page now states the deployed version at the bottom right. It "
                        "comes from the backend rather than the frontend build, so it is the "
                        "same version these notes belong to, and it answers \u201cam I looking "
                        "at the new one?\u201d without a hard refresh.",
            },
            {
                "title": "New releases are posted to the team channel",
                "body": "On the first start after a deploy, the dashboard posts a short summary "
                        "of the release to #cms-cloud-devops-internal: the title and one line "
                        "per highlight. It goes out once per version, so restarts do not repeat "
                        "it, and a send that Slack rejects is retried on the next start rather "
                        "than silently skipped.",
            },
            {
                "title": "Admins can preview or re-post it",
                "body": "A Release Announcement card on the Admin page shows the exact message "
                        "before it goes out, says whether this version has been announced and "
                        "by whom, and can post or re-post it by hand if Slack was down at "
                        "deploy time.",
            },
        ],
    },
    {
        "version": "3.14.0",
        "date": "2026-10-17",
        "title": "The Slack nudge shows when it has already been sent",
        "highlights": [
            {
                "title": "\u201cHung slacked!\u201d",
                "body": "Once Hung has been nudged for an engineer, the button on the GitHub "
                        "access queue turns green and reads \u201cHung slacked!\u201d, with the "
                        "time of the nudge on hover. Clicking it does not send a second "
                        "message: it changes to \u201cSlack again?\u201d and only sends if you "
                        "click a second time, so a stray click cannot message him twice.",
            },
            {
                "title": "It knows across reloads and across people",
                "body": "The state is read from the audit log rather than held in the browser, "
                        "so reloading the page keeps it, and an engineer who nudges Hung is "
                        "visible to everyone else with the board open. It looks back seven "
                        "days, and only counts nudges that Slack actually accepted \u2014 a "
                        "message that was only copied to the clipboard is not treated as sent.",
            },
        ],
    },
    {
        "version": "3.13.1",
        "date": "2026-10-16",
        "title": "Dependency security updates",
        "highlights": [
            {
                "title": "axios and source-map-js",
                "body": "axios moves to 1.20.0, which hardens runtime option handling against "
                        "prototype pollution and fixes unbounded growth of the interceptor "
                        "handler list. source-map-js moves to 1.2.2. No behavior in the "
                        "dashboard changes: it registers one request and one response "
                        "interceptor, both plain functions set up once and never removed, so "
                        "neither hardened path applies differently here.",
            },
            {
                "title": "One update was left alone on purpose",
                "body": "The same advisory group wanted postcss-selector-parser moved to a new "
                        "major, which is only reachable by upgrading Tailwind from 3 to 4. "
                        "Tailwind 4 is a rewrite of how styling is configured and would touch "
                        "every screen, so it is not something to carry in a dependency update. "
                        "The package concerned runs at build time against our own stylesheets "
                        "and never sees anything from a browser.",
            },
        ],
    },
    {
        "version": "3.13.0",
        "date": "2026-10-16",
        "title": "Status badges come from the design system",
        "highlights": [
            {
                "title": "One definition instead of six",
                "body": "Certificate expiry, licenses, CloudBees resource analysis, service "
                        "accounts, SonarQube lines of code and the maintenance tickets all drew "
                        "their own status pills from a local set of classes. They now use the "
                        "design system Badge: success for healthy, warn for approaching, alert "
                        "for critical, info for the ones needing a manual check, and the plain "
                        "badge for unknown. A status the page has not been taught still renders "
                        "as a badge rather than as bare text.",
            },
            {
                "title": "Shared button styles",
                "body": "The ghost link, copy and maintenance buttons are defined once rather "
                        "than repeated per widget, and the four legacy status classes they "
                        "replaced are gone along with their colour tokens.",
            },
        ],
    },
    {
        "version": "3.12.0",
        "date": "2026-10-16",
        "title": "Gold images follow the cluster, and an upgrade moves both together",
        "highlights": [
            {
                "title": "The image offered matches what the cluster runs",
                "body": "Both maintenance modals picked the gold image by the version declared "
                        "in terraform.tfvars. With a bump staged ahead of the apply that offered "
                        "the nodes an image for a control plane that does not exist yet: JFrog "
                        "prod was being offered a 1.35 image while running 1.34. Selection now "
                        "follows the running version, so prod is offered the current 1.34 image "
                        "instead, which is a patch refresh rather than a minor jump. The "
                        "declared version remains the fallback if a cluster cannot be read.",
            },
            {
                "title": "An upgrade moves the version and the image together",
                "body": "Requesting a control-plane upgrade already bumped eks_version and "
                        "realigned the gold image in terraform.tfvars and every Karpenter "
                        "nodeclass, which is the right shape: the image name carries the minor, "
                        "so the nodes have to move with the control plane. JFrog prod was the "
                        "exception, listed as having no nodeclass of its own on the belief that "
                        "it inherits the shared base. It does not, so an upgrade bumped its "
                        "version while leaving its nodes pinned to the old image. It now has "
                        "its real nodeclass and moves with the rest.",
            },
            {
                "title": "One place asks what a cluster is running",
                "body": "The JFrog modal had its own reader that only ever reached the "
                        "dashboard's own account, so prod came back unreadable and quietly fell "
                        "back to the declared version. Both modals now go through the same "
                        "resolver, which assumes the role the dashboard already holds in each "
                        "account.",
            },
        ],
    },
    {
        "version": "3.11.0",
        "date": "2026-10-16",
        "title": "Cluster versions come from the clusters now",
        "highlights": [
            {
                "title": "The card was reporting an intention",
                "body": "A cluster's current version was read from terraform.tfvars on the "
                        "maintenance branch, so it showed what Terraform intends rather than "
                        "what is running. A bump staged ahead of the apply read as already "
                        "done: JFrog prod showed 1.35 while the control plane was on 1.34. "
                        "Reported by Srikanth. The column now shows the version read from AWS, "
                        "and a cluster whose declared and running versions disagree is flagged "
                        "with what tfvars claims.",
            },
            {
                "title": "All six clusters, each through its own account",
                "body": "Reading a cluster has to happen in the account that owns it, so the "
                        "commercial CloudBees and JFrog prod clusters go through the role the "
                        "dashboard already assumes there, and GovCloud uses its own IAM user. "
                        "This needed eks:DescribeCluster, which is a different permission from "
                        "the eks:DescribeClusterVersions already held: that one lists what a "
                        "region offers, not what a cluster runs. Both GovCloud policies were "
                        "even named for this and carried only the wrong one.",
            },
            {
                "title": "A node AMI cannot get ahead of its control plane",
                "body": "The gold image is chosen by the version tfvars declares, so with a "
                        "staged bump the JFrog modal was offering a 1.35 image to a cluster "
                        "running 1.34, which would put the kubelet ahead of the API server. "
                        "That is now refused, and refused rather than assumed safe when the "
                        "running version cannot be read. A same-version image refresh is "
                        "unaffected. Upgrade targets are also counted from the running version, "
                        "so a staged bump no longer hides the work still to do.",
            },
        ],
    },
    {
        "version": "3.10.0",
        "date": "2026-10-16",
        "title": "The GitHub board was counting other teams' tickets",
        "highlights": [
            {
                "title": "654 tickets belonged to another tool",
                "body": "A request was recognized by the word GitHub appearing anywhere in its "
                        "summary, which also caught every ticket that merely mentions GitHub. "
                        "All time went from 2,750 to 2,096 and open from 184 to 144. The bulk "
                        "was 354 secret-scanning alerts and 197 SonarQube tickets, the kind that "
                        "reads \"SonarQube: GitHub PR reporting for a pull request is missing\", "
                        "plus Zscaler connectivity and Security Hub reviews.",
            },
            {
                "title": "Recognized by whose request it is",
                "body": "CLDSPT prefixes a summary with the tool the request is for, so a ticket "
                        "carrying another tool's prefix is that tool's ticket. Those prefixes are "
                        "now excluded. Requiring the summary to start with GitHub would have been "
                        "simpler and wrong: a third of real requests do not, among them \"Account "
                        "access to GitHub\" and \"Unlock GitHub Account\", and they would have "
                        "disappeared from the board instead.",
            },
            {
                "title": "Counts and lists cannot drift apart",
                "body": "The exclusion sits in the single query every number derives from, so the "
                        "per-status, per-engineer and per-application figures move with the "
                        "listings rather than against them. Re-sweep to pick up the new totals.",
            },
        ],
    },
    {
        "version": "3.9.3",
        "date": "2026-10-16",
        "title": "The prod AMI bump commits, and the confirm checkboxes sit straight",
        "highlights": [
            {
                "title": "Detected but not applicable",
                "body": "3.9.1 taught the prod modal to read its own Karpenter nodeclass, so it "
                        "started reporting the AMI bump prod actually needs. The commit path "
                        "was left judging the AMI on terraform.tfvars alone, which for prod is "
                        "already current, so the update counted for nothing: Apply stayed "
                        "disabled, and the request would have carried an empty AMI that the "
                        "backend skips outright.",
            },
            {
                "title": "The checkbox sat above its own sentence",
                "body": "The design system also styles bare label elements with a top margin of "
                        "a line and a half. Beside a checkbox in a flex row that drops the text "
                        "well below the box, so the box looked like it belonged to nothing. This "
                        "is the same cause as the invisible checkboxes in 3.9.2: the design "
                        "system styling plain elements that this app uses without its form "
                        "classes. Labels that want their own spacing still set it and still win.",
            },
            {
                "title": "Either file can be the stale one",
                "body": "The count and the request now treat the AMI as needing work when "
                        "either terraform.tfvars or the nodeclass is behind. Prod's nodeclass "
                        "patches the shared base, so one can be current while the other is not. "
                        "A file whose contents already match is left alone, so nothing "
                        "unnecessary is committed.",
            },
        ],
    },
    {
        "version": "3.9.2",
        "date": "2026-10-15",
        "title": "Every checkbox in the app was invisible",
        "highlights": [
            {
                "title": "The design system collapsed them",
                "body": "Its stylesheet styles bare input[type=checkbox] with "
                        "display:inline-grid, but the box it then draws comes from the "
                        "ds-c-choice class, which this app never uses. A native checkbox "
                        "switched to inline-grid with no size, background or border renders as "
                        "nothing. It arrived with the design system work and has been that way "
                        "since, so the controls were present and clickable but could not be "
                        "seen.",
            },
            {
                "title": "All thirteen are back",
                "body": "This was not only the prod confirmations on the maintenance modals. It "
                        "also hit the I-confirm boxes on the ITC and MGGD close widgets, the "
                        "cache-clear acknowledgement, and the per-user selections in the "
                        "Artifactory and controller user audits, which are how an engineer "
                        "picks who gets deleted. One rule restores native rendering rather than "
                        "retrofitting the design system class onto every widget.",
            },
        ],
    },
    {
        "version": "3.9.1",
        "date": "2026-10-15",
        "title": "JFrog prod's Karpenter AMI is read and offered again",
        "highlights": [
            {
                "title": "Prod does not inherit the base node AMI",
                "body": "The prod modal skipped the Karpenter nodeclass on the grounds that prod "
                        "takes its AMI from the shared base. Prod's overlay lists the nodeclass "
                        "under kustomize patches, so it overrides the base and has to be bumped "
                        "on its own. On the maintenance branch the base has moved to the "
                        "October gold image while prod still pins the September one, which is "
                        "what the prod cluster is running. Prod now reads and offers its own.",
            },
            {
                "title": "The nodeclass row no longer promises a bump it will not make",
                "body": "Both AMI tables took the nodeclass verdict from the terraform.tfvars "
                        "comparison, so prod showed the new AMI in green next to an empty "
                        "current value while the apply deliberately skipped the file. The row "
                        "is now judged on the nodeclass AMI itself, and a row with nothing to "
                        "compare says so instead of reading as up to date.",
            },
        ],
    },
    {
        "version": "3.9.0",
        "date": "2026-10-15",
        "title": "Completed requests, broken down per engineer",
        "highlights": [
            {
                "title": "A Completed column in the engineer table",
                "body": "The single total from 3.8.0 is now a per-engineer figure, counted by "
                        "assignee since the start of yesterday with cancellations still "
                        "excluded. It sits next to All time, so the table shows what each "
                        "person is carrying and what they finished in the same row.",
            },
            {
                "title": "The project total is still there, as a footnote",
                "body": "The rows cover the six people on the team, so they can add up to less "
                        "than the project closed. On the day this shipped the rows summed to 20 "
                        "against 22 closed, the other two finished by someone outside the pool. "
                        "The footnote under the table gives the project figure and says why the "
                        "two numbers differ, so the column does not read as undercounting.",
            },
        ],
    },
    {
        "version": "3.8.0",
        "date": "2026-10-15",
        "title": "How many access requests were finished since yesterday",
        "highlights": [
            {
                "title": "A completed count on the GitHub access panel",
                "body": "Completed since yesterday, with how many of those landed today. It "
                        "answers the question the panel could not before: the other tiles say "
                        "what is sitting in the queue, not what is leaving it.",
            },
            {
                "title": "Cancellations are not counted as completions",
                "body": "A canceled request reaches Done in Jira the same way a fulfilled one "
                        "does, so counting the status category alone reports withdrawals as "
                        "throughput. Yesterday closed 24 requests of which 3 were "
                        "cancellations, so the figure reads 21 and the 3 are stated beside it "
                        "rather than dropped. The count uses the resolution date, which is when "
                        "a request actually left the queue.",
            },
        ],
    },
    {
        "version": "3.7.0",
        "date": "2026-10-15",
        "title": "CMS Design System styling, and an account menu in the sidebar",
        "highlights": [
            {
                "title": "One account menu instead of three buttons",
                "body": "Profile, light and dark mode, and sign out were three separate rows at "
                        "the bottom of the sidebar. They are now one menu behind your name and "
                        "avatar, which also works when the sidebar is collapsed. It is operable "
                        "from the keyboard: focus lands on the first item when it opens, the "
                        "arrow keys move through it and wrap, Home and End jump to the ends, and "
                        "Escape closes it and puts focus back on your name.",
            },
            {
                "title": "Shared styling moved into the design system",
                "body": "Buttons, badges, cards, alerts, dropdowns and link cards are defined "
                        "once in SCSS using CMS Design System tokens instead of repeating "
                        "utility classes in each widget. Ten link widgets, the certificate and "
                        "license tables, and the environment badges all read from the shared "
                        "definitions, so dark mode contrast is fixed in one place.",
            },
            {
                "title": "The sign-in page hero text was unreadable in light mode",
                "body": "The heading and description under the logo were a pale blue on a "
                        "near-white card, around 1.1 to 1 contrast. The rule meant to recolor "
                        "them was nested under a class the markup never used, so it never "
                        "applied. They now inherit the page's own text color.",
            },
        ],
    },
    {
        "version": "3.6.1",
        "date": "2026-10-15",
        "title": "Two fixes to the JFrog entitlement credential tile",
        "highlights": [
            {
                "title": "Prod would have been re-encrypted the old way",
                "body": "The prod registry-auth secret was normalized on the maintenance branch "
                        "to encrypt only the data keys, matching dev, so the metadata stays "
                        "readable in a diff. The tile still described prod as encrypting the "
                        "whole document, so the next prod rotation would have written it back "
                        "that way and silently undone the change.",
            },
            {
                "title": "The maintenance branch is brought up to date first",
                "body": "The branch is long-lived and shared, so by the time a credential is "
                        "rotated it is normally behind main, and the rotation was committing on "
                        "top of whatever was there. Main is now merged in first. A merge "
                        "conflict is someone else's unrelated change, so it is reported rather "
                        "than cancelling the rotation: the secret file stands on its own, and "
                        "the tile says when the branch could not be synced.",
            },
        ],
    },
    {
        "version": "3.6.0",
        "date": "2026-10-15",
        "title": "Chart updates are offered only when Artifactory can serve them",
        "highlights": [
            {
                "title": "The Snapshot Controller bump could never install",
                "body": "Base chart versions were read from ArtifactHub, which answers "
                        "\"has upstream published a newer chart?\". For a chart served from our "
                        "own Artifactory that is the wrong question: Flux can only install what "
                        "has been mirrored. The card committed 5.3.0 in September and 5.4.0 in "
                        "October while the repo held only 5.2.0, so both reconciled to \"no "
                        "snapshot-controller chart with version matching 5.4.0 found\" and the "
                        "cluster sat on the August install for three weeks with the card green.",
            },
            {
                "title": "Latest now comes from the repo Flux actually reads",
                "body": "A chart whose manifest points at an Artifactory-backed "
                        "HelmRepository has its latest version resolved from that repo's Helm "
                        "index instead of upstream. The check keys off the manifest's sourceRef "
                        "rather than a per-chart setting, so any chart later moved onto that "
                        "repository is covered without new configuration.",
            },
            {
                "title": "Applying the monthly JFrog credential is a tile",
                "body": "JFrog issues one credential against our subscription and it is "
                        "regenerated monthly on the JFrog user page. JFrog Entitlement "
                        "Credential under JFrog Automation takes the username and password, "
                        "checks them against releases-authenticated-docker.jfrog.io before "
                        "writing anything, then re-encrypts all three secrets that carry it "
                        "and commits them to the current maintenance branch, so the new "
                        "credential goes live with that month's maintenance. It covers the "
                        "chart secret in flux-system and the image pull secrets in "
                        "artifactory and xray, which previously had to be edited by hand "
                        "with sops. Prod asks for a second confirmation, and each "
                        "environment keeps its own KMS key and encryption scope.",
            },
        ],
    },
    {
        "version": "3.5.0",
        "date": "2026-10-15",
        "title": "Copilot analytics, on the GitHub page",
        "highlights": [
            {
                "title": "Six new views under GitHub \u2192 Copilot",
                "body": "Licenses and seats, AI credits, spend and budget, usage and adoption, a "
                        "per-person leaderboard with a detail view, and a directory by organization "
                        "and language. Everything is read live from our own enterprise and every "
                        "table with meaningful row counts exports to CSV. No call in this feature "
                        "writes anything back to GitHub.",
            },
            {
                "title": "The GitHub page is now tabbed",
                "body": "Access requests, Copilot, Repositories, Reporting and Automation. The "
                        "Copilot views sit one level in. The SSO and token-scope warnings moved "
                        "above the tabs, because either one explains empty data on any of them.",
            },
            {
                "title": "A cost center covered only by individual budgets no longer reads as uncovered",
                "body": "A cost center backed by a team or user resource can be covered by its "
                        "members' own budgets rather than one pooled budget. The old check looked "
                        "only for a pooled budget, so it reported those as having no Copilot budget "
                        "at all. Power Users was the case in point.",
            },
            {
                "title": "Cold loads no longer time out",
                "body": "The per-person views are built from a multi-MB report downloaded from "
                        "GitHub, which outran the ingress read timeout of 90 seconds and showed up "
                        "as a first load failing and a reload working. The ceiling is now 300 "
                        "seconds and is configurable per environment.",
            },
        ],
    },
    {
        "version": "3.4.3",
        "date": "2026-10-14",
        "title": "Slack Hung links go to the ticket again",
        "highlights": [
            {
                "title": "The pasted links were dead",
                "body": "The nudge was written with Slack's <url|label> link syntax, which "
                        "only Slack's API understands. The dashboard has no bot token yet, so "
                        "the message goes on the clipboard instead and Slack's composer treats "
                        "that syntax as plain text: it autolinked the whole token and put the "
                        "label inside the address, giving browse/CLDSPT-116518%7CCLDSPT-116518, "
                        "which errors when clicked.",
            },
            {
                "title": "The clipboard copy carries bare URLs",
                "body": "A pasted nudge now lists the ticket key followed by its plain URL, "
                        "which Slack links on its own. If a bot token is ever configured the "
                        "posted message keeps the nicer inline links, since the API does parse "
                        "them. Reported by Hung.",
            },
        ],
    },
    {
        "version": "3.4.2",
        "date": "2026-10-14",
        "title": "The IR plan schedule follows the maintenance window",
        "highlights": [
            {
                "title": "The task timeline was stuck at 9 p.m.",
                "body": "The IR plan has times in two places: the window header, and the "
                        "task table's Anticipated Start Time column. Only the header was "
                        "written, so the task table kept the hand-built 9 p.m. to 12:50 a.m. "
                        "chain baked into the template. A 7 a.m. window produced a plan whose "
                        "header said 7 a.m. and whose steps said 9 p.m., which is what Change "
                        "Management rejected it for.",
            },
            {
                "title": "Each task is timed from the window start",
                "body": "The durations already in the template are chained from the window "
                        "start, and the Anticipated End Time column the template left empty is "
                        "filled in as well. For a 7 a.m. to 12 p.m. window the work now runs "
                        "07:00 to 10:15 with the rollback contingency to 11:10.",
            },
            {
                "title": "The timezone label is no longer always EST",
                "body": "It was hardcoded, so every window between March and November was "
                        "labelled an hour off. The label now comes from the offset in the "
                        "timestamp: EDT for -0400, EST for -0500.",
            },
            {
                "title": "The Change Management form's newsletter date follows the Go/No-Go",
                "body": "It read 10/8/2026 because it derives from the Go/No-Go date, which "
                        "was the stale minus-ten value. With that corrected the form now "
                        "names the newsletter actually in use.",
            },
        ],
    },
    {
        "version": "3.4.1",
        "date": "2026-10-14",
        "title": "The comms append fills the template instead of adding to it",
        "highlights": [
            {
                "title": "It fills the next blank Change slot, in place",
                "body": "The newsletter page ships with blank Change slots carrying the "
                        "template's own instructions. The append was concatenating a section "
                        "it built itself onto the end of the document, which put it after "
                        "\"Step 3\" where it is not a change entry at all, and gave it a "
                        "shape the template does not have. It now finds the first unfilled "
                        "slot and replaces only the placeholder text inside it.",
            },
            {
                "title": "The template is not altered in any way",
                "body": "Every heading, table row, class and style the template defines is "
                        "left byte-identical; only placeholder text changes. The save is "
                        "refused outright if the edit would touch anything outside the slot. "
                        "The author becomes a real user mention and the ticket a Jira macro, "
                        "which is what the filled entries on the page use.",
            },
            {
                "title": "A template change fails loudly rather than quietly",
                "body": "Each placeholder has to match exactly once or nothing is written, so "
                        "an upstream edit to the template cannot leave half-filled "
                        "instructions in a customer-facing notice. Whitespace is matched "
                        "loosely because Confluence stores non-breaking spaces throughout "
                        "these placeholders, which is what made a literal match fail on "
                        "spacing rather than content.",
            },
            {
                "title": "No blank slot left is an error, not an append",
                "body": "If every slot is filled it says so and asks for one to be added, "
                        "rather than falling back to appending a section to the end.",
            },
        ],
    },
    {
        "version": "3.4.0",
        "date": "2026-10-14",
        "title": "The things Change Management rejects on",
        "highlights": [
            {
                "title": "The ITC is assigned",
                "body": "It was deliberately created unassigned, overriding the template's "
                        "assignee. Change Management rejects an unassigned ITC, so it now "
                        "goes to Masood. Assignee is not on that project's create screen, so "
                        "Jira silently drops it from the create payload; the assignment is "
                        "made through the dedicated endpoint after creation, and the response "
                        "reports whether it stuck.",
            },
            {
                "title": "Go/No-Go can be set explicitly, and warns when it is in the past",
                "body": "It was computed as the maintenance date minus 10 days with nothing "
                        "checking the result. A window arranged late puts the review date "
                        "behind us, which is a rejection. The Admin override now takes a "
                        "Go/No-Go date alongside the window, and the MGGD form refuses to let "
                        "it pass unnoticed: it says so in red when the date has passed, and "
                        "when the window is closer than the ten days the process wants it "
                        "says how many days are left and that a justification will be needed.",
            },
            {
                "title": "Why ITC, MGGD and the IR plan can look like they disagree",
                "body": "They cannot: the IR plan is generated from the same start and end "
                        "passed to the MGGD ticket, and both tickets read one window from the "
                        "server. What differs is the window itself when an override is active, "
                        "so 7 AM to 12 PM is correct for a moved window even though it is not "
                        "the standard 9 to 1.",
            },
        ],
    },
    {
        "version": "3.3.2",
        "date": "2026-10-14",
        "title": "Section headings line up",
        "highlights": [
            {
                "title": "GitHub access requests and Reporting read like Analytics",
                "body": "All three now use the same heading with an icon: a ticket for the "
                        "CLDSPT requests, matching the one the Jira page uses in the sidebar, "
                        "and a spreadsheet for Reporting. They were previously a smaller "
                        "heading with no icon, which made them look subordinate to Analytics "
                        "rather than its peers.",
            },
            {
                "title": "Reporting moved below Repositories",
                "body": "It sits after the repository counts rather than directly under the "
                        "Copilot tiles, which keeps the license and seat tiles together and "
                        "puts the thing you leave the page with at the end.",
            },
        ],
    },
    {
        "version": "3.3.1",
        "date": "2026-10-14",
        "title": "Less chrome on the GitHub page",
        "highlights": [
            {
                "title": "Three pieces of furniture removed",
                "body": "The org and service account line under Analytics, the Enterprise "
                        "licenses heading with the enterprise slug after it, and the warning "
                        "that dso-cjoc-casc is invisible to the service account. The tiles "
                        "below each heading already say what they are.",
            },
            {
                "title": "That last one was stale",
                "body": "It explained that pull requests in an unreadable repository were "
                        "missing from the board rather than counted as zero. The pull request "
                        "board was removed in 2.16.0, so the warning described something that "
                        "no longer existed.",
            },
        ],
    },
    {
        "version": "3.3.0",
        "date": "2026-10-14",
        "title": "The GitHub page reads as tiles",
        "highlights": [
            {
                "title": "Analytics, with licenses and reporting inside it",
                "body": "The section headed GitHub is now headed Analytics, and Enterprise "
                        "licenses and Reporting sit under it rather than floating above as "
                        "separate blocks. The organization and service account move into the "
                        "subtitle instead of repeating the word analytics.",
            },
            {
                "title": "Copilot power users is a tile",
                "body": "It opens on click like the other Copilot tiles instead of sitting "
                        "open as a table. The tile itself says whether any of them are worth "
                        "a look, so you can tell without expanding it.",
            },
            {
                "title": "Reporting is a tile with a team picker",
                "body": "Pick an enterprise team from the list, which shows each team's "
                        "member count, then download the CSV. That replaces a table of every "
                        "team with its own button, which was a lot of page for one action.",
            },
            {
                "title": "Automations keeps its heading and loses the placeholder copy",
                "body": "The section stays so the page keeps a home for GitHub automations, "
                        "without the paragraph explaining that nothing is wired there yet.",
            },
        ],
    },
    {
        "version": "3.2.0",
        "date": "2026-10-14",
        "title": "Reporting section on the GitHub page",
        "highlights": [
            {
                "title": "Download a Copilot report for any enterprise team",
                "body": "A new Reporting section lists the 12 enterprise teams with their "
                        "member counts, and builds a CSV on click. Each row carries the "
                        "member's name, email, EUA, organization, whether they hold a Copilot "
                        "seat, when they last used it, and any dedicated AI-credit budget, "
                        "with the people needing attention sorted to the top.",
            },
            {
                "title": "Enterprise teams, because that is what billing points at",
                "body": "The billing cost centers reference enterprise teams, so a team's "
                        "roster is also who draws on its credit pool. Reporting over the team "
                        "rather than a hand-kept list is why the OC team turned out to be 318 "
                        "people, not the 100 a single unpaged API call suggested.",
            },
            {
                "title": "The CSV is rendered on the server",
                "body": "So the file matches the counts on screen and the browser does not "
                        "reimplement the column order or the escaping. It downloads through "
                        "the API with your token rather than a plain link, which a browser "
                        "navigation would not authenticate, and the server names the file.",
            },
        ],
    },
    {
        "version": "3.1.2",
        "date": "2026-10-14",
        "title": "Maintenance emails go to the whole team",
        "highlights": [
            {
                "title": "Everyone on the roster is notified, not three people",
                "body": "Maintenance reminder and ticket-creation emails went to a "
                        "hardcoded list of three addresses. They now go to the full "
                        "maintenance roster, resolved from each engineer's EUA through AD, "
                        "plus the comms and management side who are not on the roster. That "
                        "is nine recipients instead of three.",
            },
            {
                "title": "The roster is the source, so joiners are not missed",
                "body": "Recipients are derived from the same roster the prep rotation uses, "
                        "so somebody joining or leaving the team is picked up from one place "
                        "rather than depending on an environment variable being remembered. "
                        "Addresses are deduplicated, and if AD cannot be reached the "
                        "configured list still goes out rather than the notice going nowhere.",
            },
        ],
    },
    {
        "version": "3.1.1",
        "date": "2026-10-14",
        "title": "Prep tickets are found even when the window date moves",
        "highlights": [
            {
                "title": "Existing prep tickets are no longer reported as missing",
                "body": "A prep ticket was tied to its window by an exact text match on the "
                        "date in its body, so moving the window by a single day reported all "
                        "three as missing and told you to create a second set. The lookup now "
                        "accepts a prep ticket whose stated window is within 10 days of the "
                        "maintenance date, preferring an exact match when one exists.",
            },
            {
                "title": "A date mismatch is shown, not hidden",
                "body": "When the prep tickets state a different date than the window in "
                        "play, the ITC and MGGD forms now say which date they state and point "
                        "at the Admin override as the likely reason, instead of either "
                        "claiming the tickets are missing or quietly pretending the dates "
                        "agree. If no prep ticket exists for the window at all, it still asks "
                        "you to create them, and it names which tools were found.",
            },
            {
                "title": "The readiness email follows the same rule",
                "body": "The reminder email reads the same prep lookup, so it stops reporting "
                        "prep as outstanding when the tickets exist under a nearby date.",
            },
        ],
    },
    {
        "version": "3.1.0",
        "date": "2026-10-14",
        "title": "ITC and MGGD pre-fill the window, and the override covers time",
        "highlights": [
            {
                "title": "The ITC and MGGD forms fill in the date and window",
                "body": "They never did. The date field opened blank and the start and end "
                        "times are derived from it, so both stayed empty until somebody typed "
                        "a date. That was the behavior from the very first commit, not "
                        "something that broke, though a comment in the code claimed otherwise. "
                        "Both forms now open on the real maintenance date with the window "
                        "already filled.",
            },
            {
                "title": "The window can be overridden, not just the date",
                "body": "The Admin override now takes a start time, an end time and the time "
                        "Datadog stays silenced until, alongside the date. Each is optional: "
                        "leave one blank and it keeps its standard value, so a month that only "
                        "shifts its hours needs no date, and a month that only moves its date "
                        "keeps 9 to 1. The override is rejected if the end is not after the "
                        "start, or if Datadog would un-silence before the window closes.",
            },
            {
                "title": "Everything reads one source now",
                "body": "The date and window come from the server, which is what makes the "
                        "override reach all of it: the ITC and MGGD forms, the Datadog "
                        "downtime, and the window stated in the reminder email. An override "
                        "still expires with its date, and that now drops the times too, so a "
                        "forgotten toggle cannot move next month's hours.",
            },
            {
                "title": "The Datadog downtime could pre-fill the wrong date",
                "body": "It computed the third Saturday in the browser, which cannot see the "
                        "admin override. In an override month, like September running on the "
                        "26th instead of the 19th, it offered a date the tickets would not "
                        "use. It reads the server now, with the local calculation kept only "
                        "as an offline fallback.",
            },
        ],
    },
    {
        "version": "3.0.0",
        "date": "2026-10-13",
        "title": "New look, on the CMS Design System",
        "highlights": [
            {
                "title": "The dashboard now uses the CMS Design System",
                "body": "Menka from the design team rebuilt the shell on "
                        "@cmsgov/design-system with the official USA banner, and moved the "
                        "stylesheets from CSS to SCSS with shared theme, card, alert, sidebar "
                        "and banner partials. Muted text across every page and widget now "
                        "comes from one design-system token instead of a scatter of Tailwind "
                        "grays, so the whole app shifts together when the palette does.",
            },
            {
                "title": "A real sign-in page",
                "body": "Full-width branding, the wave treatment and the CMS banner, with the "
                        "form on a single card. The four area cards in the design (Build, "
                        "Deploy, Monitor, Secure) are commented out rather than shipped: "
                        "choosing one only changed the button label, so they would have "
                        "advertised areas that do not exist yet. The markup is left in place "
                        "to restore once they lead somewhere.",
            },
            {
                "title": "Account details live in one place",
                "body": "Name and email used to appear both in the header and at the bottom "
                        "of the sidebar. They are now only in the sidebar, and the dark mode "
                        "toggle moved there too, which gives the header back to the page "
                        "title. Worth knowing: the sidebar block only renders when the "
                        "sidebar is expanded, so collapsing it hides your account details.",
            },
            {
                "title": "The GitHub page kept everything from 2.18.1",
                "body": "The redesign and the GitHub work were written against different "
                        "versions of that page, so it was rebuilt on the current structure "
                        "rather than reverted: CLDSPT request accounting, two-stage approval, "
                        "application labels, per-org Copilot usage and power users are all "
                        "intact, now wearing the new styling.",
            },
        ],
    },
    {
        "version": "2.18.1",
        "date": "2026-10-13",
        "title": "Slack nudge for Hung is back, and the approval chips now filter",
        "highlights": [
            {
                "title": "Send to Slack, because that is where he looks",
                "body": "An engineer row with tickets the Business Owner has approved now has a "
                        "\"Slack Hung\" button. It covers only that engineer's own tickets, "
                        "only the ones already Business Owner approved, carries a greeting for "
                        "the time of day, and names who approved each one. The Jira comment "
                        "button stays, since that is what leaves a record on the ticket.",
            },
            {
                "title": "It posts for real once a bot token is set",
                "body": "The message is built on the server so the wording is identical either "
                        "way. With SLACK_BOT_TOKEN configured the dashboard posts straight to "
                        "#github-access-approvals-internal; without it the text goes to your "
                        "clipboard and the channel opens for a paste, because Slack has no "
                        "supported link that prefills a channel composer. The token is not in "
                        "the secret today, so it is the clipboard path until it is added.",
            },
            {
                "title": "Approval chips are clickable filters",
                "body": "The approval-state chips in the engineer table now filter the same way "
                        "the status and request-type chips do, so clicking \"needs Hung 3\" "
                        "shows you those three requests instead of leaving you to find them.",
            },
            {
                "title": "The chips no longer disagree with the tickets",
                "body": "They were counted during the nightly sweep while the ticket list is "
                        "read live, so an approval landing in between left a chip claiming work "
                        "that was already done. Srikanth's row read \"needs Hung 3\" when Hung "
                        "had since approved all three. Expanding a row now recounts the chips "
                        "from that engineer's live tickets.",
            },
        ],
    },
    {
        "version": "2.18.0",
        "date": "2026-10-13",
        "title": "Two-stage approval, and Copilot is about adoption not reclaim",
        "highlights": [
            {
                "title": "Hung Van's sign-off is back, in the right order",
                "body": "Approval is two stages: the requester's Business Owner approves "
                        "first, then Hung signs off on top. A ticket whose Business Owner has "
                        "approved now shows a second button that asks him, and it refuses to "
                        "post until that first approval is on the ticket, which is what makes "
                        "it safe. Across the open queue 12 requests are sitting Business "
                        "Owner approved and ready for him, 2 have been asked, and 6 are fully "
                        "signed off.",
            },
            {
                "title": "His approvals are no longer counted as the Business Owner's",
                "body": "Six approvals on open tickets are his second-stage sign-off, and "
                        "they were previously being read as the Business Owner approval. The "
                        "two stages are now told apart by who wrote the comment, and an ask "
                        "is attributed to whichever stage it addresses.",
            },
            {
                "title": "Copilot: reclaim is gone",
                "body": "CMS licenses Copilot for everyone and wants it used, so there is no "
                        "longer anything labeled reclaimable and no cancel button. What is "
                        "left is adoption: 258 of 349 seats are in active use, 11 are idle 30 "
                        "days or more and 80 have never been touched. The email to an unused "
                        "seat holder now encourages them to start using it rather than "
                        "warning them it will be taken away.",
            },
            {
                "title": "Copilot seats break down per organization",
                "body": "Clicking the seat count expands into per-org usage: CMS-Enterprise "
                        "175 seats at 70% active, CMSgov 126 at 88%, cms-enterprise-cpi-ucm "
                        "46 at 48%. That last one is where the unused seats are concentrated, "
                        "with 23 never touched.",
            },
            {
                "title": "Power users and their credit budgets",
                "body": "Eight people hold their own AI-credit budget, read from the "
                        "enterprise budgets API, which is the only place these are recorded. "
                        "Each one is listed with the budget, whether it blocks at the cap, and "
                        "when they last used Copilot, so a budget granted to somebody who is "
                        "not using it stands out. Seven of the eight are active; one has never "
                        "used Copilot at all and is flagged for review. No credits have been "
                        "drawn down enterprise-wide yet, so Copilot activity is the usable "
                        "signal until GitHub's premium-request report starts reporting.",
            },
        ],
    },
    {
        "version": "2.17.0",
        "date": "2026-10-13",
        "title": "Every ticket is labeled with its application",
        "highlights": [
            {
                "title": "Application Name shows on the ticket",
                "body": "It is the field that matters most, because Jira cascades the Primary "
                        "Approver, Backup Approver and Business Owner off it. 140 of the 176 "
                        "open requests have one and it now reads as a label beside the request "
                        "type. The other 36 are the reason those tickets have nobody to "
                        "approve them, so they say so plainly rather than showing a gap.",
            },
            {
                "title": "When it is blank, we work it out",
                "body": "Two signals, in the order Swamy described. First the justification "
                        "text, which usually names the system in prose. When that says nothing "
                        "useful, the requester's AD groups, because CMS group names encode the "
                        "application: ct-ado-claimscorevendora-application-admin means "
                        "ClaimsCore, CFACTS_USER_PRD means CFACTS. That recovers an "
                        "application for 17 of the 36.",
            },
            {
                "title": "A guess is labeled as a guess",
                "body": "A candidate is only shown as a settled answer when the live "
                        "application catalog confirms it, and the label says which signal it "
                        "came from and what it matched on. Anything the catalog does not "
                        "recognize is shown dashed with a question mark, as a lead to follow "
                        "rather than a fact. Vendor names are filtered out so a ticket reads "
                        "ClaimsCore rather than HealthEdge, and so is the CMS-ENTERPRISE org "
                        "name, which appears in nearly every justification.",
            },
            {
                "title": "Nothing is written back to Jira",
                "body": "Setting Application Name would be the real fix, but it triggers "
                        "Jira's own cascade, which emails the second-stage approver before any "
                        "Business Owner has signed off. So this labels the ticket in the "
                        "dashboard and leaves the field alone. The work happens in the daily "
                        "sweep, which adds about a second, and the page reads the answer out "
                        "of the cache.",
            },
        ],
    },
    {
        "version": "2.16.2",
        "date": "2026-10-13",
        "title": "Copilot seats do not need a Business Owner approval",
        "highlights": [
            {
                "title": "No BO approval button on Copilot requests",
                "body": "Business Owner and Product Owner approval applies to GitHub license "
                        "requests only. Eight open Copilot seat requests were showing a "
                        "\"BO approval required\" button that would have chased an approval "
                        "nobody is waiting on. They now read \"No BO approval needed\", and the "
                        "count of requests needing the ask drops from 63 to 55. The endpoint "
                        "refuses too, so the button cannot be worked around.",
            },
            {
                "title": "Application Name is shown next to the Business Owner",
                "body": "Both are read straight off the ticket: Application Name is "
                        "customfield_15250 and Business Owner is customfield_19500. Nothing is "
                        "parsed out of text. Application Name is the one that matters, because "
                        "Jira cascades the approvers and the Business Owner off it, so a blank "
                        "there is the reason a ticket has nobody to approve it. Each ticket now "
                        "says \"not set\" rather than leaving the gap invisible.",
            },
        ],
    },
    {
        "version": "2.16.1",
        "date": "2026-10-13",
        "title": "Business Owner approval replaces chasing one approver",
        "highlights": [
            {
                "title": "Hung is not the approver, and the page no longer says he is",
                "body": "He is a second-stage approver who signs off after the requester's "
                        "Business Owner, not a stand-in for one. Of the requests waiting on "
                        "approval he holds 7; Michael Burling has 11, Karl Davis 8, and 36 "
                        "have no approver configured at all. The Slack nudge that asked him "
                        "to approve is gone, because sending it before a Business Owner has "
                        "signed off is the exact misfire we were trying to avoid.",
            },
            {
                "title": "BO approval required, with a button that asks",
                "body": "Every open request now shows its Business Owner approval state read "
                        "from the ticket's comments: approved with who and when, requested and "
                        "waiting, or nothing asked yet. The last one reads \"BO approval "
                        "required\" and turns into \"Request BO approval\" on hover; clicking "
                        "it comments on the ticket asking the requester to get their Business "
                        "Owner's sign-off. Across the open queue that is 61 needing the ask, "
                        "99 already asked, and 14 approved.",
            },
            {
                "title": "Approval is read from comments because nothing else records it",
                "body": "CLDSPT does not use Jira's approval feature for these and no approval "
                        "field is ever populated, checked across the whole open queue. So the "
                        "classifier reads comments, and it has to tell an approval from a "
                        "request: Jira's automation writes \"Could you please approve?\", which "
                        "contains the word. Phrases like \"once the job code has been approved\" "
                        "and \"approval is pending\" are excluded, and we never count ourselves "
                        "or the requester as the approver.",
            },
            {
                "title": "It cannot nag someone who already approved",
                "body": "The button refuses when an approval is on the ticket, and it does not "
                        "set Application Name: doing that triggers Jira's cascade, which emails "
                        "the second-stage approver before any Business Owner has signed off.",
            },
        ],
    },
    {
        "version": "2.16.0",
        "date": "2026-10-12",
        "title": "Licenses moved up, and the page stops dumping tables",
        "highlights": [
            {
                "title": "The review queue is gone",
                "body": "It only ever covered the five repositories the service account can "
                        "see, so it reported our own pull requests as org-wide and read as "
                        "zero whenever a repo was invisible to the token. The page now leads "
                        "with the CLDSPT request picture, which is the part that is actually "
                        "complete.",
            },
            {
                "title": "Enterprise licenses sit under the CLDSPT section",
                "body": "Purchased, consumed and available were three tiles saying one "
                        "thing, so they are now a single tile reading consumed over "
                        "purchased, with available and the percentage underneath.",
            },
            {
                "title": "Reclaimable Copilot seats open on click",
                "body": "The 93-row table no longer sits open on the page. Clicking the "
                        "reclaimable count expands it, and each row carries the seat "
                        "holder's name and address once resolved.",
            },
            {
                "title": "Reminder emails to unused seat holders",
                "body": "A Copilot seat carries only a GitHub login, and these are vendor "
                        "handles AD has never heard of. The enterprise consumed-licenses "
                        "report ties each login to its EUA, and AD turns that into the "
                        "address the person actually reads. Reminders reuse the escalating "
                        "notice counter the CloudBees outreach uses, so a second nudge says "
                        "Second Notice and the row shows when the last one went out.",
            },
            {
                "title": "Reclaim is wired but needs organization owner",
                "body": "Canceling a seat exists only per organization, and the service "
                        "account is an ordinary member of all three orgs holding reclaimable "
                        "seats, so every org Copilot endpoint returns 404. The button is in "
                        "place and disabled with that reason attached; it starts working the "
                        "moment the account is made an owner with manage_billing:copilot.",
            },
            {
                "title": "Stale repositories, and both repo lists collapse",
                "body": "Recently pushed and stale are now two counts that open their table "
                        "on click. Stale means no push in a year or more, read from the "
                        "oldest-pushed end of the org, with archived repositories left out "
                        "since they are meant to be idle.",
            },
        ],
    },
    {
        "version": "2.15.1",
        "date": "2026-10-12",
        "title": "Status chips read cleanly again",
        "highlights": [
            {
                "title": "The duplicated number is gone",
                "body": "Status chips briefly read like \"Waiting for approval: 98 [98]\". "
                        "A ticket sits in exactly one status at a time, so the count in a "
                        "status and the open count in that status are the same number by "
                        "definition, and the bracket could never say anything new. Each chip "
                        "now shows one count, and the heading says which chips filter rather "
                        "than describing a split that does not exist.",
            },
        ],
    },
    {
        "version": "2.15.0",
        "date": "2026-10-12",
        "title": "Status and request type are now filters",
        "highlights": [
            {
                "title": "Click a status or a request type to filter",
                "body": "Both sets of chips are clickable. Picking one narrows the engineer "
                        "table to just those requests, and the expanded ticket list follows. "
                        "Click again, or use Clear, to drop it. A status with nothing open is "
                        "not clickable, since only open work reaches the table.",
            },
            {
                "title": "The numbers stay exact when you combine them",
                "body": "Choosing a status and a request type together shows the true count "
                        "for that combination rather than an estimate, because the sweep now "
                        "records the full breakdown per engineer instead of only the totals "
                        "for each dimension on its own.",
            },
        ],
    },
    {
        "version": "2.14.1",
        "date": "2026-10-12",
        "title": "Status accounting fixed, and tidier rows",
        "highlights": [
            {
                "title": "No request can fall out of the totals",
                "body": "The page was checking a fixed list of statuses, so when a ticket "
                        "moved to \"Scheduled Work\" it stopped being counted and the "
                        "breakdown stopped adding up. Statuses are now read from Jira at "
                        "sweep time and open versus done comes from Jira's own status "
                        "category, so a status added to the workflow is counted whether or "
                        "not this page has a label for it yet.",
            },
            {
                "title": "The approver nudge opens in the browser",
                "body": "The send button no longer hands off to the Slack desktop app. It "
                        "opens the channel in the browser instead. Slack has no supported "
                        "way to prefill a channel message box from a link, so the text is "
                        "still placed on your clipboard ready to paste.",
            },
            {
                "title": "Request types moved into the row expansion",
                "body": "The engineer table was getting wide, so the request-type breakdown "
                        "now appears when you expand a row rather than as its own column.",
            },
        ],
    },
    {
        "version": "2.14.0",
        "date": "2026-10-12",
        "title": "Access requests by type, and a nudge for approvers",
        "highlights": [
            {
                "title": "Requests are sorted by what is being asked for",
                "body": "Each request is now labeled by its nature: user or org access, "
                        "Copilot seat, new repository, repository migration, service "
                        "account, admin rights, integration, or security finding. Worth "
                        "knowing that 40 of the open items are automated security findings "
                        "that merely mention GitHub rather than access requests, which "
                        "explains part of the total.",
            },
            {
                "title": "You can see what is sitting with an approver",
                "body": "Hung Van is tracked as an approver, read from the Primary Approver "
                        "field on the ticket. Each engineer's row shows how many of their "
                        "own requests are waiting on him, and a ticket only counts when it "
                        "is genuinely sitting on an approval rather than waiting on the "
                        "customer.",
            },
            {
                "title": "One click builds the Slack nudge",
                "body": "The approver chip on your row prepares a message for "
                        "#github-access-approvals-internal with a greeting that matches the "
                        "time of day, your own tickets only, and a link for each one, then "
                        "opens the channel. Slack cannot prefill a channel message, so the "
                        "text is copied to your clipboard ready to paste.",
            },
            {
                "title": "The bell reminds you of your own queue",
                "body": "A notification tells you how many open access requests you are "
                        "carrying, how many are waiting for approval, and who they are "
                        "waiting on. The section has also moved to the top of the GitHub "
                        "page, since it is by far the largest thing in the queue.",
            },
        ],
    },
    {
        "version": "2.13.0",
        "date": "2026-10-12",
        "title": "GitHub access requests on the GitHub page",
        "highlights": [
            {
                "title": "Every access request, in every status",
                "body": "The GitHub page now accounts for all 2,685 CLDSPT GitHub access "
                        "requests rather than only the open ones, which were 175 of them. "
                        "Counts are broken out across all nine statuses these tickets reach, "
                        "and the page flags it if a status turns up that it does not "
                        "recognize, so the breakdown can never quietly stop adding up.",
            },
            {
                "title": "It leads with what is actually blocking",
                "body": "The headline numbers are the ones worth acting on: how many are "
                        "waiting for approval as a share of everything open, and how many "
                        "open requests have nobody assigned at all. On current data that is "
                        "98 waiting for approval and 44 unassigned, which says the queue is "
                        "an approval backlog rather than an engineering one.",
            },
            {
                "title": "Per engineer, with a drill-in",
                "body": "Each engineer's open and all-time volume is listed, and clicking a "
                        "name expands their requests with the status and latest comment on "
                        "each. Comments load only on drill-in, so opening the page stays fast.",
            },
        ],
    },
    {
        "version": "2.12.1",
        "date": "2026-10-08",
        "title": "GitHub page tells you what it cannot see",
        "highlights": [
            {
                "title": "Access problems are now named, not swallowed",
                "body": "A token that is not SSO-authorized for the org fails every private "
                        "repository read with a 403 that mentions no scope. The page now detects "
                        "exactly that and links the authorization, instead of surfacing an "
                        "unexplained GitHub error.",
            },
            {
                "title": "Repos the token cannot see are called out",
                "body": "Open pull requests in a repository the service account cannot read used to "
                        "count as zero, which is indistinguishable from a quiet repo. Those repos "
                        "are now named so the board is never silently incomplete.",
            },
            {
                "title": "Actions billing was never actually locked",
                "body": "The page was checking two retired billing endpoints. It now reads the "
                        "current one, so nothing on the page is reported as locked.",
            },
        ],
    },
    {
        "version": "2.12.0",
        "date": "2026-10-07",
        "title": "New GitHub page",
        "highlights": [
            {
                "title": "GitHub analytics in the sidebar",
                "body": "A new GitHub page with a review queue of every open pull request and its "
                        "review state, bucketed into approved and waiting, changes requested, needs "
                        "review and draft, defaulting to our repos with a toggle for the whole org. "
                        "Plus recently pushed repositories, and anything open 30 days or more "
                        "flagged stale.",
            },
            {
                "title": "Enterprise license and Copilot analytics",
                "body": "With the enterprise-scoped token the page also reports seats purchased "
                        "against seats consumed across the enterprise, and lists the Copilot seats "
                        "worth reclaiming: those never used and those idle for 30 days or more. "
                        "Anything still locked is listed with the exact scope it needs rather than "
                        "shown as an empty panel.",
            },
        ],
    },
    {
        "version": "2.11.4",
        "date": "2026-10-07",
        "title": "Admin promotions are announced",
        "highlights": [
            {
                "title": "Promoting someone to admin now emails them",
                "body": "The new admin gets a note naming who granted it and what admin access "
                        "allows, from maintenance mode to the date override to the audit log. The "
                        "Admin page reports whether the email was sent, and a mail failure never "
                        "blocks the promotion.",
            },
        ],
    },
    {
        "version": "2.11.3",
        "date": "2026-10-07",
        "title": "Duplicate accounts fixed",
        "highlights": [
            {
                "title": "One account per person, whatever casing you type",
                "body": "Sign-in stored whatever casing you typed rather than the spelling Active "
                        "Directory holds, so signing in as RWRW rather than rwrw created a second "
                        "account. That is why the Admin console listed people twice. Sign-in now "
                        "takes the username from AD and all lookups are case-insensitive.",
            },
            {
                "title": "Roles and saved settings no longer depend on casing",
                "body": "An admin who signed in with a different casing silently dropped to the "
                        "user role, and a second profile meant a saved GitHub token looked missing. "
                        "Existing duplicates are merged on startup, keeping the higher role and the "
                        "profile that holds your token.",
            },
        ],
    },
    {
        "version": "2.11.2",
        "date": "2026-10-07",
        "title": "Maintenance window moves to 9 AM",
        "highlights": [
            {
                "title": "The window now starts at 9 AM and no longer crosses midnight",
                "body": "Monthly maintenance runs 9 AM to 1 PM ET on the third Saturday, with the "
                        "Datadog downtime bracketing it to 2 PM. The ITC and MGGD forms, the "
                        "downtime modal and the reminder and confirmation emails all pre-fill and "
                        "state the new window, and the end time no longer rolls into the next day.",
            },
            {
                "title": "SonarQube is no longer gated by the base charts",
                "body": "The shared base charts gate only the tools that reconcile them, which is "
                        "JFrog and CloudBees. SonarQube deploys through its own Jenkins pipeline, "
                        "so its dev and prod cards stay open regardless of the base chart state.",
            },
            {
                "title": "Admin date override is unchanged",
                "body": "The Admin page can still move a given month off the third Saturday, the "
                        "way September 2026 moved to the 26th, and every downstream flow still "
                        "follows the override.",
            },
        ],
    },
    {
        "version": "2.11.1",
        "date": "2026-10-06",
        "title": "Maintenance prep tools rotate again",
        "highlights": [
            {
                "title": "Prep assignments rotate across tools again",
                "body": "With six people in the pool, the prep rotation had collapsed into a "
                        "two-month loop that gave every engineer the same tool every time. "
                        "Assignments now derive from the maintenance month, so each engineer "
                        "covers JFrog, CloudBees and SonarQube over six months, nobody is "
                        "assigned twice in a month, and the load stays even at any pool size.",
            },
        ],
    },
    {
        "version": "2.11.0",
        "date": "2026-10-06",
        "title": "Maintenance sequencing, EKS upgrades and roster",
        "highlights": [
            {
                "title": "EKS Control Plane upgrade card",
                "body": "All six clusters in one place: the versions AWS offers with "
                        "end-of-support dates, the APIs and CRDs a target version removes "
                        "(scanned with pluto), the Kubernetes upgrade notes, and an apply "
                        "that bumps eks_version and realigns the gold image together.",
            },
            {
                "title": "Base Helm Charts split out, and now a prerequisite",
                "body": "The shared kubernetes/base/releases charts moved out of the JFrog "
                        "dev modal into their own card at the top of Tool Maintenance. "
                        "Per-tool upgrades are gated until the shared charts are current, "
                        "with a Run anyway escape hatch.",
            },
            {
                "title": "Agent node pools no longer roll off the gold image",
                "body": "The CloudBees maintenance modal was offering the EKS-optimized "
                        "AL2023 image as the agent target while every nodeclass already ran "
                        "the CMS gold image. It now resolves the gold image in all 4 envs.",
            },
            {
                "title": "Snyk license expiry corrected",
                "body": "The License Expiry widget had been reporting Snyk as expired since "
                        "October 1. The renewal through September 30 2027 is now reflected.",
            },
        ],
    },
    {
        "version": "2.10.0",
        "date": "2026-10-06",
        "title": "EKS upgrade advisor and shared base charts",
        "highlights": [
            {
                "title": "EKS Control Plane and Base Helm Charts cards",
                "body": "First release of the EKS upgrade advisor with the pluto deprecated-API "
                        "scan, plus the shared base charts card.",
            },
        ],
    },
]

APP_VERSION = RELEASES[0]["version"]

_ACK_KEY = "whats_new_ack"


def current_release() -> dict:
    return RELEASES[0]


def release_for(version: str) -> dict | None:
    return next((r for r in RELEASES if r["version"] == version), None)


def acknowledged_version(profile: dict) -> str:
    return (profile or {}).get(_ACK_KEY) or ""


def whats_new_for(profile: dict) -> dict:
    """The popup payload: the current release plus whether this user dismissed it."""
    rel = current_release()
    ack = acknowledged_version(profile)
    return {
        "version": rel["version"],
        "date": rel["date"],
        "title": rel["title"],
        "highlights": rel["highlights"],
        "acknowledged": ack == rel["version"],
        "acknowledged_version": ack,
    }


def mark_acknowledged(profile: dict, version: str) -> dict:
    """Record the dismissal on a profile dict and hand it back for saving."""
    updated = dict(profile or {})
    updated[_ACK_KEY] = version
    return updated
