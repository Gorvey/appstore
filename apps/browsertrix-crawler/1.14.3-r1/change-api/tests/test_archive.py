import gzip
import json
import zipfile
from io import BytesIO
from pathlib import Path

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from change_api.archive import ArchiveIndexer, read_metadata
from change_api.config import Settings
from change_api.db import Repository


def make_wacz(path: Path, url: str, body: bytes, created: str) -> None:
    raw = BytesIO()
    writer = WARCWriter(raw, gzip=True)
    headers = StatusAndHeaders(
        "200 OK", [("Content-Type", "text/plain; charset=utf-8")], protocol="HTTP/1.1"
    )
    record = writer.create_warc_record(url, "response", payload=BytesIO(body), http_headers=headers)
    writer.write_record(record)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("datapackage.json", json.dumps({"created": created, "resources": []}))
        archive.writestr("archive/test.warc.gz", raw.getvalue())


def settings(tmp_path: Path) -> Settings:
    return Settings(
        token="test-token",
        crawls_dir=tmp_path / "crawls",
        data_dir=tmp_path / "data",
        scan_interval=1,
        max_content_bytes=32 * 1024 * 1024,
        mcp_inline_bytes=64 * 1024,
    )


def test_indexes_baseline_and_only_new_global_hashes(tmp_path: Path):
    config = settings(tmp_path)
    config.crawls_dir.mkdir(parents=True)
    repository = Repository(config.data_dir / "index.sqlite3")
    indexer = ArchiveIndexer(config, repository)

    first = config.crawls_dir / "first.wacz"
    second = config.crawls_dir / "second.wacz"
    make_wacz(first, "https://example.test/a", b"same", "2026-01-01T00:00:00Z")
    make_wacz(second, "https://example.test/b", b"same", "2026-01-02T00:00:00Z")

    indexer.index(read_metadata(first, validate=True))
    indexer.index(read_metadata(second, validate=True))

    first_crawl = repository.get_crawl("first")
    second_crawl = repository.get_crawl("second")
    assert first_crawl["baseline"] is True
    assert first_crawl["changeCount"] == 1
    assert second_crawl["baseline"] is False
    assert second_crawl["changeCount"] == 0


def test_content_over_limit_is_metadata_only(tmp_path: Path):
    config = settings(tmp_path)
    object.__setattr__(config, "max_content_bytes", 4)
    config.crawls_dir.mkdir(parents=True)
    repository = Repository(config.data_dir / "index.sqlite3")
    archive = config.crawls_dir / "large.wacz"
    make_wacz(archive, "https://example.test/large", b"12345", "2026-01-01T00:00:00Z")

    ArchiveIndexer(config, repository).index(read_metadata(archive, validate=True))
    changes = repository.list_changes("large", 0, 100)
    assert changes["items"][0]["contentUnsupported"] is True
    assert changes["items"][0]["stored"] is False
