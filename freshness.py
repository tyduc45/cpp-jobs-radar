"""Bound how long an unverified job can appear, without declaring it closed."""
from datetime import datetime, timedelta, timezone

from eligibility import is_visible

DEFAULT_MAX_UNVERIFIED_HOURS = 72


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Source deadlines without a timezone are ambiguous; do not guess one.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def visible_until(job, config):
    last_seen = timestamp(job.get("last_seen"))
    if not last_seen:
        return None
    limit = last_seen + timedelta(hours=config.get("max_unverified_hours", DEFAULT_MAX_UNVERIFIED_HOURS))
    deadline = timestamp(job.get("application_deadline"))
    return min(limit, deadline) if deadline else limit


def is_current(job, config, now=None):
    if not is_visible(job):
        return False
    if "sources" in config and not any(
        job["source_id"] == f"{s['type']}:{s['board']}" and s.get("enabled", True)
        for s in config["sources"]
    ):
        return False
    until = visible_until(job, config)
    return until is not None and until > (now or datetime.now(timezone.utc))
