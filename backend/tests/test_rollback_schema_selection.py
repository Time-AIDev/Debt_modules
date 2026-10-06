"""Choose rollback code for the schema that actually committed, never downgrade data."""
import importlib.util
from pathlib import Path
import pytest

source = Path(__file__).resolve().parents[2] / "infra/vps/release.py"
spec = importlib.util.spec_from_file_location("rollback_schema_selection_test", source)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_failed_transaction_keeps_previous_schema_and_image():
    assert release.rollback_image_for_schema(2, "previous", 2, "compatible", 3) == "previous"


def test_committed_schema_requires_compatible_fallback_image():
    assert release.rollback_image_for_schema(3, "previous", 2, "compatible", 3) == "compatible"


@pytest.mark.parametrize("image,version", [(None, None), ("unsupported", 2), ("future", 4)])
def test_no_compatible_code_refuses_schema_downgrade(image, version):
    with pytest.raises(release.ReleaseError, match="schema-compatible"):
        release.rollback_image_for_schema(3, "previous", 2, image, version)
