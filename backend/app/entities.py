"""EPC / SPV — the two entities of deck v20.0, and the one-field routing rule.

"Each document is routed on company_id, so the routing rule is one field, not a set
of conditions." (Deck v20.0, architecture slide.) SPV never appears on a cash order.
EPC is the service entity for every customer, cash and lease alike.
"""

EPC = "EPC"
SPV = "SPV"

COMPANIES = {
    EPC: {
        "company_id": "CO-EPC",
        "name": "EPC — operating company",
        "debt_module": "DEBT Cash",
        "peak_ledger": "PEAK Cash",
    },
    SPV: {
        "company_id": "CO-SPV",
        "name": "SPV — financing vehicle",
        "debt_module": "DEBT Lease",
        "peak_ledger": "PEAK Lease",
    },
}

# The receivable kinds and who owns each. SERVICE is EPC's even on an SPV lease —
# that is the deck's deliberate two-entity showcase (S09).
RECEIVABLE_ENTITY = {
    "CASH": EPC,
    "LEASE": SPV,
    "SERVICE": EPC,
}


def entity_for(product: str) -> str:
    """CASH → EPC, LEASE → SPV. Unknown products refuse rather than guess —
    an invoice booked into the wrong PEAK instance is a statutory-books error."""
    key = (product or "").strip().upper()
    if key not in RECEIVABLE_ENTITY:
        raise ValueError("no entity routing for product %r" % product)
    return RECEIVABLE_ENTITY[key]


def company_id_for(entity: str) -> str:
    return COMPANIES[entity]["company_id"]


def entity_fields(entity: str) -> dict:
    """The pair every routed payload carries, together, always."""
    return {"entity": entity, "company_id": company_id_for(entity)}


def assert_entity_present(payload):
    """Response-boundary guard, the same shape as band_sets.assert_band_pair_present:
    any object carrying `entity` must carry `company_id` beside it. One field of the
    pair alone cannot route a document."""
    if isinstance(payload, dict):
        if "entity" in payload and payload["entity"] in (EPC, SPV):
            assert "company_id" in payload, (
                "entity present without company_id — documents route on company_id "
                "(deck v20.0); the entity label alone is not a routing rule"
            )
        for value in payload.values():
            assert_entity_present(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            assert_entity_present(item)
