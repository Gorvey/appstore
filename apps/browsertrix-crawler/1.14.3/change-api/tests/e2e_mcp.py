import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def result_json(result):
    assert result.content and result.content[0].type == "text"
    return json.loads(result.content[0].text)


async def main() -> None:
    headers = {"Authorization": "Bearer e2e-strict-token"}
    async with streamablehttp_client(
        "http://127.0.0.1:8080/mcp", headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            expected = [
                "get_content",
                "get_crawl",
                "get_url_history",
                "list_changed_contents",
                "list_crawls",
                "trigger_crawl",
            ]
            assert names == expected, names

            crawls = await session.call_tool("list_crawls", {"limit": 10})
            assert not crawls.isError
            structured = result_json(crawls)
            ids = [item["crawlId"] for item in structured["items"]]
            assert ids == ["localhost-before-update", "localhost-after-update"]

            changes = await session.call_tool(
                "list_changed_contents",
                {"crawl_id": "localhost-after-update", "limit": 2},
            )
            assert not changes.isError
            change_data = result_json(changes)
            assert len(change_data["items"]) == 2
            large_digest = change_data["items"][0]["digest"]
            small_digest = change_data["items"][1]["digest"]

            large_content = await session.call_tool(
                "get_content", {"digest": large_digest}
            )
            assert not large_content.isError
            large_content_data = result_json(large_content)
            assert large_content_data["delivery"] == "rest"

            small_content = await session.call_tool(
                "get_content", {"digest": small_digest}
            )
            assert not small_content.isError
            small_content_data = result_json(small_content)
            assert small_content_data["delivery"] == "inline"
            assert small_content_data["text"]

            print(
                json.dumps(
                    {
                        "tools": names,
                        "crawls": ids,
                        "changeSampleCount": len(change_data["items"]),
                        "largeContentDelivery": large_content_data["delivery"],
                        "smallContentDelivery": small_content_data["delivery"],
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
