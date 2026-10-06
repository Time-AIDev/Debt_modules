import socket
import threading
import hashlib

import pytest
from sqlalchemy import text

from app import db, migrate
from app.attachments import scanner, store

META = {"kind": "PDF", "content_type": "application/pdf", "sha256": hashlib.sha256(b"%PDF-1.4 twenty bytes").hexdigest(), "size": len(b"%PDF-1.4 twenty bytes"), "filename": "a.pdf"}
CLEAN = {"state": "RULES_ONLY", "by": "rules", "note_th": "x"}


def _clamd(reply):
    """A one-shot fake clamd speaking INSTREAM."""
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    got = {}

    def serve():
        conn, _ = srv.accept()
        data = b""
        while b"\x00\x00\x00\x00" not in data[data.find(b"\x00") + 1:]:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        got["data"] = data
        conn.sendall(reply); conn.close(); srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return port, got


def test_without_clamav_the_scan_is_rules_only_and_says_so(monkeypatch):
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: d)
    out = scanner.scan(b"%PDF-1.4")
    assert out == {"state": "RULES_ONLY", "by": "rules", "note_th": scanner.RULES_ONLY_TH}


def test_a_clean_clamd_answer_is_clean_and_the_stream_was_framed(monkeypatch):
    port, got = _clamd(b"stream: OK\x00")
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": str(port)}.get(k, d))
    assert scanner.scan(b"%PDF-1.4")["state"] == "CLEAN"
    assert got["data"].startswith(b"zINSTREAM\x00") and got["data"].endswith(b"\x00\x00\x00\x00")


def test_an_infected_answer_raises_with_the_signature(monkeypatch):
    port, _ = _clamd(b"stream: Eicar-Test-Signature FOUND\x00")
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": str(port)}.get(k, d))
    with pytest.raises(scanner.Infected) as exc:
        scanner.scan(b"x")
    assert "Eicar" in exc.value.signature


def test_a_configured_but_unreachable_scanner_refuses_rather_than_passing(monkeypatch):
    monkeypatch.setattr(scanner, "_env", lambda k, d=None: {"CLAMAV_HOST": "127.0.0.1", "CLAMAV_PORT": "1"}.get(k, d))
    with pytest.raises(scanner.ScannerUnavailable):
        scanner.scan(b"x")


def test_the_memory_store_works_without_a_database_and_says_it_is_not_durable(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    store.reset()
    rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
    assert rec["uid"].startswith("att-") and rec["durable"] is False and "bytes" not in rec
    got, raw = store.get(rec["uid"])
    assert raw == b"%PDF-1.4 twenty bytes" and got["scan_state"] == "RULES_ONLY"
    assert store.attach(rec["uid"], "contact:ct-1")["attached_to"] == "contact:ct-1"
    assert [r["uid"] for r in store.list_for("contact:ct-1")] == [rec["uid"]]
    assert store.delete(rec["uid"], "nantapol")["deleted_by"] == "nantapol"
    assert store.get(rec["uid"]) is None


def test_the_postgres_store_round_trips_bytes_and_is_durable(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    # Controller ruling (2026-09-15, ledgered): migrate.apply executes statements
    # without committing, leaving pg_conn inside an autobegun transaction — and
    # store.put's `with conn.begin():` would raise SQLAlchemy's "a transaction is
    # already begun" if handed that connection uncommitted. Commit here so the
    # store's own conn.begin() starts clean. The store COMMITS its own rows, and
    # pg_conn's teardown truncates only schemas landing and app (never records),
    # so cleanup is explicit in `finally` and runs even if an assertion fails.
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
        assert rec["durable"] is True
        _, raw = store.get(rec["uid"])
        assert raw == b"%PDF-1.4 twenty bytes"
    finally:
        pg_conn.execute(text("delete from records.attachment"))
        pg_conn.commit()


def test_attach_to_an_unknown_file_returns_none_on_the_memory_path(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    store.reset()
    assert store.attach("att-unknown0000", "contact:ct-1") is None
    rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
    store.delete(rec["uid"], "nantapol")
    assert store.attach(rec["uid"], "contact:ct-1") is None


def test_put_and_get_agree_on_uploaded_at_in_memory(monkeypatch):
    monkeypatch.setattr(db, "configured", lambda: False)
    store.reset()
    rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
    got, _ = store.get(rec["uid"])
    assert rec["uploaded_at"] == got["uploaded_at"]
    assert "+" in rec["uploaded_at"] or rec["uploaded_at"].endswith("Z")


def test_put_and_get_agree_on_uploaded_at_in_postgres(pg_conn, monkeypatch):
    migrate.apply(pg_conn)
    pg_conn.commit()
    monkeypatch.setattr(db, "configured", lambda: True)
    monkeypatch.setattr(db, "connect", lambda: pg_conn)
    monkeypatch.setattr(pg_conn, "close", lambda: None)
    try:
        rec = store.put(META, b"%PDF-1.4 twenty bytes", "nantapol", CLEAN)
        got, _ = store.get(rec["uid"])
        assert rec["uploaded_at"] == got["uploaded_at"]
        assert "+" in rec["uploaded_at"] or rec["uploaded_at"].endswith("Z")
    finally:
        pg_conn.execute(text("delete from records.attachment"))
        pg_conn.commit()
