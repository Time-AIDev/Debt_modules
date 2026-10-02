"""The scanner port (design F8). ClamAV's clamd over TCP (INSTREAM) when configured;
otherwise the honest label RULES_ONLY. Configured-but-unreachable REFUSES the upload —
a scanner that silently passes when it is down is the failure mode this exists to end.
"""
import socket
import struct
import os
import requests

from ..integrations import env as _env

RULES_ONLY_TH = "ตรวจตามกฎรูปแบบไฟล์แล้ว ยังไม่ผ่านโปรแกรมสแกนไวรัส (ยังไม่ตั้งค่า ClamAV)"
CLEAN_TH = "ผ่านการสแกนไวรัส (ClamAV)"
CHUNK = 64 * 1024


class Infected(Exception):
    def __init__(self, signature):
        super().__init__(signature)
        self.signature = signature


class ScannerUnavailable(Exception):
    pass


def configured():
    return bool(_env("SCANNER_URL") or _env("CLAMAV_HOST"))


def identity_token(audience):
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token
    return id_token.fetch_id_token(Request(), audience)


def _http_scan(raw, url):
    try:
        response = requests.post(url.rstrip("/") + "/scan", data=raw,
                                 headers={"Authorization": "Bearer " + identity_token(url),
                                          "Content-Type": "application/octet-stream"}, timeout=240)
        if response.status_code == 422:
            raise Infected(response.json().get("signature", "malware"))
        if response.status_code != 200 or response.json().get("state") != "CLEAN":
            raise ScannerUnavailable("scanner refused upload")
        return {"state": "CLEAN", "by": "clamd", "note_th": CLEAN_TH}
    except Infected:
        raise
    except Exception:
        raise ScannerUnavailable("scanner unavailable") from None


def scan(raw):
    url = _env("SCANNER_URL")
    if url: return _http_scan(raw, url)
    host = _env("CLAMAV_HOST")
    if not host:
        if os.environ.get("ENV") == "prd": raise ScannerUnavailable("scanner configuration required")
        return {"state": "RULES_ONLY", "by": "rules", "note_th": RULES_ONLY_TH}
    port = int(_env("CLAMAV_PORT", "3310"))
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            sock.sendall(b"zINSTREAM\x00")
            for i in range(0, len(raw), CHUNK):
                piece = raw[i:i + CHUNK]
                sock.sendall(struct.pack(">I", len(piece)) + piece)
            sock.sendall(struct.pack(">I", 0))
            answer = b""
            while not answer.endswith(b"\x00"):
                part = sock.recv(4096)
                if not part:
                    break
                answer += part
    except (OSError, socket.timeout) as exc:
        raise ScannerUnavailable("clamd at %s:%s: %s" % (host, port, exc.__class__.__name__))
    text = answer.rstrip(b"\x00").decode("utf-8", errors="replace")
    if text.endswith("OK"):
        return {"state": "CLEAN", "by": "clamd", "note_th": CLEAN_TH}
    if text.endswith("FOUND"):
        raise Infected(text.split(":", 1)[-1].replace("FOUND", "").strip())
    raise ScannerUnavailable("clamd answered %r" % text[:80])
