from pathlib import Path

from typer.testing import CliRunner

from shardnet.cli.main import app

runner = CliRunner()


def test_client_manifest_command_outputs_manifest(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"abcdefghij")

    result = runner.invoke(
        app,
        ["client", "manifest", str(file_path), "--chunk-size", "4"],
    )

    assert result.exit_code == 0
    assert '"info_hash"' in result.output
    assert '"total_chunks": 3' in result.output


def test_client_status_returns_non_zero_when_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "client",
            "status",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "--data-dir",
            str(tmp_path / "client-data"),
        ],
    )

    assert result.exit_code == 1
    assert "Status unavailable" in result.output
