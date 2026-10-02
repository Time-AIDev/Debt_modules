"""Canonical PEAK review proposals shared by matching and landing reads."""


def make(value, rule=None, code=None):
    """Return one stable proposal, accepting historical customer-number strings."""
    if isinstance(value, dict):
        customer_no = value.get("customer_no")
        rule = value.get("rule")
        code = value.get("code")
    else:
        customer_no = value
    if customer_no is None:
        return None
    customer_no = str(customer_no).strip()
    if not customer_no:
        return None
    return {"customer_no": customer_no, "rule": rule or None, "code": code or None}


def merge(*groups):
    """Canonical candidates, first source first and unique by customer number."""
    out, seen = [], set()
    for group in groups:
        values = group if isinstance(group, (list, tuple)) else [group]
        for value in values:
            candidate = make(value)
            if candidate is None or candidate["customer_no"] in seen:
                continue
            seen.add(candidate["customer_no"])
            out.append(candidate)
    return out
