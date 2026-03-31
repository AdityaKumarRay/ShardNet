from pathlib import Path

import pytest

from shardnet.client.core.download_store import DownloadStore
from shardnet.client.core.manifest import build_file_manifest, iter_file_chunks
from shardnet.common.errors import TransferError


def test_download_store_resume_state_persists(tmp_path: Path) -> None:
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(b"abcdefghij")
    manifest = build_file_manifest(source_file, chunk_size_bytes=4)

    store = DownloadStore(tmp_path / "client-data")
    target_path = tmp_path / "downloads" / "source.bin"
    store.create_or_resume_download(manifest, target_path)

    first_chunk = next(iter_file_chunks(source_file, manifest.chunk_size_bytes))
    store.write_chunk(manifest, chunk_index=0, chunk_data=first_chunk)

    resumed_store = DownloadStore(tmp_path / "client-data")
    resumed_store.create_or_resume_download(manifest, target_path)
    progress = resumed_store.get_progress(manifest.info_hash)

    assert progress.completed_chunks == [0]
    assert progress.missing_chunks == [1, 2]
    assert progress.status == "active"


def test_download_store_rejects_invalid_chunk_hash(tmp_path: Path) -> None:
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(b"abcdefghij")
    manifest = build_file_manifest(source_file, chunk_size_bytes=4)

    store = DownloadStore(tmp_path / "client-data")
    store.create_or_resume_download(manifest, tmp_path / "downloads" / "source.bin")

    with pytest.raises(TransferError, match="SHA-256"):
        store.write_chunk(manifest, chunk_index=0, chunk_data=b"zzzz")


def test_download_store_finalize_moves_verified_file(tmp_path: Path) -> None:
    source_file = tmp_path / "source.bin"
    payload = b"abcdefghij"
    source_file.write_bytes(payload)
    manifest = build_file_manifest(source_file, chunk_size_bytes=4)

    store = DownloadStore(tmp_path / "client-data")
    target_path = tmp_path / "downloads" / "source.bin"
    store.create_or_resume_download(manifest, target_path)

    for chunk_index, chunk_data in enumerate(
        iter_file_chunks(source_file, manifest.chunk_size_bytes)
    ):
        store.write_chunk(manifest, chunk_index=chunk_index, chunk_data=chunk_data)

    final_path = store.finalize_download(manifest.info_hash)
    progress = store.get_progress(manifest.info_hash)

    assert final_path == target_path
    assert final_path.read_bytes() == payload
    assert progress.status == "completed"
    assert progress.missing_chunks == []
