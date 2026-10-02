#!/usr/bin/env python3
"""A real PostgreSQL 16 for the test suite, with no root, no Homebrew, no Docker.

This machine has none of the three — ~/.volt-gcloud-env records "no root, no
Homebrew", which is already why gcloud runs against a uv-installed Python 3.12.
The `pgserver` wheel ships relocatable PostgreSQL binaries and runs them from a
data directory under $HOME over a unix socket, which needs no port, no service
and no privileges.

Real Postgres and not SQLite because the landing schema is jsonb throughout, and
a jsonb bug that only appears in staging has appeared in the wrong place.

    ./scripts/pg_local.sh start            # volt_test: start, create if absent, print the URL
    ./scripts/pg_local.sh start volt_debt  # any other name (the prototype's own database)
    ./scripts/pg_local.sh url [volt_debt]  # just the URL, for VOLT_TEST_PG_URL / DATABASE_URL
    ./scripts/pg_local.sh stop

The test suite's database and the prototype's must be different: conftest's pg_conn
teardown truncates every landing/app table, which would empty the served book.
"""
import pathlib
import sys

PGDATA = pathlib.Path.home() / ".volt-postgres" / "data"
DB = "volt_test"


def server():
    import pgserver
    PGDATA.mkdir(parents=True, exist_ok=True)
    # cleanup_mode=None: the server outlives this process, so a test run does not
    # pay initdb again and `url` is cheap to call from a shell.
    return pgserver.get_server(str(PGDATA), cleanup_mode=None)


def db_name(argument=None):
    """The database this call is about: the argument, then $VOLT_PG_DB, then the suite's."""
    import os
    return argument or os.environ.get("VOLT_PG_DB") or DB


def ensure_database(srv, name=None):
    name = db_name(name)
    existing = srv.psql("select datname from pg_database;")
    if name not in existing:
        srv.psql("create database %s;" % name)


def url(srv=None, name=None):
    srv = srv or server()
    return srv.get_uri(database=db_name(name)).replace("postgresql://", "postgresql+psycopg://")


def main(argv):
    command = argv[1] if len(argv) > 1 else "url"
    name = argv[2] if len(argv) > 2 else None
    if command == "url":
        print(url(name=name))
    elif command == "start":
        srv = server()
        ensure_database(srv, name)
        version = srv.psql("select current_setting('server_version');").split()[2]
        print("PostgreSQL %s ready · database %s" % (version, db_name(name)))
        print(url(srv, name))
    elif command == "stop":
        server().cleanup()
        print("stopped")
    elif command == "status":
        srv = server()
        print(srv.psql("select current_setting('server_version');").split()[2])
    else:
        print("usage: pg_local.sh start|stop|status|url [database]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
