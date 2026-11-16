"""Signed macOS app bundles re-sign the pinned ONNX Runtime dylib, changing its sha256: the code signature is the check."""
import sys
from pathlib import Path

import pytest

from app import nft2


def test_outside_app_bundle_never_accepted(tmp_path):
    f = tmp_path / "libonnxruntime.1.32.0.dylib"
    f.write_bytes(b"x")
    assert nft2._signed_in_app_bundle(f) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS codesign only")
def test_unsigned_file_in_bundle_path_rejected(tmp_path):
    d = tmp_path / "Fake.app" / "Contents" / "Resources"
    d.mkdir(parents=True)
    f = d / "libonnxruntime.1.32.0.dylib"
    f.write_bytes(b"not a signed mach-o")
    assert nft2._signed_in_app_bundle(f) is False


@pytest.mark.skipif(sys.platform == "darwin", reason="non-macOS")
def test_other_platforms_keep_sha_rule(tmp_path):
    assert nft2._signed_in_app_bundle(Path("/x/Outpost Luna.app/Contents/a.dylib")) is False
