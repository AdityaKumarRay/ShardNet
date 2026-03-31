from shardnet.common.constants import API_PREFIX, API_VERSION, PROTOCOL_VERSION


def test_version_constants() -> None:
    assert API_VERSION == "v1"
    assert API_PREFIX == "/api/v1"
    assert PROTOCOL_VERSION == 1
