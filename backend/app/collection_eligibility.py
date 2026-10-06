"""Installation eligibility, separate from debt amounts and human NPL decisions."""
from . import debt_imports

ENDED = frozenset({"CLOSED", "WRITTEN_OFF", "TERMINATED", "CANCELLED"})


def for_contract(contract, field_of=None):
    field_of = field_of or (lambda item, name: getattr(item, name, None))
    status = field_of(contract, "status")
    if status in ENDED:
        return {"eligible": False, "state": "ENDED", "reason": "ENDED_CONTRACT"}
    if status == "PRE_COLLECTION":
        return {"eligible": False, "state": "NOT_INSTALLED", "reason": "NOT_INSTALLED"}
    # Native/synthetic engine proofs keep their established pure assessment seam;
    # every imported/enriched production contract requires separate confirmation.
    if not getattr(contract, "requires_installation_confirmation", False) and not getattr(
            contract, "requires_schedule_confirmation", False):
        return {"eligible": True, "state": "LEGACY_ENGINE", "reason": None}
    confirmation = debt_imports.installation_for(contract.uid)
    if not confirmation or confirmation.get("state") != "CONFIRMED":
        return {"eligible": False, "state": "UNCONFIRMED", "reason": "INSTALLATION_UNCONFIRMED"}
    return {"eligible": True, "state": "CONFIRMED", "reason": None, "confirmation": confirmation}
