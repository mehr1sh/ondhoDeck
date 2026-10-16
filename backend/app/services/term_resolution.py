"""Which approved terms are in force on a date.

A term applies on `as_of` when it is approved (confirmed/edited) and `effective_from <= as_of < effective_to`
(missing bounds are open). Supersession is explicit: superseding a term sets its `effective_to` to the newer
term's `effective_from`, so the older term stops applying from that date while staying in history for
earlier dates and past runs. Nothing is inferred from document order or upload time; two approved terms in
force for the same simulator input with different values are reported as a conflict by the engine.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol

from ..engine.simulator import APPROVED_STATUSES


class Dated(Protocol):
    review_status: str
    effective_from: date | None
    effective_to: date | None


def in_force(c: Dated, as_of: date) -> bool:
    if c.review_status not in APPROVED_STATUSES:
        return False
    if c.effective_from is not None and c.effective_from > as_of:
        return False
    return c.effective_to is None or c.effective_to > as_of
