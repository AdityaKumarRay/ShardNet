"""Tracker-specific error types."""

from shardnet.common.errors import ShardNetError


class PeerNotFoundError(ShardNetError):
    """Raised when a peer is not known to the tracker."""

    def __init__(self, peer_id: str) -> None:
        super().__init__(
            code="peer_not_found",
            message="Peer is not registered with the tracker.",
            context={"peer_id": peer_id},
        )


class FileMetadataConflictError(ShardNetError):
    """Raised when a file announce conflicts with existing metadata."""

    def __init__(self, info_hash: str) -> None:
        super().__init__(
            code="file_metadata_conflict",
            message="File metadata for this info_hash does not match existing tracker state.",
            context={"info_hash": info_hash},
        )


class InfoHashNotFoundError(ShardNetError):
    """Raised when no file metadata exists for an info_hash."""

    def __init__(self, info_hash: str) -> None:
        super().__init__(
            code="info_hash_not_found",
            message="No tracker metadata exists for the provided info_hash.",
            context={"info_hash": info_hash},
        )
