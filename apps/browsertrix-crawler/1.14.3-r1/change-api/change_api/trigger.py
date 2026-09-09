from pathlib import Path


def request_crawl(control_dir: Path) -> dict:
    """Persist one pending crawl; concurrent requests share the same queue slot."""
    try:
        (control_dir / "pending").mkdir()
    except FileExistsError:
        return {"status": "queued", "coalesced": True}
    return {"status": "queued", "coalesced": False}
