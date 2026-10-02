import os
import subprocess
import sys
from pathlib import Path

import pytest
from app import task_objects


@pytest.fixture
def local_objects(monkeypatch, tmp_path):
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("UPLOADS_BUCKET", "uploads")
    monkeypatch.setenv("CLEAN_BUCKET", "clean")
    return tmp_path / "objects"


def test_private_object_survives_another_process(local_objects):
    task_objects.put("jobs/run-1/body", b"persistent")
    result = subprocess.check_output([
        sys.executable, "-c",
        "from app import task_objects; import sys; sys.stdout.buffer.write(task_objects.get('jobs/run-1/body'))"],
        env=os.environ.copy(), cwd=Path(__file__).resolve().parents[1])
    assert result == b"persistent"
    assert (local_objects / "uploads/jobs/run-1/body").stat().st_mode & 0o777 == 0o600


def test_objects_are_immutable_and_buckets_are_isolated(local_objects):
    task_objects.put("same", b"original")
    with pytest.raises(FileExistsError):
        task_objects.put("same", b"replacement")
    task_objects.put("same", b"clean", bucket_env="CLEAN_BUCKET")
    assert task_objects.get("same") == b"original"
    assert task_objects.get("same", bucket_env="CLEAN_BUCKET") == b"clean"


@pytest.mark.parametrize("name", ["../outside", "/outside", "nested/../../outside", "a//b"])
def test_object_names_cannot_escape_root(local_objects, name):
    with pytest.raises(ValueError):
        task_objects.put(name, b"private")


def test_symlink_cannot_redirect_private_bytes(local_objects, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (local_objects / "uploads").mkdir(parents=True)
    (local_objects / "uploads/link").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        task_objects.put("link/stolen", b"private")
    assert not (outside / "stolen").exists()
