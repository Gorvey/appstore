from starlette.datastructures import Headers

from change_api.auth import token_matches


def headers(value: str | None = None) -> Headers:
    raw = [] if value is None else [(b"authorization", value.encode())]
    return Headers(raw=raw)


def test_bearer_token_must_match_exactly():
    assert token_matches(headers("Bearer exact-token"), "exact-token")
    assert not token_matches(headers("bearer exact-token"), "exact-token")
    assert not token_matches(headers("Bearer Exact-token"), "exact-token")
    assert not token_matches(headers("Bearer exact-token "), "exact-token")
    assert not token_matches(headers("Bearer  exact-token"), "exact-token")
    assert not token_matches(headers(), "exact-token")


def test_multiple_authorization_headers_are_rejected():
    values = Headers(
        raw=[
            (b"authorization", b"Bearer exact-token"),
            (b"authorization", b"Bearer exact-token"),
        ]
    )
    assert not token_matches(values, "exact-token")
