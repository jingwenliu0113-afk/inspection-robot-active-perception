"""Shared Mac heavy-lock check (PORTFOLIO.md "Mac Hard Lock", MACHINE_POLICY.md).

This project never takes the lock for development work, but long multi-process CPU work must not
run while another project holds it (its formal measurement would be disturbed). Check before the
run starts and again before every job; a job that finds the lock held is skipped, not queued.
"""

from __future__ import annotations

from pathlib import Path

LOCK = Path("/tmp/ai-portfolio-mac-heavy.lock")


def holder(lock: Path = LOCK) -> str | None:
    """None when the lock is free, else the owner description (owner.txt if readable)."""
    if not lock.exists():
        return None
    owner = lock / "owner.txt"
    try:
        return owner.read_text().strip().replace("\n", "; ") or "(empty owner.txt)"
    except OSError:
        return "(owner.txt unreadable)"


def require_free(lock: Path = LOCK) -> None:
    h = holder(lock)
    if h is not None:
        raise SystemExit(f"Mac heavy lock is held ({h}): not starting CPU-heavy work")
