"""The PEAK invoice-report API door — a PORT, not a client (vault note 10 §3 WP5, ruling F19).

Door 1 (Round A) is the uploaded "รายงานใบแจ้งหนี้" export. Door 2 would pull the same
report from PEAK's API. Nobody has verified an endpoint, a payload or an auth scheme
against PEAK's documentation, so this module holds exactly two things:

  - the NAMES of the configuration door 2 will need (values stay in the environment:
    never in code, a response, a problem or a log);
  - an honest answer: `not_configured` while a name is unset, `untested` once both
    are set, because no endpoint has been verified.

list_invoices therefore never returns and never touches the network. When an endpoint
is verified, the adapter is written here against the documented shape and
VERIFIED_ENDPOINT names the document it was verified against — not before.

PKD-001 pins integrations/peak.py (four public functions, DRAFT_ONLY). This module is
separate on purpose, imports nothing from it, and has no write verb. No webhook
receiver exists: a receiver written against a payload nobody has seen is a guess.
"""
from datetime import date

from . import env

REQUIRED_ENV = ("PEAK_REPORT_API_BASE_URL", "PEAK_REPORT_API_TOKEN")
INSTANCES = ("EPC", "SPV")
# None until an endpoint is verified against PEAK's own documentation; then the title
# and version of that document, and list_invoices gains its adapter.
VERIFIED_ENDPOINT = None

NOT_CONFIGURED_TH = "ยังไม่ได้ตั้งค่าการดึงรายงานใบแจ้งหนี้จาก PEAK API — ต้องตั้ง %s"
UNTESTED_TH = ("ตั้งค่า PEAK API แล้ว แต่ยังไม่ได้ตรวจปลายทางกับเอกสาร API ของ PEAK "
               "ระบบจึงยังไม่ดึงข้อมูล — ใช้การอัปโหลดไฟล์รายงานไปก่อน")


class PeakReportApiError(Exception):
    def __init__(self, code, detail, detail_th, **extra):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.detail_th = detail_th
        self.extra = extra

    def problem(self):
        return dict({"code": self.code, "detail": self.detail, "detail_th": self.detail_th}, **self.extra)


class NotConfigured(PeakReportApiError):
    def __init__(self, missing):
        names = ", ".join(missing)
        super().__init__("integration_not_configured", "Set %s to open the PEAK report API door" % names,
                         NOT_CONFIGURED_TH % names, missing_env=list(missing))
        self.missing = list(missing)


class Untested(PeakReportApiError):
    def __init__(self):
        super().__init__("integration_untested",
                         "No PEAK report endpoint has been verified against PEAK's documentation",
                         UNTESTED_TH)


def _missing():
    return [name for name in REQUIRED_ENV if not env(name)]


def state():
    """The door's state, in codes. Names only — no value is ever read into this dict."""
    missing = _missing()
    return {
        "state": "disabled" if env("ENV") == "prd" else "not_configured" if missing else "untested",
        "env": list(REQUIRED_ENV),
        "missing_env": missing,
        "verified_endpoint": VERIFIED_ENDPOINT,
        "webhook": "not_built",
    }


def _check_since(raw):
    if raw in (None, ""):
        return
    text_value = str(raw)
    try:
        if len(text_value) != 10:
            raise ValueError(text_value)
        date.fromisoformat(text_value)
    except ValueError:
        raise PeakReportApiError("since_invalid", "since must be a date (yyyy-mm-dd); got %r" % text_value,
                                 "วันที่เริ่มดึงต้องเป็นวันที่ รูปแบบ ปี-เดือน-วัน")


def list_invoices(since, instance):
    """Invoices PEAK reports since `since` (yyyy-mm-dd or None) for one instance.

    Refuses in every state this build can be in: a bad argument, a missing name, or an
    endpoint nobody has verified. There is deliberately no request here to refuse later."""
    if env("ENV") == "prd":
        raise PeakReportApiError("feature_disabled", "Production uses PEAK file imports only.", "ใช้การนำเข้าไฟล์ PEAK ในรอบนี้")
    _check_since(since)
    if instance not in INSTANCES:
        raise PeakReportApiError("instance_unknown", "instance is EPC or SPV; got %r" % (instance,),
                                 "instance ต้องเป็น EPC หรือ SPV")
    missing = _missing()
    if missing:
        raise NotConfigured(missing)
    raise Untested()
