"""Private immutable objects, on GCS or a server-owned filesystem volume."""
import os
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from .integrations import env


def client():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


def bucket(bucket_env="UPLOADS_BUCKET"):
    value = env(bucket_env)
    if not value: raise RuntimeError(bucket_env + " is required")
    return quote(value, safe="")


def put(name, raw, bucket_env="UPLOADS_BUCKET"):
    if env("OBJECT_STORAGE_BACKEND", "gcs") == "filesystem":
        with _parent(name, bucket_env, create=True) as (directory, filename):
            fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.fsync(directory)
            except BaseException:
                os.unlink(filename, dir_fd=directory)
                raise
        return name
    with client() as transport:
        response = transport.post("https://storage.googleapis.com/upload/storage/v1/b/%s/o" % bucket(bucket_env),
                                  params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
                                  data=raw, headers={"Content-Type": "application/octet-stream"}, timeout=60)
        response.raise_for_status()
    return name


def get(name, bucket_env="UPLOADS_BUCKET"):
    if env("OBJECT_STORAGE_BACKEND", "gcs") == "filesystem":
        with _parent(name, bucket_env, create=False) as (directory, filename):
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "rb") as source:
                return source.read()
    with client() as transport:
        response = transport.get("https://storage.googleapis.com/storage/v1/b/%s/o/%s" % (bucket(bucket_env), quote(name, safe="")),
                                 params={"alt": "media"}, timeout=60)
        response.raise_for_status()
    return response.content


@contextmanager
def _parent(name, bucket_env, create):
    parts = name.split("/")
    bucket_name = env(bucket_env)
    root = env("OBJECT_STORAGE_ROOT")
    if (not root or not Path(root).is_absolute() or not bucket_name or
        not re.fullmatch(r"[A-Za-z0-9_-]+", bucket_name) or
        any(part in ("", ".", "..") or "\x00" in part for part in parts)):
        raise ValueError("Invalid private object location")
    if create:
        Path(root).mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in [bucket_name] + parts[:-1]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                    os.fsync(directory)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory, parts[-1]
    finally:
        os.close(directory)
