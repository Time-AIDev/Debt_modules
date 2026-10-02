"""Refresh signatures before opening HTTP; fail closed when refresh fails."""
import os
import signal
import socket
import subprocess
import time

subprocess.run(["freshclam", "--stdout"], check=True, timeout=240)
daemon = subprocess.Popen(["clamd", "--config-file=/srv/clamd.conf"])
server = None
def stop(signum, frame):
    if server: server.terminate()
    daemon.terminate()
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    deadline = time.monotonic() + 90
    while True:
        if daemon.poll() is not None: raise RuntimeError("clamd exited before readiness")
        try:
            with socket.create_connection(("127.0.0.1", 3310), timeout=1): break
        except OSError:
            if time.monotonic() >= deadline: raise RuntimeError("clamd startup timed out")
            time.sleep(1)
    server = subprocess.Popen(["uvicorn", "app.scanner_api:app", "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8080")])
    raise SystemExit(server.wait())
finally:
    daemon.terminate()
    daemon.wait(timeout=10)
