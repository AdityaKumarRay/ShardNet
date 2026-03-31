from pathlib import Path

import pytest

from shardnet.client.core.manifest import build_file_manifest


def test_build_file_manifest_from_path(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"abcdefghij")

    manifest = build_file_manifest(file_path, chunk_size_bytes=4)

    assert manifest.file_name == "sample.bin"
    assert manifest.file_size_bytes == 10
    assert manifest.chunk_size_bytes == 4
    assert manifest.total_chunks == 3
    assert len(manifest.chunk_sha256) == 3
    assert manifest.chunk_size_for_index(0) == 4
    assert manifest.chunk_size_for_index(1) == 4
    assert manifest.chunk_size_for_index(2) == 2


def test_build_file_manifest_rejects_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.bin"
    file_path.write_bytes(b"")

    with pytest.raises(ValueError, match="empty file"):
        build_file_manifest(file_path, chunk_size_bytes=1024)
