"""Small, testable helpers for CARLA session cleanup.

The runnable script owns CARLA objects, but these two invariants are easy to
test without a simulator and easy to get wrong in a ``finally`` block:

* restore the **exact** ``WorldSettings`` snapshot taken before this task
  changed anything (never unconditionally switch back to async);
* destroy only this task's actors and report any that could not be destroyed,
  instead of silently leaving a vehicle or sensor behind.
"""

from __future__ import annotations

from typing import Iterable

__all__ = [
    "SETTINGS_FIELDS",
    "settings_snapshot",
    "restore_settings",
    "destroy_actors",
    "leftover_actors",
    "cleanup_session",
]

#: The WorldSettings fields this task changes and therefore must restore.
SETTINGS_FIELDS = (
    "synchronous_mode",
    "no_rendering_mode",
    "fixed_delta_seconds",
    "substepping",
    "max_substeps",
    "max_substep_delta_time",
)


def settings_snapshot(settings: object) -> dict:
    """Return the restorable subset of a CARLA WorldSettings object."""

    return {name: getattr(settings, name) for name in SETTINGS_FIELDS}


def restore_settings(world: object, snapshot: dict) -> dict:
    """Apply ``snapshot`` to the world's current settings and return what was set.

    A fresh settings object is read from the world, every snapshot field is
    assigned, and the result is applied once. The returned dict is read back
    from the world after applying, so callers can compare before/after.
    """

    if set(snapshot) != set(SETTINGS_FIELDS):
        raise ValueError(
            "settings snapshot must contain exactly %s" % (SETTINGS_FIELDS,)
        )
    current = world.get_settings()
    for name in SETTINGS_FIELDS:
        setattr(current, name, snapshot[name])
    world.apply_settings(current)
    return settings_snapshot(world.get_settings())


def destroy_actors(actors: Iterable[object]) -> list:
    """Destroy the given actors in reverse order, returning per-actor errors.

    An actor that is already dead is skipped. A destroy failure is collected as
    ``"<type>: <message>"`` instead of aborting the remaining cleanup, so one
    stale handle cannot prevent the others from being removed.
    """

    errors = []
    for actor in reversed(list(actors)):
        try:
            if getattr(actor, "is_alive", True):
                actor.destroy()
        except Exception as exc:  # cleanup must continue for the other actors
            errors.append(f"{type(exc).__name__}: {exc}")
    return errors


def leftover_actors(world: object, prefix: str = "vln_") -> list:
    """Return actors whose ``role_name`` starts with ``prefix``."""

    return [
        actor
        for actor in world.get_actors()
        if str(getattr(actor, "attributes", {}).get("role_name", "")).startswith(prefix)
    ]


def cleanup_session(world: object, actors: Iterable[object], snapshot: dict) -> dict:
    """One fail-soft cleanup path shared by success and exception exits.

    Destroys this run's actors, sweeps any remaining ``vln_`` actors, ticks the
    world when possible, restores the exact saved settings, and returns the
    evidence a result report needs. A destroy failure is collected, not raised,
    so a single stale handle cannot stop the settings restore.
    """

    errors = destroy_actors(actors)
    remaining = leftover_actors(world)
    if remaining:
        errors.extend(destroy_actors(remaining))
    try:
        world.tick()
    except Exception:
        pass
    after = restore_settings(world, snapshot)
    return {
        "destroy_errors": errors,
        "leftover_vln_actors": len(leftover_actors(world)),
        "settings_after": after,
        "settings_restored": snapshot == after,
    }
