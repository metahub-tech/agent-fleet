"""Per-device holder registry with session-bound, enforced leases — thread-safe, no IO.

Semantics (enforced by `_lease_gate.LeaseGate` on every device-touching tool):

* a device with **no holder** is free — any session may use it;
* once a session acquires a lease, **only that session** may use the device;
  other sessions get a structured denial instead of silently sharing the mouse;
* every allowed call refreshes ``last_used_at`` (**auto-renew**), including
  capability tools such as browser / human_dom / vision;
* 10 idle minutes release the lease lazily (no background thread).
"""
import os
import sys
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
    session_id: Optional[str] = None   # MCP session that acquired it (enforcement key)


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

    def acquire(self, serial: str, holder_name: str, session_id: Optional[str] = None) -> dict:
        """Try to claim `serial` for `holder_name` (bound to `session_id` when given).

        Re-acquiring with the same holder name is idempotent and **re-binds** the
        lease to the caller's session, so an agent that reconnected (new MCP
        session) recovers its own lease instead of being locked out.
        """
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
                    session_id=session_id,
                )
                return {"acquired": True, "holder": holder_name}
            if existing.name == holder_name:
                # Re-use object replacement since Holder is frozen
                self._holders[serial] = Holder(
                    name=existing.name,
                    acquired_at=existing.acquired_at,
                    last_used_at=now,
                    session_id=session_id if session_id is not None else existing.session_id,
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

    def release(self, serial: str, holder_name: str, session_id: Optional[str] = None) -> dict:
        """Release the claim if held by `holder_name`.

        When the lease is session-bound, a release from a **different** session is
        refused (re-acquiring with the same name re-binds it first).
        """
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
            if (
                session_id is not None
                and existing.session_id is not None
                and existing.session_id != session_id
            ):
                return {
                    "released": False,
                    "reason": "session_mismatch",
                    "holder": existing.name,
                    "note": "lease is bound to another session -- call acquire again to re-bind, then release",
                }
            held = int((self._now() - existing.acquired_at).total_seconds())
            del self._holders[serial]
            return {"released": True, "held_for_seconds": held}

    def guard(self, serial: str, session_id: Optional[str]) -> dict:
        """Enforced access check + auto-renew, called before every device-touching tool.

        Returns ``{"ok": True, ...}`` and refreshes ``last_used_at`` when the call
        may proceed. Returns ``{"ok": False, ...}`` with the back-off information
        when another session holds the lease. A free (or idle-expired) device is
        allowed but is **not** auto-acquired: claiming stays explicit.
        """
        if not serial:
            raise ValueError("serial must not be empty")
        with self._lock:
            self._maybe_expire_locked(serial)
            existing = self._holders.get(serial)
            if os.environ.get("FLEET_LEASE_DEBUG") == "1":
                holder = existing.name if existing else None
                bound = existing.session_id if existing else None
                print(f"[lease] guard serial={serial} session={session_id} holder={holder} bound={bound}",
                      file=sys.stderr, flush=True)
            if existing is None:
                return {"ok": True, "leased": False}
            bound = existing.session_id
            if bound is None or session_id is None or bound == session_id:
                # legacy/unbound lease, or a session-less client: allow + renew
                self._holders[serial] = Holder(
                    name=existing.name,
                    acquired_at=existing.acquired_at,
                    last_used_at=self._now(),
                    session_id=bound,
                )
                return {"ok": True, "leased": True, "holder": existing.name, "renewed": True}
            idle = int((self._now() - existing.last_used_at).total_seconds())
            return {
                "ok": False,
                "leased": True,
                "current_holder": existing.name,
                "idle_seconds": idle,
                "auto_release_in_seconds": max(
                    0, int(self._idle_timeout.total_seconds()) - idle
                ),
            }

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
                "auto_release_in_seconds": max(
                    0, int(self._idle_timeout.total_seconds()) - idle
                ),
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
                    "auto_release_in_seconds": max(
                        0, int(self._idle_timeout.total_seconds()) - idle
                    ),
                }
            return result
