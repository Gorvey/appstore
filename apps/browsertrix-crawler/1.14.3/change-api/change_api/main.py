import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from mcp.server.fastmcp import FastMCP

from . import __version__
from .archive import ArchiveIndexer
from .auth import token_matches
from .config import Settings
from .db import Repository, decode_cursor


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = Settings.from_env()
settings.data_dir.mkdir(parents=True, exist_ok=True)
repository = Repository(settings.data_dir / "index.sqlite3")
indexer = ArchiveIndexer(settings, repository)

mcp = FastMCP(
    "Browsertrix Change API",
    instructions=(
        "Query Browsertrix crawl rounds and retrieve content hashes that were first "
        "observed in each round. Save returned cursors on the client side."
    ),
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _cursor(value: str | None) -> int:
    try:
        return decode_cursor(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ensure_crawl_ready(crawl_id: str) -> dict:
    crawl = repository.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(status_code=404, detail="crawl not found")
    if crawl["status"] != "ready":
        raise HTTPException(status_code=409, detail="crawl is not ready")
    return crawl


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        task = asyncio.create_task(indexer.run(), name="archive-indexer")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Browsertrix Change API",
    version=__version__,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path == "/healthz":
        return await call_next(request)
    if not token_matches(request.headers, settings.token):
        return JSONResponse(
            status_code=401,
            content={"detail": "unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


@app.get("/healthz", include_in_schema=False)
def healthz():
    repository.ready_count()
    return {"status": "ok"}


@app.get("/api/v1/crawls")
def list_crawls(
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    return repository.list_crawls(_cursor(cursor), limit)


@app.get("/api/v1/crawls/{crawl_id}")
def get_crawl(crawl_id: str):
    crawl = repository.get_crawl(crawl_id)
    if not crawl:
        raise HTTPException(status_code=404, detail="crawl not found")
    return crawl


@app.get("/api/v1/crawls/{crawl_id}/changes")
def list_changes(
    crawl_id: str,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    hostname: str | None = None,
    mime: str | None = None,
    status: int | None = Query(default=None, ge=100, le=599),
    url_prefix: str | None = Query(default=None, alias="urlPrefix"),
):
    crawl = _ensure_crawl_ready(crawl_id)
    result = repository.list_changes(
        crawl_id,
        _cursor(cursor),
        limit,
        hostname=hostname,
        mime=mime,
        status=status,
        url_prefix=url_prefix,
    )
    result["crawl"] = crawl
    return result


@app.get("/api/v1/contents/{digest}/metadata")
def content_metadata(digest: str):
    content = repository.get_content(digest.lower())
    if not content:
        raise HTTPException(status_code=404, detail="content not found")
    return content


@app.get("/api/v1/contents/{digest}")
def content_body(digest: str):
    normalized = digest.lower()
    content = repository.get_content(normalized)
    if not content:
        raise HTTPException(status_code=404, detail="content not found")
    if content["contentUnsupported"]:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "content_unsupported",
                "reason": content["unsupportedReason"],
                "size": content["size"],
            },
        )
    row_path = _stored_path(normalized)
    if not row_path.is_file():
        raise HTTPException(status_code=410, detail="extracted content is unavailable")
    headers = {
        "Content-Disposition": f'attachment; filename="{normalized}"',
        "X-Content-Type-Options": "nosniff",
        "X-Original-Content-Type": content["mime"] or "application/octet-stream",
        "ETag": f'"sha256:{normalized}"',
    }
    return FileResponse(row_path, media_type="application/octet-stream", headers=headers)


@app.get("/api/v1/urls/history")
def url_history(
    url: str = Query(min_length=1),
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    return repository.url_history(url, _cursor(cursor), limit)


def _stored_path(digest: str) -> Path:
    content = repository.get_content(digest)
    if not content or not content["stored"]:
        return settings.data_dir / "missing"
    return settings.data_dir / "content" / "sha256" / digest[:2] / digest


@mcp.tool(name="list_crawls")
def list_crawls_tool(cursor: str | None = None, limit: int = 100) -> dict:
    """List ready crawl rounds using a client-owned opaque cursor."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    return repository.list_crawls(decode_cursor(cursor), limit)


@mcp.tool(name="get_crawl")
def get_crawl_tool(crawl_id: str) -> dict:
    """Get metadata and indexing status for one crawl round."""
    crawl = repository.get_crawl(crawl_id)
    if not crawl:
        raise ValueError("crawl not found")
    return crawl


@mcp.tool()
def list_changed_contents(
    crawl_id: str,
    cursor: str | None = None,
    limit: int = 100,
    hostname: str | None = None,
    mime: str | None = None,
    status: int | None = None,
    url_prefix: str | None = None,
) -> dict:
    """List globally new content hashes first observed in a crawl round."""
    crawl = repository.get_crawl(crawl_id)
    if not crawl or crawl["status"] != "ready":
        raise ValueError("crawl is not ready or does not exist")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    return repository.list_changes(
        crawl_id,
        decode_cursor(cursor),
        limit,
        hostname=hostname,
        mime=mime,
        status=status,
        url_prefix=url_prefix,
    )


@mcp.tool()
def get_content(digest: str) -> dict:
    """Return small text inline, or metadata and an authenticated REST path."""
    normalized = digest.lower()
    content = repository.get_content(normalized)
    if not content:
        raise ValueError("content not found")
    result = {"metadata": content}
    if content["contentUnsupported"]:
        result["delivery"] = "unsupported"
        return result
    path = _stored_path(normalized)
    if not path.is_file():
        result["delivery"] = "unavailable"
        return result
    mime = content["mime"] or ""
    is_text = mime.startswith("text/") or mime in {
        "application/json",
        "application/javascript",
        "application/ld+json",
        "application/xml",
        "application/xhtml+xml",
    }
    if is_text and path.stat().st_size <= settings.mcp_inline_bytes:
        encoding = content["encoding"] or "utf-8"
        try:
            text = path.read_text(encoding=encoding, errors="replace")
        except LookupError:
            text = path.read_text(encoding="utf-8", errors="replace")
        result.update({"delivery": "inline", "text": text})
    else:
        result.update(
            {
                "delivery": "rest",
                "contentUrl": f"/api/v1/contents/{normalized}",
            }
        )
    return result


@mcp.tool()
def get_url_history(
    url: str, cursor: str | None = None, limit: int = 100
) -> dict:
    """Get exact-URL capture history without normalizing query parameters."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    return repository.url_history(url, decode_cursor(cursor), limit)


# Mount last so REST and health routes retain precedence. The MCP app owns /mcp.
app.mount("/", mcp.streamable_http_app())
