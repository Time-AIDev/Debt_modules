"""Heartbeat-only cold-restore probe for captured images without --probe-only.

This entry must never dispatch, schedule or retain objects. It runs only in the
isolated staging recovery stack; queued jobs stay untouched.
"""
import os
import time
from urllib.parse import urlsplit


def validate_environment(environ):
    expected = {
        'ENV': 'stg', 'DEPLOYMENT_ENV': 'stg', 'AUTH_MODE': 'on',
        'AUTH_ALLOW_TEST_ACCOUNTS': 'false', 'PROD_GO_LIVE_ENABLED': 'false',
        'PEAK_OUTBOUND_ENABLED': 'false', 'VOLT_SHARED_STATE_ENABLED': 'true',
        'TASK_QUEUE_BACKEND': 'postgres', 'VOLT_RECOVERY_READ_ONLY': 'true',
    }
    if any(environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Recovery worker probe requires the isolated staging policy')
    database = urlsplit(environ.get('DATABASE_URL', ''))
    if database.hostname != 'db' or database.path != '/debt':
        raise RuntimeError('Recovery worker probe requires the internal restored database')


def run(environ=None, *, tick=None, wait=time.sleep):
    validate_environment(os.environ if environ is None else environ)
    if tick is None:
        # Import validates the captured application's configuration. Importing
        # local_worker does not enter its __main__ dispatcher.
        from app import main  # noqa: F401
        from app.local_worker import heartbeat
        tick = heartbeat
    while True:
        tick('probe')
        wait(1)


if __name__ == '__main__':
    run()
