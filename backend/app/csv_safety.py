"""One rule for spreadsheet formula detection at import and export boundaries."""
import re

# A prefix such as +1 is insufficient: +1+SUM(...) is a formula. The complete
# value must be numeric before a leading sign is allowed through unchanged.
_NUMBER = re.compile(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_LEADING = "".join(chr(i) for i in range(33)) + "\ufeff"


def formula(value):
    if not isinstance(value, str):
        return False
    text = value.lstrip(_LEADING)
    return bool(text and text[0] in "=+-@" and not _NUMBER.fullmatch(text))


def cell(value):
    """Preserve genuine numbers; force formula-looking text to spreadsheet text."""
    return "'" + value if formula(value) else value


def row(values):
    return [cell(value) for value in values]


def mapping(values):
    return {key: cell(value) for key, value in values.items()}
