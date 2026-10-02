"""The splitter, once schema.sql is allowed to carry a function body."""
from app import migrate


def _split(sql, tmp_path, monkeypatch):
    path = tmp_path / "schema.sql"
    path.write_text(sql, encoding="utf-8")
    monkeypatch.setattr(migrate, "SCHEMA_PATH", path)
    return migrate.statements()


def test_a_semicolon_inside_a_single_quoted_literal_does_not_split(tmp_path, monkeypatch):
    sql = "CREATE TABLE t (a text);\nINSERT INTO t VALUES ('one; two');\n"
    assert _split(sql, tmp_path, monkeypatch) == [
        "CREATE TABLE t (a text)",
        "INSERT INTO t VALUES ('one; two')",
    ]


def test_a_dollar_quoted_function_body_is_one_statement(tmp_path, monkeypatch):
    sql = (
        "CREATE FUNCTION f() RETURNS trigger AS $body$\n"
        "BEGIN RAISE EXCEPTION 'no'; END;\n"
        "$body$ LANGUAGE plpgsql;\n"
        "CREATE TABLE t (a text);\n"
    )
    out = _split(sql, tmp_path, monkeypatch)
    assert len(out) == 2
    assert out[0].startswith("CREATE FUNCTION f()")
    assert "RAISE EXCEPTION" in out[0]
    assert out[1] == "CREATE TABLE t (a text)"


def test_a_doubled_quote_inside_a_literal_is_not_the_end_of_it(tmp_path, monkeypatch):
    sql = "INSERT INTO t VALUES ('it''s; fine');\nSELECT 1;\n"
    assert _split(sql, tmp_path, monkeypatch) == [
        "INSERT INTO t VALUES ('it''s; fine')",
        "SELECT 1",
    ]


def test_comments_are_still_stripped_before_splitting(tmp_path, monkeypatch):
    sql = "-- a prose comment; with a semicolon\nSELECT 1;\n"
    assert _split(sql, tmp_path, monkeypatch) == ["SELECT 1"]
