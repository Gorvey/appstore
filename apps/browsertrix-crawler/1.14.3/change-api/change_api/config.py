from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    token: str
    crawls_dir: Path
    data_dir: Path
    scan_interval: float
    max_content_bytes: int
    mcp_inline_bytes: int
    control_dir: Path = Path("/crawl-control")

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("CHANGE_API_TOKEN", "")
        if not token:
            raise RuntimeError("CHANGE_API_TOKEN must be set and non-empty")
        return cls(
            token=token,
            control_dir=Path(os.environ.get("CHANGE_API_CONTROL_DIR", "/crawl-control")),
            crawls_dir=Path(os.environ.get("CHANGE_API_CRAWLS_DIR", "/crawls")),
            data_dir=Path(os.environ.get("CHANGE_API_DATA_DIR", "/data")),
            scan_interval=_positive_float("CHANGE_API_SCAN_INTERVAL", 30.0),
            max_content_bytes=_positive_int(
                "CHANGE_API_MAX_CONTENT_BYTES", 32 * 1024 * 1024
            ),
            mcp_inline_bytes=_positive_int(
                "CHANGE_API_MCP_INLINE_BYTES", 64 * 1024
            ),
        )


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value
