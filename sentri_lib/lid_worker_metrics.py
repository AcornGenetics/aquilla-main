"""Live-count tracking for lid-heater worker threads (issue #157).

Diagnostic instrumentation for the SENTRI self-cancellation study: a leak shows
up as ``live_count`` climbing across runs without returning to zero. Pure logic,
no hardware imports, so it is importable on any machine.
"""
import threading

_live_tids: set[int] = set()
_lock = threading.Lock()


def enter(tid: int) -> int:
    """Register a live lid-heater worker; return the new live count."""
    with _lock:
        _live_tids.add(tid)
        return len(_live_tids)


def exit(tid: int) -> int:
    """Deregister a lid-heater worker; return the new live count."""
    with _lock:
        _live_tids.discard(tid)
        return len(_live_tids)


def live_count() -> int:
    """Number of lid-heater workers currently registered as live."""
    with _lock:
        return len(_live_tids)


def live_tids() -> set[int]:
    """Copy of the currently-registered worker thread ids."""
    with _lock:
        return set(_live_tids)


def reset() -> None:
    """Clear all tracked workers (test support)."""
    with _lock:
        _live_tids.clear()
