import asyncio
import importlib
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from change_api.trigger import request_crawl


def test_concurrent_requests_coalesce_and_can_be_consumed(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: request_crawl(tmp_path), range(20)))
    assert sum(not result["coalesced"] for result in results) == 1
    assert all(result["status"] == "queued" for result in results)
    (tmp_path / "pending").rmdir()
    assert request_crawl(tmp_path)["coalesced"] is False


def test_rest_and_mcp_share_authenticated_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANGE_API_TOKEN", "test-token")
    monkeypatch.setenv("CHANGE_API_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CHANGE_API_CONTROL_DIR", str(tmp_path))
    main = importlib.import_module("change_api.main")
    monkeypatch.setattr(main, "settings", main.Settings.from_env())
    client = TestClient(main.app)
    assert client.post("/api/v1/crawls").status_code == 401
    assert not (tmp_path / "pending").exists()
    response = client.post(
        "/api/v1/crawls", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 202
    assert response.json() == {"status": "queued", "coalesced": False}
    assert main.trigger_crawl_tool() == {"status": "queued", "coalesced": True}
    assert "trigger_crawl" in [tool.name for tool in asyncio.run(main.mcp.list_tools())]
    (tmp_path / "pending").rmdir()
    # Missing deployment mount must fail explicitly rather than acknowledge a request.
    monkeypatch.setenv("CHANGE_API_CONTROL_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(main, "settings", main.Settings.from_env())
    assert client.post(
        "/api/v1/crawls", headers={"Authorization": "Bearer test-token"}
    ).status_code == 503
