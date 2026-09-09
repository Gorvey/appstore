## 产品介绍

**Browsertrix Crawler** 是 Webrecorder 推出的高保真浏览器式网络爬虫，可在单个 Docker 容器中并行运行浏览器并生成 WARC/WACZ 网页归档。本模板支持多站点列表和按间隔循环抓取。

## 主要功能

- **多站点定时抓取**：通过 seeds.txt 配置多个种子 URL，每轮完成后按设定间隔自动开始下一轮。
- **跨轮自动去重**：使用持久化 Redis 内容索引，按内容哈希写入 WARC revisit 记录，减少定时重复抓取的存储占用。
- **可回放归档**：默认生成 WACZ 文件，并将抓取结果持久化到本地目录。
- **Agent 变更接口**：自动索引每轮新增内容哈希，通过受 Token 保护的 REST API 和 MCP 提供变更列表、正文及 URL 历史。

- **主动抓取**：通过 REST `POST /api/v1/crawls` 或 MCP `trigger_crawl` 请求立即抓取；忙碌时排队，重复待处理请求合并。详见 [接口说明](CHANGE_API.md)。
