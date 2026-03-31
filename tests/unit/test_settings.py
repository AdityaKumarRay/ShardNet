from shardnet.common.config import ClientSettings, TrackerSettings


def test_tracker_settings_env_override(monkeypatch) -> None:
    monkeypatch.setenv("TRACKER_PORT", "8123")
    monkeypatch.setenv("TRACKER_LOG_LEVEL", "DEBUG")

    settings = TrackerSettings()

    assert settings.port == 8123
    assert settings.log_level == "DEBUG"


def test_client_defaults() -> None:
    settings = ClientSettings()

    assert settings.protocol_version == 1
    assert settings.tracker_base_url.startswith("http://")
    assert settings.default_chunk_size_bytes == 262_144
