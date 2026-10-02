"""Private GCS objects accessed with workload identity, without downloaded keys."""
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
    with client() as transport:
        response = transport.post("https://storage.googleapis.com/upload/storage/v1/b/%s/o" % bucket(bucket_env),
                                  params={"uploadType": "media", "name": name, "ifGenerationMatch": "0"},
                                  data=raw, headers={"Content-Type": "application/octet-stream"}, timeout=60)
        response.raise_for_status()
    return name


def get(name, bucket_env="UPLOADS_BUCKET"):
    with client() as transport:
        response = transport.get("https://storage.googleapis.com/storage/v1/b/%s/o/%s" % (bucket(bucket_env), quote(name, safe="")),
                                 params={"alt": "media"}, timeout=60)
        response.raise_for_status()
        return response.content
