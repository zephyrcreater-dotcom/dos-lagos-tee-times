"""Lightweight JSON-file state tracking for already-notified tee times.

No database: just a dict of `unique_id -> last_known_available_spots`, persisted as JSON.
This lets the monitor tell apart:
  - a tee time it has never seen before (not in the state file)
  - a tee time whose availability increased since last seen (new spots opened up,
    including a slot going from 0 -> N after a cancellation)
  - a tee time that is unchanged or has fewer spots than before (no notification)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .teeitup import TeeTime

logger = logging.getLogger(__name__)


def load_state(path: str | Path) -> dict[str, int]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("State file %s did not contain a JSON object; ignoring it", path)
            return {}
        return {str(k): int(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Could not read state file %s (%s); starting with empty state", path, exc)
        return {}


def save_state(path: str | Path, state: dict[str, int]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp_path.replace(path)


def find_newly_available(tee_times: list[TeeTime], state: dict[str, int]) -> list[TeeTime]:
    """Return the subset of `tee_times` that represent new or increased availability.

    Does not mutate `state` — call `update_state` separately once you've decided to treat
    this batch as "seen" (e.g. after successfully sending a notification, or on every
    dry run if you don't want to re-detect the same slots next time).
    """
    newly_available = []
    for tee_time in tee_times:
        previous_spots = state.get(tee_time.unique_id, 0)
        if tee_time.available_spots > previous_spots:
            newly_available.append(tee_time)
    return newly_available


def update_state(tee_times: list[TeeTime], state: dict[str, int]) -> dict[str, int]:
    """Return a new state dict reflecting the latest observed availability for `tee_times`.

    Tee times not present in `tee_times` are left untouched in the returned state (e.g. a
    slot for a date outside today's query isn't touched by a query for a different date).
    """
    updated = dict(state)
    for tee_time in tee_times:
        updated[tee_time.unique_id] = tee_time.available_spots
    return updated
