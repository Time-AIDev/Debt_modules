"""The match ladder: which customer a PEAK invoice belongs to, and by which rule.

Vault note 10 §2.1 measured why each rung exists: 612 of 645 V-id contact codes are
Odoo's crm.lead.volt_id (rung 3 bridges through Odoo's phone); 188 of 339 eleven-digit
codes equal a book customer_no (rung 1); 282 codes are composites like
"VL0010239,VC0010687" — the package-change trace (rung 4, candidates only); names are
Latin in PEAK and Thai in the book (rung 5, candidates only).

Pure. The indexes are built by the caller from whatever holds the book today.
EXACT is the only verdict that ever applies without a click (design F1).
"""
import re

V_ID = re.compile(r"^(VC|VRC|VL|VRL)(\d{7})$")
V_SHORT = re.compile(r"^(VC|VRC|VL|VRL)(\d{1,6})$")
ELEVEN = re.compile(r"^\d{11}$")
TITLES = re.compile(r"^(นาย|นางสาว|นาง|คุณ|บริษัท|ด\.ช\.|ด\.ญ\.|mr\.?|mrs\.?|ms\.?|miss|khun)\s*", re.IGNORECASE)


def normalise_code(text):
    return re.sub(r"\s+", "", str(text or "")).upper()


def normalise_name(text):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = TITLES.sub("", t)
    return t.lower()


def _digits(phone):
    d = re.sub(r"\D", "", str(phone or ""))
    if d.startswith("66") and len(d) == 11:
        d = "0" + d[2:]
    return d


def code_parts(text):
    """One code, or the parts of a composite, each repaired where the repair is
    unambiguous: a bare numeric suffix takes the previous part's prefix and length;
    a short V-id is zero-padded to seven digits. Space-delimited parts split only if
    each is code-shaped; otherwise interior whitespace is removed."""
    # Split on comma, semicolon, slash first
    raw_parts = [p for p in re.split(r"[,;/]+", str(text or "")) if p]

    parts = []
    for raw_part in raw_parts:
        # Check if the part contains whitespace
        if " " in raw_part or "\t" in raw_part:
            # Try to split on whitespace
            tokens = raw_part.split()
            # Check if each token is code-shaped (matches V_ID, V_SHORT, or ELEVEN)
            if all(V_ID.match(normalise_code(t)) or V_SHORT.match(normalise_code(t)) or
                   ELEVEN.match(normalise_code(t)) for t in tokens):
                # All tokens are code-shaped, split on whitespace
                parts.extend(normalise_code(t) for t in tokens)
            else:
                # Not all code-shaped, remove whitespace
                parts.append(normalise_code(raw_part))
        else:
            # No whitespace, just normalise
            parts.append(normalise_code(raw_part))

    # Remove empty parts
    parts = [p for p in parts if p]

    # Apply repairs: digit suffix and short code padding
    out, prev = [], None
    for p in parts:
        if p.isdigit() and prev and V_ID.match(prev) and len(p) < 7:
            # Only apply repair if prev is a full V-id
            p = prev[:len(prev) - len(p)] + p
        m = V_SHORT.match(p)
        if m and not V_ID.match(p):
            p = m.group(1) + m.group(2).zfill(7)
        out.append(p)
        # Only update prev if this part is a full V-id
        prev = p if V_ID.match(p) else None
    return out


def _hold(index, key, no):
    holders = index.setdefault(key, [])
    if no not in holders:
        holders.append(no)


def build_book_index(customers):
    """The book, keyed four ways.

    Final review I3: a V-id or a phone two book customers share used to map
    last-wins, so the key auto-applied EXACT to whichever customer came last.
    `vid_holders` / `phone_holders` now list EVERY holder of a key (book order, no
    duplicates), and `by_vid` / `by_phone` keep a key only when exactly one customer
    holds it — so nothing reading them can ever pick one holder of a shared key. (The
    ruling named lists on by_vid / by_phone themselves; the existing, unedited
    test_build_book_index_handles_object_input_with_attributes pins those two as
    key → customer_no, so the lists sit beside them instead.)

    Feedback round 2 / TASK-211: the names are ALSO indexed per script
    (`by_name_th` / `by_name_roman`) so a cross-script hit can be proposed as
    NAME_XSCRIPT — a candidate, never EXACT."""
    idx = {"by_no": {}, "by_vid": {}, "by_phone": {}, "by_name": {}, "vid_holders": {}, "phone_holders": {},
           "by_name_th": {}, "by_name_roman": {}}
    for c in customers:
        get = (lambda k, o=c: o.get(k)) if isinstance(c, dict) else (lambda k, o=c: getattr(o, k, None))
        no = str(get("customer_no") or "")
        if not no:
            continue
        idx["by_no"][no] = no
        m = re.match(r"^(V[A-Z]{1,2}\d{7})", normalise_code(get("volt_id")))
        if m:
            _hold(idx["vid_holders"], m.group(1), no)
        ph = _digits(get("phone_e164"))
        if ph:
            _hold(idx["phone_holders"], ph, no)
        for key, slot in (("by_name_th", get("display_name")), ("by_name_roman", get("name_roman"))):
            n = normalise_name(slot)
            if n and no not in idx[key].get(n, []):
                idx[key].setdefault(n, []).append(no)
        for name in (get("display_name"), get("name_roman")):
            n = normalise_name(name)
            if n and no not in idx["by_name"].get(n, []):
                # Store as a list, maintain book order, no duplicates
                if n not in idx["by_name"]:
                    idx["by_name"][n] = []
                idx["by_name"][n].append(no)
    idx["by_vid"] = {k: v[0] for k, v in idx["vid_holders"].items() if len(v) == 1}
    idx["by_phone"] = {k: v[0] for k, v in idx["phone_holders"].items() if len(v) == 1}
    return idx


