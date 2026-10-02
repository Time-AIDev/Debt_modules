"""Who signs a governed act — round-2 settasak S2-04.

The interface carries two headers: X-Volt-Officer (the identity switch) and
X-Volt-Role (the role button). Round 2 pressed MANAGER/OWNER while the identity
stayed on an officer, so a lead's review answer, the Owner's cut-off approval and a
report snapshot were all signed "nantapol". A governed act is signed by a person
whose registry role matches the role that performed it; when the header identity
does not, the act is signed by that role's default identity and the record says so
(`by_role`). Nothing here is authentication — the registry is the seed's own names.
"""
ROLE_DEFAULTS = {"MANAGER": "settasak", "OWNER": "owner"}
GOVERNED_ROLES = ("MANAGER", "OWNER")

# Fixed members beside the officers the seed assigns customers to. settasak is the
# team lead persona (Supervisor + Manager); "owner" is the Owner's own identity.
FIXED = (
    {"uid": "settasak", "display_name_th": "settasak", "display_name_en": "settasak", "role": "MANAGER", "roles": ["SUPERVISOR", "MANAGER"]},
    {"uid": "owner", "display_name_th": "เจ้าของระบบ (owner)", "display_name_en": "System owner (owner)", "role": "OWNER", "roles": ["OWNER"]},
    # The O&M team's seat (round-3 J3-07 added OPS to the API roles; login 2026-09-13
    # gives it an identity so ops.test signs as someone the registry knows).
    {"uid": "ops", "display_name_th": "ทีมปฏิบัติการ (ops)", "display_name_en": "Operations team (ops)", "role": "OPS", "roles": ["OPS"]},
)
# Thai spellings the sheet's MapLog uses for an officer (cases.OFFICER_ALIASES holds the reverse).
DISPLAY_TH = {"thip": "ทิพย์อักษร"}


# The scan is over the whole served book, and the shell, Today and Reports each ask
# for it on one load. Cached against the book the scan read: the same CUSTOMERS and
# IDENTITIES list objects at the same length. A reload rebinds the lists
# (main.reload_book), so the next call rescans; the held references also keep those
# list objects alive, so a freed-and-reallocated id can never be mistaken for the
# book the cache was built from.
_REGISTRY_CACHE = {"customers": None, "identities": None, "lengths": None, "rows": None}


def registry():
    """[{uid, display_name_th, role, roles}] — every officer the seed assigns work to,
    as OFFICER, plus the fixed Manager and Owner identities."""
    from . import main
    customers, identities = main.CUSTOMERS, main.IDENTITIES
    lengths = (len(customers), len(identities))
    cached = _REGISTRY_CACHE
    if (cached["rows"] is not None and cached["customers"] is customers
            and cached["identities"] is identities and cached["lengths"] == lengths):
        # Fresh dicts, as before the cache: callers own what they are handed.
        return [dict(row) for row in cached["rows"]]
    seen, rows = set(), []
    # Every served customer, identities included: a crm.lead identity is assigned to
    # the same two desk officers as any other row, and auth.check_officers refuses to
    # start when an allow-listed officer is missing from this registry.
    for customer in list(customers) + list(identities):
        uid = getattr(customer, "officer", None)
        if uid and uid not in seen:
            seen.add(uid)
            rows.append({"uid": uid, "display_name_th": DISPLAY_TH.get(uid, uid), "display_name_en": uid, "role": "OFFICER", "roles": ["OFFICER"]})
    rows.sort(key=lambda r: r["uid"])
    for fixed in FIXED:
        if fixed["uid"] not in seen:
            rows.append(dict(fixed))
    cached.update(customers=customers, identities=identities, lengths=lengths, rows=rows)
    return [dict(row) for row in rows]


def role_of_officer(uid):
    for row in registry():
        if row["uid"] == uid:
            return row["role"]
    return None


def sign(body, officer_header, role_header, fallback="officer"):
    """Returns (by, by_role). `by` is the body's `by`, else the header identity, else the
    fallback word — unless the act's role is MANAGER/OWNER and that identity does not
    hold the role: then the role's default identity signs and by_role names the role."""
    role = (role_header or "OFFICER").upper()
    identity = (body or {}).get("by") or (officer_header or "").strip() or None
    if role in GOVERNED_ROLES:
        holder = role_of_officer(identity) if identity else None
        # An identity the registry knows as an OFFICER cannot sign a Manager/Owner act;
        # a name the registry does not know (a lead typing their own) is kept as given.
        holds = identity is not None and (holder is None or holder == role or (role == "MANAGER" and holder == "OWNER"))
        if not holds:
            return ROLE_DEFAULTS[role], role
        return identity, role
    return identity or fallback, None
