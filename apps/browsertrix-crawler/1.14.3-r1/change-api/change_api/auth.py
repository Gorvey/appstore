from __future__ import annotations

import hmac

from starlette.datastructures import Headers


def token_matches(headers: Headers, expected: str) -> bool:
    """Accept exactly one canonical Bearer header and compare its token strictly."""
    values = headers.getlist("authorization")
    if len(values) != 1:
        return False
    value = values[0]
    prefix = "Bearer "
    if not value.startswith(prefix):
        return False
    supplied = value[len(prefix) :]
    if not supplied or supplied != supplied.strip():
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
