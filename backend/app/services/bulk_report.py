"""Posts a bulk-job completion report to Slack #cms-cloud-devops-internal,
shared by the org-invite, Copilot-seat, and repo-create workers, so whoever
ran a batch (and the rest of the team) sees the outcome without having to
keep the dashboard tab open until it finishes."""
from __future__ import annotations

from app.services import slack

_CHANNEL = "cms-cloud-devops-internal"
_MAX_LISTED = 20
_MAX_REASON_LEN = 150
# Slack rejects a whole message if any section's text exceeds 3000 chars.
# The item-count cap above bounds the common case, but a long GitHub error
# message (error_detail() allows up to 200 chars per item) times 20 items
# can still exceed it, so the text itself is bounded too, with margin for
# the "*Failed:*" header and the "...and N more" suffix.
_SECTION_CHAR_LIMIT = 3000
_SECTION_SAFETY_MARGIN = 200


def send_completion_report(title: str, by: str | None, lines: list[str], failures: list[tuple[str, str]]) -> None:
    """`lines` are short markdown summary strings (counts, etc.); `failures`
    are (name, reason) pairs for anything that didn't succeed, listed
    (capped by count and by rendered size) so there's something concrete to
    investigate from the alert itself."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": False}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]
    if failures:
        budget = _SECTION_CHAR_LIMIT - _SECTION_SAFETY_MARGIN
        included: list[str] = []
        for name, reason in failures[:_MAX_LISTED]:
            short_reason = reason if len(reason) <= _MAX_REASON_LEN else reason[:_MAX_REASON_LEN] + "…"
            line = f"• {name}: {short_reason}"
            if len(line) > budget:
                break
            included.append(line)
            budget -= len(line) + 1  # +1 for the newline joining it to the next line
        omitted = len(failures) - len(included)
        if omitted > 0:
            more = f"…and {omitted} more"
            failure_text = "\n".join([*included, more]) if included else more
        else:
            failure_text = "\n".join(included)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Failed:*\n{failure_text}"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Run by {by or 'unknown'}"}]})

    slack.send_message(_CHANNEL, title, blocks)


def send_crash_report(kind: str, username: str, error: str) -> None:
    """A batch's worker thread died before finishing -- post a short alert
    rather than leaving the job silently stuck for anyone polling it."""
    slack.send_message(_CHANNEL, f"GitHub {kind} batch by {username} failed to finish: {error}")
