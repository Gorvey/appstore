from pathlib import Path

from change_api.db import Repository, decode_cursor, encode_cursor


def test_cursor_round_trip_and_validation():
    assert decode_cursor(encode_cursor(123)) == 123
    assert decode_cursor(None) == 0

    try:
        decode_cursor("not-a-cursor")
    except ValueError as exc:
        assert str(exc) == "invalid cursor"
    else:
        raise AssertionError("invalid cursor was accepted")


def test_change_list_groups_occurrences_by_digest(tmp_path: Path):
    repository = Repository(tmp_path / "index.sqlite3")
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO crawls
               (crawl_id, collection, created_at, wacz_path, wacz_size,
                wacz_mtime_ns, status, baseline)
               VALUES ('crawl-1', 'crawl-1', '2026-01-01T00:00:00Z',
                       '/crawls/crawl-1.wacz', 1, 1, 'ready', 1)"""
        )
        connection.execute(
            """INSERT INTO contents
               (digest, size, mime, stored, first_crawl_id, first_url)
               VALUES ('abc', 5, 'text/plain', 1, 'crawl-1', 'https://a.test/a')"""
        )
        connection.execute(
            "INSERT INTO crawl_changes (crawl_id, digest) VALUES ('crawl-1', 'abc')"
        )
        for url in ("https://a.test/a", "https://a.test/b"):
            connection.execute(
                """INSERT INTO occurrences
                   (crawl_id, digest, url, hostname, http_status, mime, warc_type)
                   VALUES ('crawl-1', 'abc', ?, 'a.test', 200, 'text/plain', 'response')""",
                (url,),
            )

    result = repository.list_changes("crawl-1", 0, 100, hostname="a.test")
    assert len(result["items"]) == 1
    assert len(result["items"][0]["occurrences"]) == 2
    assert result["nextCursor"] is None
