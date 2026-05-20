"""Per-device advisory holder registry — thread-safe, no IO."""
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

IDLE_TIMEOUT = timedelta(minutes=10)


@dataclass(frozen=True)
class Holder:
    name: str
    acquired_at: datetime
    last_used_at: datetime


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStateRegistry:
    """Per-device advisory holder registry, thread-safe.

    One shared lock covers the whole registry — operations on different
    devices serialize at the lock but never block on each other's WORK
    (the lock is only held during state mutation, not during ADB calls).
    """

    def __init__(
        self,
        idle_timeout: timedelta = IDLE_TIMEOUT,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._idle_timeout = idle_timeout
        self._clock: Callable[[], datetime] = clock if clock is not None else _default_clock
        self._lock = threading.Lock()
        # serial -> Holder
        self._holders: dict[str, Holder] = {}

    # ------------------------------------------------------------------
    # Internal helpers (must be called with _lock held)
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        return self._clock()

    def _is_idle_locked(self, holder: Holder) -> bool:
        return (self._now() - holder.last_used_at) > self._idle_timeout

    def _maybe_expire_locked(self, serial: str) -> None:
        """Drop holder for serial if idle-expired."""
        h = self._holders.get(serial)
        if h is not None and self._is_idle_locked(h):
            del self._holders[serial]

    def _expire_all_locked(self) -> None:
        expired = [s for s, h in self._holders.items() if self._is_idle_locked(h)]
        for s in expired:
            del self._holders[s]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self, serial: str, holder_name: str) -> dict:
        """Try to claim `serial` for `holder_name`."""
        if not serial:
            raise ValueError("serial must not be empty")
        with self._lock:
            self._maybe_expire_locked(serial)
            now = self._now()
            existing = self._holders.get(serial)
            if existing is None:
                self._holders[serial] = Holder(
                    name=holder_name,
                    acquired_at=now,
                    last_used_at=now,
                )
                return {"acquired": True, "holder": holder_name}
            if existing.name == holder_name:
                # Re-use object replacement since Holder is frozen
                self._holders[serial] = Holder(
                    name=existing.name,
                    acquired_at=existing.acquired_at,
                    last_used_at=now,
                )
                return {"acquired": True, "holder": holder_name, "note": "already yours"}
            idle = int((now - existing.last_used_at).total_seconds())
            return {
                "acquired": False,
                "current_holder": existing.name,
                "since": existing.acquired_at.isoformat(),
                "idle_seconds": idle,
                "auto_release_in_seconds": max(
                    0, int(self._idle_timeout.total_seconds()) - idle
                ),
            }

    def release(self, serial: str, holder_name: str) -> dict:
        """Release the claim if held by `holder_name`."""
        if not serial:
            raise ValueError("serial must not be empty")
        with self._lock:
            existing = self._holders.get(serial)
            if existing is None:
                return {"released": False, "note": "no holder"}
            if existing.name != holder_name:
                return {
                    "released": False,
                    "current_holder": existing.name,
                    "you_provided": holder_name,
                    "note": "holder_name mismatch -- only the holder can release",
                }
            held = int((self._now() - existing.acquired_at).total_seconds())
            del self._holders[serial]
            return {"released": True, "held_for_seconds": held}

    def touch(self, serial: str) -> None:
        """Refresh last_used_at if `serial` is held."""
        if not serial:
            raise ValueError("serial must not be empty")
        with self._lock:
            self._maybe_expire_locked(serial)
            existing = self._holders.get(serial)
            if existing is not None:
                self._holders[serial] = Holder(
                    name=existing.name,
                    acquired_at=existing.acquired_at,
                    last_used_at=self._now(),
                )

    def status(self, serial: str) -> dict:
        """Snapshot of holder state for `serial`."""
        if not serial:
            raise ValueError("serial must not be empty")
        with self._lock:
            self._maybe_expire_locked(serial)
            existing = self._holders.get(serial)
            if existing is None:
                return {"in_use": False, "note": "free for acquire"}
            now = self._now()
            idle = int((now - existing.last_used_at).total_seconds())
            return {
                "in_use": True,
                "holder": existing.name,
                "acquired_at": existing.acquired_at.isoformat(),
                "last_used_at": existing.last_used_at.isoformat(),
                "idle_seconds": idle,
            }

    def all_status(self) -> dict[str, dict]:
        """{serial: status_dict} for every currently-held device."""
        with self._lock:
            self._expire_all_locked()
            result = {}
            now = self._now()
            for serial, h in self._holders.items():
                idle = int((now - h.last_used_at).total_seconds())
                result[serial] = {
                    "in_use": True,
                    "holder": h.name,
                    "acquired_at": h.acquired_at.isoformat(),
                    "last_used_at": h.last_used_at.isoformat(),
                    "idle_seconds": idle,
                }
            return result
