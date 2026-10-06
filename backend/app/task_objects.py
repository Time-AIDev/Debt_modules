"""Private immutable objects, on GCS or a server-owned filesystem volume."""
import os
import re
import shutil
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
            reserve = int(env("OBJECT_STORAGE_MIN_FREE_BYTES", str(1024 * 1024 * 1024)))
            if shutil.disk_usage(env("OBJECT_STORAGE_ROOT")).free - len(raw) < reserve:
                raise OSError("Private object storage is below its free space reserve")
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
    cap = int(env("OBJECT_READ_MAX_BYTES", str(100 * 1024 * 1024)))
    if env("OBJECT_STORAGE_BACKEND", "gcs") == "filesystem":
        with _parent(name, bucket_env, create=False) as (directory, filename):
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "rb") as source:
                raw = source.read(cap + 1)
                if len(raw) > cap:
                    raise ValueError("Private object exceeds the read limit")
                return raw
    with client() as transport:
        response = transport.get("https://storage.googleapis.com/storage/v1/b/%s/o/%s" % (bucket(bucket_env), quote(name, safe="")),
                                 params={"alt": "media"}, timeout=60, stream=True)
        response.raise_for_status()
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > cap:
                response.close()
                raise ValueError("Private object exceeds the read limit")
            chunks.append(chunk)
    return b"".join(chunks)


def delete(name, bucket_env="UPLOADS_BUCKET"):
    """Idempotent deletion of a known immutable object; callers prove retention."""
    if env("OBJECT_STORAGE_BACKEND", "gcs") == "filesystem":
        try:
            with _parent(name, bucket_env, create=False) as (directory, filename):
                try:
                    os.unlink(filename, dir_fd=directory)
                    os.fsync(directory)
                except FileNotFoundError:
                    return False
        except FileNotFoundError:
            return False
        return True
    with client() as transport:
        response = transport.delete("https://storage.googleapis.com/storage/v1/b/%s/o/%s" %
                                    (bucket(bucket_env), quote(name, safe="")), timeout=60)
        if response.status_code == 404:
            return False
        response.raise_for_status()
    return True


def list_transient_objects():
    """Only transient prefixes; permanent attachments are never GC candidates."""
    bucket_name = env("UPLOADS_BUCKET")
    if env("OBJECT_STORAGE_BACKEND", "gcs") == "filesystem":
        root = env("OBJECT_STORAGE_ROOT")
        if (not root or not Path(root).is_absolute() or Path(root).is_symlink() or
                not re.fullmatch(r"[A-Za-z0-9_-]+", bucket_name or "")):
            raise ValueError("Invalid private object location")
        base = Path(root) / bucket_name
        if base.is_symlink():
            raise ValueError("Invalid private object location")
        for prefix in ("chunks", "jobs"):
            directory = base / prefix
            if directory.is_symlink() or not directory.exists():
                continue
            for parent, directories, filenames in os.walk(directory, followlinks=False):
                directories[:] = [name for name in directories if not (Path(parent) / name).is_symlink()]
                for filename in filenames:
                    path = Path(parent) / filename
                    if not path.is_symlink() and path.is_file():
                        stat = path.stat()
                        yield {"name": str(path.relative_to(base)), "size": stat.st_size, "updated": stat.st_mtime}
        return
    from datetime import datetime
    with client() as transport:
        for prefix in ("chunks/", "jobs/"):
            page = None
            while True:
                params = {"prefix": prefix, "maxResults": 1000, "fields": "items(name,size,updated),nextPageToken"}
                if page:
                    params["pageToken"] = page
                response = transport.get("https://storage.googleapis.com/storage/v1/b/%s/o" % bucket(),
                                         params=params, timeout=60)
                response.raise_for_status()
                data = response.json()
                for item in data.get("items", []):
                    yield {"name": item["name"], "size": int(item["size"]),
                           "updated": datetime.fromisoformat(item["updated"].replace("Z", "+00:00")).timestamp()}
                page = data.get("nextPageToken")
                if not page:
                    break


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
