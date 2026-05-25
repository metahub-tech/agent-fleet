"""Browser-profile lease registry — advisory holder + real instance lifecycle.

Design: docs/internal/design/2026-05-25-browser-profile-lease.md

A browser profile (a Chrome `user-data-dir`, optionally + `--profile-directory`)
is an OS-EXCLUSIVE resource: only one Chrome instance may hold a given user-data-dir
at a time. human_browser and agent_browser therefore share ONE registry so they can
never grab the same profile concurrently. Unlike DeviceStateRegistry (pure advisory),
this also owns the real browser instance handle and how to close it.

Lifecycle (per the design's locked decisions):
  - bind:    free -> start instance + claim; yours -> reuse; held by other -> REFUSE
             with auto_release_in (non-blocking); detached(kept process) -> reattach
             ("warm" reuse); detached of a DIFFERENT engine -> close old + start new.
  - release: detach only — KEEP the process for warm reuse; idle timeout closes it.
  - close:   close the real process + drop the lease.
  - idle timeout: lazily expire (on bind/touch/get_instance/status) -> close + drop.

Thread-safety: one RLock guards state mutation. For V1, start_fn (a slow browser
launch) runs under the lock, which serializes BINDS but not OPERATIONS — touch /
get_instance are O(1), so multi-profile parallel OPERATION still holds. close_fn
LIKEWISE runs under the lock (on close + idle-expiry), so it MUST be non-blocking
(e.g. terminate without an unbounded wait) or it will stall the whole registry. We
use lazy expiry only (no background sweeper), so there is no sweeper-vs-operation
race: get_instance refreshes last_used on every op and a single op is far shorter
than the idle timeout. Promote to two-phase bind / add a sweeper only if needed.

The registry is dependency-free: callers inject start_fn() -> instance and
close_fn(instance) -> None, so browser specifics live in the capabilities, not here.
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

IDLE_TIMEOUT = timedelta(minutes=10)

ENGINE_HUMAN = "human"
ENGINE_AGENT = "agent"
_ENGINES = (ENGINE_HUMAN, ENGINE_AGENT)

STATE_ACTIVE = "active"
STATE_DETACHED = "detached"  # released but process kept for warm reuse


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BrowserLease:
    profile_key: str
    engine: str
    holder: str
    instance: Any
    close_fn: Callable[[Any], None]
    acquired_at: datetime
    last_used_at: datetime
    state: str  # STATE_ACTIVE | STATE_DETACHED


class BrowserLeaseRegistry:
    """Shared by human_browser + agent_browser; keyed by normalized profile_key
    (the real user-data-dir, resolved by the caller so symlinks can't bypass the
    cross-engine mutual exclusion)."""

    def __init__(
        self,
        idle_timeout: timedelta = IDLE_TIMEOUT,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self._idle_timeout = idle_timeout
        self._clock: Callable[[], datetime] = clock if clock is not None else _default_clock
        self._lock = threading.RLock()
        self._leases: dict[str, BrowserLease] = {}

    # ------------------------------------------------------------------
    # internals (call with _lock held)
    # ------------------------------------------------------------------
    def _now(self) -> datetime:
        return self._clock()

    def _is_idle_locked(self, lease: BrowserLease) -> bool:
        return (self._now() - lease.last_used_at) > self._idle_timeout

    def _close_instance(self, lease: BrowserLease) -> None:
        try:
            lease.close_fn(lease.instance)
        except Exception as exc:  # closing must never raise into callers
            print(f"[browser-lease] close_fn failed for {lease.profile_key}: {exc}", file=sys.stderr)

    def _expire_locked(self, profile_key: str) -> None:
        """Close + drop the lease for profile_key if idle-expired (active OR detached)."""
        lease = self._leases.get(profile_key)
        if lease is not None and self._is_idle_locked(lease):
            self._close_instance(lease)
            del self._leases[profile_key]

    def _auto_release_in(self, lease: BrowserLease, now: datetime) -> int:
        idle = int((now - lease.last_used_at).total_seconds())
        return max(0, int(self._idle_timeout.total_seconds()) - idle)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def bind(
        self,
        profile_key: str,
        engine: str,
        holder: str,
        start_fn: Callable[[], Any],
        close_fn: Callable[[Any], None],
    ) -> dict:
        """Claim profile_key for (engine, holder), starting/reattaching the browser.

        start_fn() is called only when a NEW instance is needed; it runs under the
        lock (V1). Returns {bound: True, ...} or {bound: False, current_holder, ...}.
        """
        if not profile_key:
            raise ValueError("profile_key must not be empty")
        if not holder:
            raise ValueError("holder must not be empty")
        if engine not in _ENGINES:
            raise ValueError(f"engine must be one of {_ENGINES}, got {engine!r}")

        with self._lock:
            self._expire_locked(profile_key)
            now = self._now()
            ex = self._leases.get(profile_key)

            if ex is None:
                inst = start_fn()
                self._leases[profile_key] = BrowserLease(
                    profile_key, engine, holder, inst, close_fn, now, now, STATE_ACTIVE
                )
                return {"bound": True, "profile_key": profile_key, "engine": engine, "reused": False}

            if ex.state == STATE_ACTIVE:
                if ex.holder == holder and ex.engine == engine:
                    ex.last_used_at = now
                    return {"bound": True, "profile_key": profile_key, "engine": engine,
                            "reused": True, "note": "already yours"}
                # held by another holder or the other engine -> refuse (non-blocking)
                return {
                    "bound": False,
                    "profile_key": profile_key,
                    "current_holder": ex.holder,
                    "current_engine": ex.engine,
                    "idle_seconds": int((now - ex.last_used_at).total_seconds()),
                    "auto_release_in_seconds": self._auto_release_in(ex, now),
                }

            # ex.state == DETACHED (process kept for warm reuse)
            if ex.engine == engine:
                ex.holder = holder
                ex.state = STATE_ACTIVE
                ex.last_used_at = now
                return {"bound": True, "profile_key": profile_key, "engine": engine,
                        "reused": True, "note": "reattached to kept process"}
            # different engine kept the process -> can't reuse; close it and start fresh
            self._close_instance(ex)
            inst = start_fn()
            self._leases[profile_key] = BrowserLease(
                profile_key, engine, holder, inst, close_fn, now, now, STATE_ACTIVE
            )
            return {"bound": True, "profile_key": profile_key, "engine": engine,
                    "reused": False, "note": "replaced different-engine detached process"}

    def release(self, profile_key: str, holder: str) -> dict:
        """Detach (KEEP the process for warm reuse). Only the holder may release."""
        if not profile_key:
            raise ValueError("profile_key must not be empty")
        with self._lock:
            ex = self._leases.get(profile_key)
            if ex is None:
                return {"released": False, "note": "no lease"}
            if ex.holder != holder:
                return {"released": False, "current_holder": ex.holder,
                        "note": "holder mismatch -- only the holder can release"}
            ex.state = STATE_DETACHED
            ex.holder = ""  # detached = ownerless: a warm bind reassigns it, anyone may close it
            ex.last_used_at = self._now()  # reset idle clock so the kept process lingers a full timeout
            return {"released": True, "kept_alive": True,
                    "note": "process kept warm; idle timeout will close it"}

    def close(self, profile_key: str, holder: str) -> dict:
        """Close the real process and drop the lease. Only the holder may close."""
        if not profile_key:
            raise ValueError("profile_key must not be empty")
        with self._lock:
            ex = self._leases.get(profile_key)
            if ex is None:
                return {"closed": False, "note": "no lease"}
            # detached leases are ownerless (kept warm) -- anyone may close them;
            # an active lease may only be closed by its holder.
            if ex.state == STATE_ACTIVE and ex.holder != holder:
                return {"closed": False, "current_holder": ex.holder,
                        "note": "holder mismatch -- only the holder can close"}
            self._close_instance(ex)
            del self._leases[profile_key]
            return {"closed": True}

    def touch(self, profile_key: str, holder: str) -> dict:
        """Refresh idle clock for an active lease held by holder."""
        if not profile_key:
            raise ValueError("profile_key must not be empty")
        with self._lock:
            self._expire_locked(profile_key)
            ex = self._leases.get(profile_key)
            if ex is None:
                return {"ok": False, "note": "no lease (expired or never bound)"}
            if ex.holder != holder:
                return {"ok": False, "current_holder": ex.holder, "note": "not your lease"}
            if ex.state != STATE_ACTIVE:
                return {"ok": False, "note": "lease detached; re-bind first"}
            ex.last_used_at = self._now()
            return {"ok": True}

    def get_instance(self, profile_key: str, holder: str) -> Any:
        """Return the live instance for an active lease held by holder (op routing),
        refreshing the idle clock. Returns None if not bound/holder mismatch/detached."""
        if not profile_key:
            raise ValueError("profile_key must not be empty")
        with self._lock:
            self._expire_locked(profile_key)
            ex = self._leases.get(profile_key)
            if ex is None or ex.holder != holder or ex.state != STATE_ACTIVE:
                return None
            ex.last_used_at = self._now()
            return ex.instance

    def status(self) -> dict:
        """Snapshot of every current lease."""
        with self._lock:
            for pk in list(self._leases):
                self._expire_locked(pk)
            now = self._now()
            leases = [
                {
                    "profile_key": l.profile_key,
                    "engine": l.engine,
                    "holder": l.holder,
                    "state": l.state,
                    "acquired_at": l.acquired_at.isoformat(),
                    "last_used_at": l.last_used_at.isoformat(),
                    "idle_seconds": int((now - l.last_used_at).total_seconds()),
                    "auto_release_in_seconds": self._auto_release_in(l, now),
                }
                for l in self._leases.values()
            ]
            return {"leases": leases}


# Process-wide shared registry: human_browser + agent_browser import this so a
# single profile can't be held by both engines at once (cross-engine exclusion).
_SHARED: Optional[BrowserLeaseRegistry] = None


def shared_registry() -> BrowserLeaseRegistry:
    global _SHARED
    if _SHARED is None:
        _SHARED = BrowserLeaseRegistry()
    return _SHARED
