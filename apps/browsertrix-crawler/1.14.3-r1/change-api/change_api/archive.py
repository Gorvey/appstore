from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from warcio.archiveiterator import ArchiveIterator

from .config import Settings
from .db import Repository


logger = logging.getLogger("change_api.indexer")
HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class ArchiveMetadata:
    path: Path
    crawl_id: str
    collection: str
    created_at: str
    relation: dict
    size: int
    mtime_ns: int


@dataclass
class CapturedRecord:
    digest: str
    decoded_sha256: str | None
    size: int | None
    mime: str | None
    encoding: str | None
    stored_path: Path | None
    unsupported_reason: str | None
    url: str
    hostname: str
    captured_at: str | None
    http_status: int | None
    warc_type: str
    warc_filename: str
    record_id: str | None


class ArchiveIndexer:
    def __init__(self, settings: Settings, repository: Repository):
        self.settings = settings
        self.repository = repository
        self._observed: dict[Path, tuple[int, int]] = {}
        self._attempted: dict[Path, tuple[int, int]] = {}

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.scan_once)
            except Exception as exc:  # pragma: no cover - defensive task boundary
                logger.error("archive scan failed: %s", type(exc).__name__)
            await asyncio.sleep(self.settings.scan_interval)

    def scan_once(self) -> None:
        paths = sorted(self.settings.crawls_dir.glob("collections/**/*.wacz"))
        self._reconcile_availability(paths)
        candidates: list[ArchiveMetadata] = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            signature = (stat.st_size, stat.st_mtime_ns)
            if self._observed.get(path) != signature:
                self._observed[path] = signature
                continue
            if self._attempted.get(path) == signature:
                continue
            try:
                candidates.append(read_metadata(path, validate=True))
            except Exception as exc:
                self._attempted[path] = signature
                self._record_failure(path, signature, exc)

        for metadata in sorted(candidates, key=lambda item: (item.created_at, item.crawl_id)):
            signature = (metadata.size, metadata.mtime_ns)
            self._attempted[metadata.path] = signature
            try:
                self.index(metadata)
                logger.info("archive indexed: crawl_id=%s", metadata.crawl_id)
            except Exception as exc:
                self._record_failure(metadata.path, signature, exc, metadata)

    def index(self, metadata: ArchiveMetadata) -> None:
        with self.repository.connect() as connection:
            existing = connection.execute(
                "SELECT status, wacz_size, wacz_mtime_ns FROM crawls WHERE crawl_id = ?",
                (metadata.crawl_id,),
            ).fetchone()
            if existing and existing["status"] == "ready":
                if (
                    existing["wacz_size"] != metadata.size
                    or existing["wacz_mtime_ns"] != metadata.mtime_ns
                ):
                    connection.execute(
                        """UPDATE crawls SET archive_available = 0,
                                  error = 'archive changed after indexing'
                           WHERE crawl_id = ?""",
                        (metadata.crawl_id,),
                    )
                return

            baseline = self.repository.ready_count(connection) == 0
            connection.execute(
                """INSERT INTO crawls
                   (crawl_id, collection, created_at, wacz_path, wacz_size,
                    wacz_mtime_ns, status, baseline, archive_available,
                    relation_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, 'indexing', ?, 1, ?, NULL)
                   ON CONFLICT(crawl_id) DO UPDATE SET
                     collection = excluded.collection,
                     created_at = excluded.created_at,
                     wacz_path = excluded.wacz_path,
                     wacz_size = excluded.wacz_size,
                     wacz_mtime_ns = excluded.wacz_mtime_ns,
                     status = 'indexing',
                     baseline = excluded.baseline,
                     archive_available = 1,
                     relation_json = excluded.relation_json,
                     error = NULL""",
                (
                    metadata.crawl_id,
                    metadata.collection,
                    metadata.created_at,
                    str(metadata.path),
                    metadata.size,
                    metadata.mtime_ns,
                    int(baseline),
                    json.dumps(metadata.relation, separators=(",", ":")),
                ),
            )

            for captured in iter_records(metadata.path, self.settings):
                self._store_record(connection, metadata.crawl_id, captured)

            connection.execute(
                """UPDATE crawls SET status = 'ready', indexed_at = CURRENT_TIMESTAMP,
                          archive_available = 1, error = NULL
                   WHERE crawl_id = ?""",
                (metadata.crawl_id,),
            )

    def _store_record(
        self, connection: sqlite3.Connection, crawl_id: str, captured: CapturedRecord
    ) -> None:
        existing = connection.execute(
            "SELECT stored FROM contents WHERE digest = ?", (captured.digest,)
        ).fetchone()
        is_new = existing is None
        if is_new:
            connection.execute(
                """INSERT INTO contents
                   (digest, size, mime, encoding, stored, content_path,
                    unsupported_reason, decoded_sha256, first_crawl_id, first_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    captured.digest,
                    captured.size,
                    captured.mime,
                    captured.encoding,
                    int(captured.stored_path is not None),
                    _relative_content_path(captured.stored_path, self.settings.data_dir),
                    captured.unsupported_reason,
                    captured.decoded_sha256,
                    crawl_id,
                    captured.url,
                ),
            )
            if captured.warc_type == "response":
                connection.execute(
                    "INSERT INTO crawl_changes (crawl_id, digest) VALUES (?, ?)",
                    (crawl_id, captured.digest),
                )
        elif captured.stored_path is not None and not existing["stored"]:
            connection.execute(
                """UPDATE contents SET size = ?, mime = ?, encoding = ?, stored = 1,
                          content_path = ?, unsupported_reason = NULL,
                          decoded_sha256 = ? WHERE digest = ?""",
                (
                    captured.size,
                    captured.mime,
                    captured.encoding,
                    _relative_content_path(captured.stored_path, self.settings.data_dir),
                    captured.decoded_sha256,
                    captured.digest,
                ),
            )
        connection.execute(
            """INSERT OR IGNORE INTO occurrences
               (crawl_id, digest, url, hostname, captured_at, http_status, mime,
                warc_type, warc_filename, record_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                crawl_id,
                captured.digest,
                captured.url,
                captured.hostname,
                captured.captured_at,
                captured.http_status,
                captured.mime,
                captured.warc_type,
                captured.warc_filename,
                captured.record_id,
            ),
        )

    def _record_failure(
        self,
        path: Path,
        signature: tuple[int, int],
        error: Exception,
        metadata: ArchiveMetadata | None = None,
    ) -> None:
        crawl_id = metadata.crawl_id if metadata else path.stem
        collection = metadata.collection if metadata else path.parent.name
        created_at = (
            metadata.created_at
            if metadata
            else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        )
        relation = metadata.relation if metadata else {}
        safe_error = type(error).__name__
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO crawls
                   (crawl_id, collection, created_at, wacz_path, wacz_size,
                    wacz_mtime_ns, status, archive_available, relation_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, 'failed', 0, ?, ?)
                   ON CONFLICT(crawl_id) DO UPDATE SET
                     status = 'failed', archive_available = 0,
                     wacz_size = excluded.wacz_size,
                     wacz_mtime_ns = excluded.wacz_mtime_ns,
                     error = excluded.error""",
                (
                    crawl_id,
                    collection,
                    created_at,
                    str(path),
                    signature[0],
                    signature[1],
                    json.dumps(relation, separators=(",", ":")),
                    safe_error,
                ),
            )
        logger.error("archive indexing failed: crawl_id=%s error=%s", crawl_id, safe_error)

    def _reconcile_availability(self, paths: list[Path]) -> None:
        available = {str(path) for path in paths}
        with self.repository.connect() as connection:
            rows = connection.execute(
                "SELECT crawl_id, wacz_path FROM crawls WHERE status = 'ready'"
            ).fetchall()
            for row in rows:
                is_available = row["wacz_path"] in available
                connection.execute(
                    "UPDATE crawls SET archive_available = ? WHERE crawl_id = ?",
                    (int(is_available), row["crawl_id"]),
                )


def read_metadata(path: Path, validate: bool) -> ArchiveMetadata:
    stat = path.stat()
    with zipfile.ZipFile(path) as archive:
        if validate:
            corrupt = archive.testzip()
            if corrupt:
                raise zipfile.BadZipFile("WACZ contains a corrupt member")
        package = json.loads(archive.read("datapackage.json"))
        if not any(name.endswith(".warc.gz") for name in archive.namelist()):
            raise ValueError("WACZ has no WARC resources")
    created_at = package.get("created") or datetime.fromtimestamp(
        stat.st_mtime, timezone.utc
    ).isoformat()
    return ArchiveMetadata(
        path=path,
        crawl_id=path.stem,
        collection=path.parent.name,
        created_at=created_at,
        relation=package.get("relation") or {},
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def iter_records(path: Path, settings: Settings):
    with zipfile.ZipFile(path) as archive:
        warc_names = sorted(
            name for name in archive.namelist() if name.endswith(".warc.gz")
        )
        for warc_name in warc_names:
            with archive.open(warc_name) as compressed:
                with gzip.GzipFile(fileobj=compressed) as stream:
                    for record in ArchiveIterator(stream):
                        warc_type = record.rec_type
                        if warc_type not in {"response", "revisit"}:
                            continue
                        captured = _capture_record(record, warc_name, settings)
                        if captured is not None:
                            yield captured


def _capture_record(record, warc_name: str, settings: Settings) -> CapturedRecord | None:
    url = record.rec_headers.get_header("WARC-Target-URI") or ""
    if not url:
        return None
    expected_digest = normalize_digest(
        record.rec_headers.get_header("WARC-Payload-Digest")
    )
    mime, encoding = parse_content_type(
        record.http_headers.get_header("Content-Type") if record.http_headers else None
    )
    status = parse_status(record.http_headers.statusline if record.http_headers else None)
    stored_path = None
    unsupported_reason = None
    decoded_digest = None
    size = None

    if record.rec_type == "response":
        stored_path, size, decoded_digest, unsupported_reason = extract_payload(
            record.content_stream(), settings
        )
        digest = expected_digest or decoded_digest
        if not digest:
            if stored_path:
                stored_path.unlink(missing_ok=True)
            return None
        if stored_path:
            final_path = content_path(settings.data_dir, digest)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if final_path.exists():
                stored_path.unlink(missing_ok=True)
                stored_path = final_path
            else:
                os.replace(stored_path, final_path)
                stored_path = final_path
    else:
        if not expected_digest:
            return None
        digest = expected_digest

    return CapturedRecord(
        digest=digest,
        decoded_sha256=decoded_digest,
        size=size,
        mime=mime,
        encoding=encoding,
        stored_path=stored_path,
        unsupported_reason=unsupported_reason,
        url=url,
        hostname=(urlsplit(url).hostname or "").lower(),
        captured_at=record.rec_headers.get_header("WARC-Date"),
        http_status=status,
        warc_type=record.rec_type,
        warc_filename=warc_name,
        record_id=record.rec_headers.get_header("WARC-Record-ID"),
    )


def extract_payload(stream, settings: Settings) -> tuple[Path | None, int, str, str | None]:
    temp_dir = settings.data_dir / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    supported = True
    with tempfile.NamedTemporaryFile(dir=temp_dir, delete=False) as output:
        temp_path = Path(output.name)
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            if supported and size <= settings.max_content_bytes:
                output.write(chunk)
            elif supported:
                supported = False
    if not supported:
        temp_path.unlink(missing_ok=True)
        return None, size, digest.hexdigest(), "content exceeds configured limit"
    return temp_path, size, digest.hexdigest(), None


def normalize_digest(value: str | None) -> str | None:
    if not value:
        return None
    algorithm, separator, encoded = value.partition(":")
    if separator and algorithm.lower() != "sha256":
        return None
    candidate = encoded if separator else algorithm
    if HEX_64.fullmatch(candidate):
        return candidate.lower()
    try:
        padded = candidate.upper() + "=" * (-len(candidate) % 8)
        decoded = base64.b32decode(padded)
    except Exception:
        return None
    return decoded.hex() if len(decoded) == 32 else None


def parse_content_type(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parts = [part.strip() for part in value.split(";")]
    mime = parts[0].lower() or None
    encoding = None
    for part in parts[1:]:
        key, separator, current = part.partition("=")
        if separator and key.strip().lower() == "charset":
            encoding = current.strip().strip('"') or None
    return mime, encoding


def parse_status(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.split(None, 1)[0])
    except (ValueError, IndexError):
        return None


def content_path(data_dir: Path, digest: str) -> Path:
    return data_dir / "content" / "sha256" / digest[:2] / digest


def _relative_content_path(path: Path | None, data_dir: Path) -> str | None:
    return str(path.relative_to(data_dir)) if path else None
