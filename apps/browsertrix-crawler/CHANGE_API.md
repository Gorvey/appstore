# Browsertrix Change API

`change-api` 将每轮完整 WACZ 中首次出现的 SHA-256 正文提取为 Agent 可查询的结构化数据。它不把新哈希猜测为“新增文件”或“修改文件”；同一哈希可关联多个实际抓取 URL。

## 认证

除 `/healthz` 外，所有请求都必须携带安装时配置的 Token：

```http
Authorization: Bearer <CHANGE_API_TOKEN>
```

Token 区分大小写并严格比较。不接受查询参数、Cookie、前后空格或其他认证头。OpenAPI 文档位于 `/api/v1/docs`。

## REST API

| 方法与路径 | 用途 |
| --- | --- |
| `GET /healthz` | 无敏感信息的存活检查，无需认证 |
| `GET /api/v1/crawls` | 分页列出已经完成索引的抓取轮次 |
| `GET /api/v1/crawls/{crawlId}` | 获取轮次状态、baseline、统计和 WACZ 依赖 |
| `GET /api/v1/crawls/{crawlId}/changes` | 获取该轮首次出现的内容哈希 |
| `GET /api/v1/contents/{digest}/metadata` | 获取内容元数据及全部出现位置 |
| `GET /api/v1/contents/{digest}` | 下载解码后的 HTTP payload |
| `GET /api/v1/urls/history?url=...` | 按未经规范化的完整 URL 查询历史 |

列表接口默认每页 100 条，最多 500 条。响应中的 `nextCursor` 由 Agent 保存并原样传回 `cursor`。变更列表支持 `hostname`、`mime`、`status` 和 `urlPrefix` 过滤。

正文接口强制以附件和 `application/octet-stream` 返回，同时通过 `X-Original-Content-Type` 标注原 MIME。超过 32 MiB 的正文仅保留元数据，正文请求返回 HTTP 413。

## MCP

Streamable HTTP 入口为 `/mcp`，使用同一个 Bearer Token，提供：

- `list_crawls`
- `get_crawl`
- `list_changed_contents`
- `get_content`
- `get_url_history`

不超过 64 KiB 的文本可由 `get_content` 直接内联返回；更大的文本和二进制返回受认证保护的 REST 路径。

当前项目已在 `.codex/config.toml` 中配置远程 MCP。使用前在启动 Codex 的本机环境设置 Token，配置文件不会保存实际密钥：

```bash
export BROWSERTRIX_CHANGE_API_TOKEN='<CHANGE_API_TOKEN>'
```

重新启动或重新载入项目后，Codex 将通过 `https://browsertrix-crawler.cooool.fun/mcp` 连接。

## 数据与保留

服务只读挂载 `crawls/`，将 SQLite 和提取正文写入 `change-api-data/`。归档至少连续两次扫描保持大小及修改时间不变，并通过 ZIP、`datapackage.json` 和 WARC 检查后才会发布为 ready。默认不自动删除归档、索引或正文。
