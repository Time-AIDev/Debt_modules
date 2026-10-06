"""Read-only document diagnostics; quarantined observations never become cash."""
def documents(rejected, limit=50, offset=0):
    grouped = {}
    for item in rejected or []:
        key = item.get("doc_no") or "source-row-%s" % item.get("row", "unknown")
        group = grouped.setdefault(key, {"doc_no": item.get("doc_no"), "verdict": "REJECTED",
                                         "can_apply": False, "codes": [], "rows": []})
        if item.get("code") not in group["codes"]:
            group["codes"].append(item.get("code"))
        group["rows"].append({"row": item.get("row"), "code": item.get("code"),
                              "field_or_value": item.get("value"),
                              "observation": item.get("observation") or {}})
    values = list(grouped.values())
    return {"rows": values[offset:offset + limit], "total": len(values),
            "source_rows": sum(len(item["rows"]) for item in values), "limit": limit, "offset": offset}
