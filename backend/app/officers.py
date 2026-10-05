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


# Fingerprints catch in-place changes without caching account emails.
_REGISTRY_CACHE = {"key": None, "rows": None}


def _copy_rows(rows):
    return [{**row, "roles": list(row["roles"])} for row in rows]


def _build_registry(customer_uids, allowlist_entries):
    from .auth import AuthConfigError
    rows = {row["uid"]: {**row, "roles": list(row["roles"])} for row in FIXED}
    for uid in customer_uids:
        if uid and uid not in rows:
            rows[uid] = {"uid": uid, "display_name_th": DISPLAY_TH.get(uid, uid),
                         "display_name_en": uid, "role": "OFFICER", "roles": ["OFFICER"]}
    configured = {}
    for position, (uid, role) in enumerate(allowlist_entries, 1):
        if uid in configured and configured[uid] != role:
            raise AuthConfigError("AUTH_ALLOWLIST entry %d has conflicting officer roles" % position)
        configured[uid] = role
        if uid in rows:
            if role not in rows[uid]["roles"]:
                raise AuthConfigError("AUTH_ALLOWLIST entry %d conflicts with the officer registry role" % position)
        else:
            rows[uid] = {"uid": uid, "display_name_th": DISPLAY_TH.get(uid, uid),
                         "display_name_en": uid, "role": role, "roles": [role]}
    fixed_uids = {row["uid"] for row in FIXED}
    return ([rows[uid] for uid in sorted(rows) if uid not in fixed_uids]
            + [rows[row["uid"]] for row in FIXED])


def registry():
    """Customer, fixed and validated allowlist identities, deduplicated by UID."""
    from . import main, auth
    customer_uids = tuple(getattr(customer, "officer", None)
                          for customer in list(main.CUSTOMERS) + list(main.IDENTITIES))
    config = auth.current_config()
    allowlist_entries = tuple((entry["officer"], entry["role"])
                              for entry in config.allowlist.values()) if config.on else ()
    key = (customer_uids, allowlist_entries)
    if _REGISTRY_CACHE["key"] != key or _REGISTRY_CACHE["rows"] is None:
        rows = _build_registry(customer_uids, allowlist_entries)
        _REGISTRY_CACHE.update(key=key, rows=rows)
    return _copy_rows(_REGISTRY_CACHE["rows"])


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
