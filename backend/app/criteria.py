"""Saved review criteria, and the default.

The system refuses an IMPLICIT default population (see errors.population_filter_unset:
"There is no implicit whole-book default, deliberately"). That refusal is about a
default nobody chose. It is not a refusal to let a person choose one.

So a default here is always: chosen by a named person, at a stated time, and shown
that way wherever it is applied. `kpi_default_population_filter` stays open as a
decision about what the ORGANISATION's default is; this is one reviewer's saved view
and never silently becomes the other.

State is process-local and resets on restart. Nothing here writes to the sheet.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

from .session import Store

POPULATIONS = {
    "all_orders": "Every order in the run, whatever its status.",
    "awaiting_approval": "Orders still sitting at Order - EPC Installation.",
    "approved_this_run": "Orders a person moved to Order - Done in this run.",
}

# Only these can carry a target. A target on a figure nobody controls — total book
# value, say — reads as a forecast, and this screen does not forecast.
TARGETABLE = ("orders_approved", "orders_awaiting", "leases", "at_risk_30")


@dataclass
class Criteria:
    population: str = "all_orders"
    province: Optional[str] = None
    order_type: Optional[str] = None
    targets: dict = field(default_factory=dict)
    set_by: Optional[str] = None
    set_at: Optional[str] = None

    def to_dict(self):
        return asdict(self)


# Per tester. One reviewer's saved view must not become another's, which is exactly
# the confusion the "no implicit default" rule exists to prevent.
#
# The slot holds a one-element list rather than the Criteria directly, because None
# is a meaningful value here — "nobody has saved one" is different from an empty
# criteria object, and the interface must be able to tell them apart.
_default_store = Store(lambda: [None], key="criteria.default")


def reset():
    _default_store.reset()


def get_default():
    return _default_store.for_current()[0]


def save_default(payload, by, at):
    """Returns (criteria, error_code)."""
    criteria, error = build(payload)
    if error:
        return None, error
    criteria.set_by = by
    criteria.set_at = at
    _default_store.for_current()[0] = criteria
    return criteria, None


def clear_default():
    slot = _default_store.for_current()
    had = slot[0] is not None
    slot[0] = None
    return had


def build(payload):
    """Validate an incoming criteria payload. Returns (criteria, error_code)."""
    payload = payload or {}
    population = payload.get("population") or "all_orders"
    if population not in POPULATIONS:
        return None, "population_unknown"

    targets = {}
    for key, value in (payload.get("targets") or {}).items():
        if key not in TARGETABLE:
            return None, "target_not_targetable:%s" % key
        if value is None or value == "":
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None, "target_not_a_number:%s" % key
        if number < 0:
            return None, "target_negative:%s" % key
        targets[key] = number

    return Criteria(
        population=population,
        province=(payload.get("province") or None),
        order_type=(payload.get("order_type") or None),
        targets=targets,
    ), None
