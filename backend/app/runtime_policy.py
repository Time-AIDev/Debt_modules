"""Runtime defaults shared by local, staging and production release scripts."""
import os

SCHEMA_VERSION = 2
DEFAULTS = {
    "AUTH_SESSION_POLICY": "tab", "AUTH_TAB_ABSOLUTE_SECONDS": "28800",
    "AUTH_REAUTH_SECONDS": "0", "REQUEST_JSON_MAX_BYTES": "1048576",
    "REQUEST_UPLOAD_MAX_BYTES": "104857600", "REQUEST_BODY_TIMEOUT_SECONDS": "30",
    "PROD_LOCK_WAIT_SECONDS": "15", "AUTH_LOGIN_RATE_LIMIT": "30",
    "REQUIRE_STATE_VERSION": "true",
    "AUTH_LOGIN_RATE_WINDOW_SECONDS": "60", "MAX_JOB_ATTEMPTS": "5",
    "JOB_EXECUTION_TIMEOUT_SECONDS": "300", "WORKER_HEARTBEAT_MAX_AGE_SECONDS": "30",
    "UPLOAD_OWNER_MAX_BYTES": "209715200", "UPLOAD_TOTAL_MAX_BYTES": "1073741824",
    "JOB_OWNER_MAX_BYTES": "209715200", "JOB_TOTAL_MAX_BYTES": "1073741824",
    "OBJECT_STORAGE_MIN_FREE_BYTES": "1073741824", "OBJECT_READ_MAX_BYTES": "104857600",
    "REQUEST_RESULT_RETENTION_HOURS": "24", "TRANSIENT_OBJECT_GRACE_HOURS": "24",
    "DEAD_LETTER_RETENTION_DAYS": "7", "XLSX_PARSE_MAX_SECONDS": "120",
    "XLSX_MAX_PROCESSED_CELLS": "10000000", "XLSX_MAX_KEPT_CELLS": "1000000",
    "XLSX_MAX_KEPT_TEXT_BYTES": "67108864", "XLSX_MAX_SHARED_STRINGS": "250000",
    "XLSX_MAX_SHARED_STRING_BYTES": "16777216", "PEAK_OUTBOUND_ENABLED": "false",
    "DB_POOL_SIZE": "5", "DB_MAX_OVERFLOW": "2",
    "REQUIRE_DEPENDENCY_READINESS": "true",
}


def shared_state_enabled(environ=None):
    environ = os.environ if environ is None else environ
    return environ.get("ENV") == "prd" or environ.get("VOLT_SHARED_STATE_ENABLED") == "true"


def environment_defaults(environment, state="shared"):
    aliases = {"dev": "dev", "local": "dev", "stg": "stg", "staging": "stg",
               "uat": "stg", "prd": "prd", "prod": "prd", "production": "prd"}
    mode = aliases.get(environment)
    if mode is None or state not in ("shared", "fixtures"):
        raise ValueError("unknown environment or state mode")
    if mode == "prd" and state != "shared":
        raise ValueError("production requires shared state")
    values = dict(DEFAULTS, ENV=mode, DEPLOYMENT_ENV=mode,
                  VOLT_SHARED_STATE_ENABLED="true" if state == "shared" else "false",
                  AUTH_MODE="on" if state == "shared" else "off",
                  AUTH_ALLOW_TEST_ACCOUNTS="false" if mode == "prd" else "true",
                  PROD_GO_LIVE_ENABLED="false" if mode == "prd" else "true")
    return values