def build_odoo_index(rows):
    out = {}
    for r in rows:
        vid = normalise_code(r.get("volt_id"))
        ph = _digits(r.get("phone_e164") or r.get("phone"))
        if V_ID.match(vid) and ph:
            out[vid] = ph
    return out


def _holders(book, kind, key):
    """Every book customer holding `key` ("vid" or "phone"). A hand-built index
    without the *_holders lists still answers from by_vid / by_phone."""
    listed = (book.get(kind + "_holders") or {}).get(key)
    if listed is not None:
        return listed
    one = book["by_" + kind].get(key)
    return [one] if one else []


def _rung(code, book, odoo):
    """Rungs 1–3 for one already-normalised code:
    (customer_no, rule, [])        exactly one book customer holds the key;
    (None, SHARED_*, [holders…])   more than one does — never exact (final review I3);
    (None, None, [])               nothing matches.
    A V-id two customers share stops at rung 2: it is not re-tried through Odoo's
    phone, which could name one of them — or someone else — as if it were certain."""
    if ELEVEN.match(code) and code in book["by_no"]:
        return code, "CUSTOMER_NO", []
    if V_ID.match(code):
        holders = _holders(book, "vid", code)
        if len(holders) == 1:
            return holders[0], "VOLT_ID", []
        if holders:
            return None, "SHARED_VOLT_ID", list(holders)
        phone = odoo.get(code)
        holders = _holders(book, "phone", phone) if phone else []
        if len(holders) == 1:
            return holders[0], "VOLT_ID_VIA_ODOO_PHONE", []
        if holders:
            return None, "SHARED_PHONE", list(holders)
    return None, None, []


def _exact(code, book, odoo):
    """Rungs 1–3 for one already-normalised code. (customer_no, rule) or (None, None);
    a key more than one book customer holds is never exact."""
    no, rule, _ = _rung(code, book, odoo)
    return (no, rule) if no else (None, None)


def _propose(candidates, nos, rule, code):
    for no in nos:
        if not any(c["customer_no"] == no for c in candidates):
            candidates.append({"customer_no": no, "rule": rule, "code": code})


def match_one(invoice, book, odoo, links):
    raw_codes = [invoice.get("contact_code"), invoice.get("reference")]
    for raw in raw_codes:
        code = normalise_code(raw)
        if code and code in links:
            return {"verdict": "EXACT", "rule": "LINK", "customer_no": links[code]["customer_no"], "candidates": []}
    candidates = []
    for raw in raw_codes:
        code = normalise_code(raw)
        if not code:
            continue
        # Pass raw text to code_parts for proper space-handling
        parts = code_parts(raw)
        if len(parts) == 1 and parts[0] == code:
            no, rule, holders = _rung(code, book, odoo)
            # Final review I3: once an earlier column's key turned out shared, a later
            # column's exact hit is proposed beside its holders, never applied over them.
            if no and not candidates:
                return {"verdict": "EXACT", "rule": rule, "customer_no": no, "candidates": []}
            if rule:
                _propose(candidates, [no] if no else holders, rule, code)
    for raw in raw_codes:
        if not raw:
            continue
        code = normalise_code(raw)
        # Pass raw text to code_parts for proper space-handling
        parts = code_parts(raw)
        if len(parts) > 1 or (parts and parts[0] != code):
            for p in parts:
                no, rule, holders = _rung(p, book, odoo)
                if rule:
                    _propose(candidates, [no] if no else holders, "COMPOSITE:" + rule, p)
    name = normalise_name(invoice.get("customer_name"))
    if name:
        # TASK-211: with per-script indexes, a hit only through the OTHER script is
        # proposed as NAME_XSCRIPT — still a CANDIDATE, never EXACT, capped like NAME.
        if "by_name_th" in book:
            th_hit = name in (book.get("by_name_th") or {})
            roman_hit = name in (book.get("by_name_roman") or {})
        else:
            th_hit, roman_hit = name in book["by_name"], False
        if " " in name and (th_hit or roman_hit):
            rule = "NAME" if th_hit else "NAME_XSCRIPT"
            for no in (book["by_name"].get(name) or []):
                if not any(c["customer_no"] == no for c in candidates):
                    candidates.append({"customer_no": no, "rule": rule, "code": invoice.get("customer_name")})
        else:
            # First-word hit (including one-word names): capped at 3 customers
            word = name.split(" ")[0]
            if word and word in book["by_name"]:
                nos = book["by_name"][word]
                if len(nos) <= 3:
                    for no in nos:
                        if not any(c["customer_no"] == no for c in candidates):
                            candidates.append({"customer_no": no, "rule": "NAME_FIRST_WORD", "code": invoice.get("customer_name")})
    if candidates:
        return {"verdict": "CANDIDATE", "rule": None, "customer_no": None, "candidates": candidates}
    return {"verdict": "UNMATCHED", "rule": None, "customer_no": None, "candidates": []}


def match(invoices, book, odoo, links):
    return [match_one(inv, book, odoo, links or {}) for inv in invoices]
