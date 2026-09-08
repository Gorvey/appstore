# Browsertrix Crawler 配置选项报告

本报告对应镜像 `webrecorder/browsertrix-crawler:1.14.3`。该程序是任务型命令行爬虫，不提供常驻 Web 管理界面。本应用模板在安装后立即尝试第一轮；每轮完成后容器正常退出，由 Docker 重启容器、等待 `CRAWL_INTERVAL` 后再开始下一轮。重启进程命名空间可避免官方单次任务遗留的浏览器/代理状态污染下一轮。因此它是“上一轮结束后的固定间隔”，不是固定时刻的 Cron 表达式。

## 模板文件和默认行为

| 文件/设置 | 用途 | 模板默认值 |
| --- | --- | --- |
| `config/seeds.txt` | 多个种子站点，每行一个 HTTP(S) URL；空列表时每 60 秒重新检查 | 仅含注释示例 |
| `config/crawl-config.yml` | 官方 YAML 抓取配置；支持与 CLI 长参数同名的键 | 见下表 |
| `crawls/` | 持久化集合、WARC/WACZ、报告和中断状态 | 空目录 |
| `redis-data/` | 持久化跨轮内容哈希和 WACZ 依赖索引 | 空目录 |
| `change-api-data/` | 变更服务的 SQLite 索引和按哈希提取的正文 | 空目录 |
| `CRAWL_INTERVAL` | 一轮完成后到下一轮开始前的等待时间，接受 `sleep` 格式，如 `30m`、`6h`、`1d` | `24h` |
| `CHANGE_API_TOKEN` | REST 与 MCP 共用的 Bearer Token，必须严格匹配 | 安装时设置 |

## Agent 变更接口

应用内的 `change-api` 服务只读扫描完整 WACZ，将服务全局历史首次出现的 SHA-256 内容按抓取轮次建立索引。首个轮次标记为 baseline；同一正文对应多个 URL 时仅保存一份内容并记录全部出现位置。正文默认最多提取 32 MiB，超限资源仅提供元数据。

服务在容器内监听 `8080`，不映射宿主机端口。通过 1Panel 反向代理访问时，除 `/healthz` 外的 REST、OpenAPI 文档及 `/mcp` 均要求请求头 `Authorization: Bearer <CHANGE_API_TOKEN>`。REST 前缀为 `/api/v1`，MCP 使用 Streamable HTTP。

模板保留了官方 Compose 的 `NET_ADMIN`、`SYS_ADMIN` capabilities 和 `1gb` 共享内存。未映射宿主机端口；只有手动启用 screencast、调试或健康检查服务时才需要额外端口。

默认抓取配置：

| YAML 键 | 默认值 | 说明 |
| --- | --- | --- |
| `collection` | `crawl-@ts` | 每轮生成独立的时间戳集合，保留历史归档 |
| `scopeType` | `prefix` | 每个种子仅跟随同 URL 前缀的链接 |
| `pageLimit` | `100` | 每轮最多抓取 100 页；`0` 为无限制 |
| `workers` | `1` | 单浏览器工作进程，降低默认资源压力 |
| `pageLoadTimeout` | `90` | 单页加载超时，单位秒 |
| `generateWACZ` | `true` | 生成可回放的 WACZ |
| `text` | `[to-pages]` | 将初始页面文本写入 `pages.jsonl` |
| `dedupePagesMinDepth` | `-1` | 不跳过整个重复页面，保留页面资源和链接的完整发现 |
| `redisDedupeUrl` | `redis://redis:6379/0` | 使用应用内持久化 Redis 进行跨轮内容去重 |
| `saveState` | `partial` | 中断时保存恢复状态 |
| `reportSkipped` | `true` | 输出未入队 URL 报告 |

## 去重结论

单轮抓取内无需开启任何参数：

- 相同 URL 再次进入队列时会被跳过，不写 revisit 记录。
- 不同 URL 返回相同内容时，会按内容哈希写入较小的 WARC `revisit` 记录，引用第一次保存的响应。
- 多个种子站点由同一个 `crawl` 进程处理，所以同一轮中跨站点出现的相同内容也可参与内容去重。

`dedupePagesMinDepth` 是另一种更激进的优化。设为 `0` 或更大时，重复 HTML 页面在达到指定深度后会中止继续加载；它能节省时间，但也会跳过该页面的图片、样式和新链接。模板保持 `-1`，不启用此优化。若明确接受这一取舍，官方通常建议从 `1` 开始。

模板默认部署持久化 Redis，并在定时产生的不同轮次间复用内容哈希索引。后续 WACZ 中的 revisit 记录会通过 `relation.requires` 依赖较早的 WACZ；因此必须同时保留依赖链中的历史 WACZ，单独移动或删除早期文件会让重复资源无法完整回放。并发抓取才考虑 `dedupeConcurrent`，该选项在任务失败或取消时可能造成依赖数据缺失。

## `crawl` 支持的 YAML/CLI 参数

YAML 文件可使用 CLI 长参数名称作为键；命令行参数会覆盖 YAML。数组键在 YAML 中写成列表，布尔开关写成 `true`/`false`。

### 种子、范围与链接发现

| 参数 | 类型/默认值 | 作用 |
| --- | --- | --- |
| `seeds` / `url` | 数组 / `[]` | 起始 URL；本模板改用 `seedFile` |
| `seedFile` / `urlFile` | 字符串 | 每行一个 URL 的种子文件 |
| `depth` | 数字 / `-1` | 所有种子的抓取深度 |
| `extraHops` | 数字 / `0` | 超出当前范围仍允许跟随的跳数 |
| `scopeType` | `page`、`page-spa`、`prefix`、`host`、`domain`、`any`、`custom` | 预定义抓取范围 |
| `scopeIncludeRx` / `include` | 字符串 | 自定义纳入范围的 URL 正则 |
| `scopeExcludeRx` / `exclude` | 字符串 | 排除 URL 正则 |
| `allowHashUrls` | 布尔 / `false` | 允许带不同 hash 的 URL，适用于 SPA |
| `selectLinks` / `linkSelector` | 数组 / `[a[href]->href]` | 提取链接的 CSS 选择器和属性 |
| `alwaysAddBehaviorLinks` | 布尔 / `false` | 允许行为脚本添加超出范围的链接 |
| `useSitemap` / `sitemap` | 布尔或 URL | 读取默认或指定 sitemap |
| `sitemapFromDate`、`sitemapToDate` | ISO 日期 | 按 sitemap 日期过滤 |
| `addRedirectedSeeds` | 布尔 / `false` | 将重定向后的种子作为新种子 |

每个 `seeds` 项还可写成对象，单独设置 `url`、`depth`、`scopeType`、`include`、`exclude` 和 `auth`。

### 并发、等待与限制

| 参数 | 类型/默认值 | 作用 |
| --- | --- | --- |
| `workers` | 数字 / `1` | 并行浏览器 worker 数量 |
| `waitUntil` | 数组 / `[load, networkidle2]` | Puppeteer 页面就绪条件 |
| `pageLoadTimeout` / `timeout` | 秒 / `90` | 单页加载超时 |
| `behaviorTimeout` | 秒 / `90` | 页面行为最长运行时间，`0` 不限制 |
| `postLoadDelay` | 秒 / `0` | 页面加载后、后处理前额外等待 |
| `pageExtraDelay` / `delay` | 秒 / `0` | 每页行为完成后的限速等待 |
| `netIdleWait` | 秒 / `2` | 网络空闲等待时间 |
| `netIdleMaxRequests` | 数字 / `1` | 判断空闲时允许的最大活跃请求数 |
| `pageLimit` / `limit` | 数字 / `0` | 最大成功页面数，`0` 不限制 |
| `maxPageLimit` | 数字 / `0` | 覆盖并约束 `pageLimit` 的上限 |
| `sizeLimit` | 字节 / `0` | 输出大小上限，`0` 不限制 |
| `diskUtilization` | 百分比 / `0` | 达到磁盘占用率后保存状态并退出 |
| `timeLimit` | 秒 / `0` | 单轮总时长限制，`0` 不限制 |

### 输出、归档与元数据

| 参数 | 类型/默认值 | 作用 |
| --- | --- | --- |
| `collection` | 字符串 / `crawl-@ts` | 集合目录名，支持时间戳模板 |
| `generateWACZ` | 布尔 / `false` | 生成 WACZ |
| `generateCDX` | 布尔 / `false` | 生成合并 CDXJ 索引 |
| `combineWARC` | 布尔 / `false` | 合并 WARC 文件 |
| `rolloverSize` | 字节 / `1000000000` | WARC 分卷大小 |
| `useSHA1` | 布尔 / `false` | 使用 SHA-1，默认使用 SHA-256 |
| `text` | `to-pages`、`to-warc`、`final-to-warc` 数组 | 文本提取目标 |
| `screenshot` | `view`、`thumbnail`、`fullPage`、`fullPageFinal` 数组 | 页面截图类型 |
| `warcInfo` / `warcinfo` | 对象 | 自定义 warcinfo 字段 |
| `warcPrefix` | 字符串 | WARC 文件名前缀 |
| `title`、`description` / `desc` | 字符串 | WACZ 元数据标题和说明 |
| `statsFilename` | 字符串 | 统计 JSON 输出路径 |
| `saveStorage` | 布尔 | 将 localStorage/sessionStorage 写入元数据 |
| `dryRun` | 布尔 | 不写归档，仅写页面、日志和可选状态 |

### 浏览器、行为、拦截与代理

| 参数组 | 支持的键 |
| --- | --- |
| 浏览器 | `headless`、`driver`、`mobileDevice`、`userAgent`、`userAgentSuffix`、`lang`、`serviceWorker`、`extraChromeArgs` |
| 行为 | `behaviors`、`customBehaviors`、`clickSelector` |
| URL 拦截 | `blockRules`、`blockMessage`、`blockAds`、`adBlockMessage`、`originOverride` |
| Robots | `useRobots` / `robots`、`robotsAgent`（默认 `Browsertrix/1.x`） |
| 代理 | `proxyServer`、`proxyServerPreferSingleProxy`、`proxyServerConfig`、`sshProxyPrivateKeyFile`、`sshProxyKnownHostsFile` |
| 浏览器配置档 | `profile` / `loadProfile`、`saveProfile` |

默认行为列表是 `autoplay`、`autofetch`、`autoscroll`、`siteSpecific`；默认 `serviceWorker` 为 `disabled`。代理也可通过 `PROXY_SERVER`，或 `PROXY_HOST` + `PROXY_PORT` 环境变量设置。

### 去重、状态、容错与观测

| 参数组 | 支持的键 |
| --- | --- |
| 去重/Redis | `redisStoreUrl`、`redisDedupeUrl`、`dedupePagesMinDepth`、`dedupeConcurrent` |
| 状态 | `crawlId` / `id`、`saveState`、`saveStateInterval`、`saveStateHistory`、`overwrite`、`waitOnDone`、`restartsOnError` |
| 失败处理 | `maxPageRetries` / `retries`、`failOnFailedSeed`、`failOnFailedLimit`、`failOnInvalidStatus`、`failOnContentCheck` |
| 限流识别 | `rateLimitStatusCodes`、`rateLimitOnMatch`、`rateLimitTimeout`、`rateLimitMaxRetries`、`rateLimitInterruptCount` |
| 日志 | `logging`、`logLevel`、`context` / `logContext`、`logExcludeContext` |
| 报告/Redis 日志 | `reportSkipped`、`logErrorsToRedis`、`logBehaviorsToRedis`、`writePagesToRedis` |
| 调试/服务 | `screencastPort`、`screencastRedis`、`healthCheckPort`、`debugAccessRedis`、`debugAccessBrowser` |
| QA | `qaSource`、`qaDebugImageDiff` |

关键默认值：`redisStoreUrl=redis://localhost:6379/0`（内部状态 Redis）、`dedupePagesMinDepth=-1`、`dedupeConcurrent=false`、`saveState=partial`、`saveStateInterval=300`、`saveStateHistory=5`、`maxPageRetries=2`、限流状态码 `[403,429,503]`、`rateLimitTimeout=300`、`rateLimitMaxRetries=4`。

## 官方环境变量

| 环境变量 | 作用 |
| --- | --- |
| `CRAWL_ARGS`、`QA_ARGS` | 追加 crawler/QA 命令行参数 |
| `CRAWL_ID` | 抓取 ID，也用于上传回调 |
| `PROXY_SERVER`，或 `PROXY_HOST` + `PROXY_PORT` | 单代理配置 |
| `STORE_ENDPOINT_URL` | 启用 S3 兼容存储上传 |
| `STORE_ACCESS_KEY`、`STORE_SECRET_KEY` | S3 凭据 |
| `STORE_PATH`、`STORE_FILENAME`、`STORE_REGION` | S3 路径、文件名模板和区域；区域默认 `us-east-1` |
| `STORE_USER`、`WEBHOOK_URL` | 上传完成回调中的用户标识和 HTTP/Redis 回调地址 |
| `WACZ_SIGN_URL`、`WACZ_SIGN_TOKEN` | WACZ 签名服务及 Bearer Token |

这些高级项包含凭据或依赖外部服务，按本仓库规则未暴露在 1Panel 安装表单中，可按需直接添加到 Compose 环境变量。

## 其他入口点

- `create-login-profile`：支持 `url`、`user`、`password`、`filename`、`debugScreenshot`、`headless`、`automated`、`interactive`（已弃用）、`shutdownWait`、`postLoadDelay`、`profile`、`windowSize`、`cookieDays`、`proxyServer`、`proxyServerConfig`、`sshProxyPrivateKeyFile`、`sshProxyKnownHostsFile`。
- `indexer`：支持必填 `redisDedupeUrl`，以及 `sourceUrl`、`sourceCrawlId`、`removing`、`commitCrawlId`、`cancelCrawlId`，用于导入、提交、取消或清理跨轮去重索引。

## 来源

- [Browsertrix Crawler 用户指南](https://crawler.docs.browsertrix.com/user-guide/)
- [YAML 配置](https://crawler.docs.browsertrix.com/user-guide/yaml-config/)
- [全部命令行参数](https://crawler.docs.browsertrix.com/user-guide/cli-options/)
- [去重说明](https://crawler.docs.browsertrix.com/user-guide/dedupe/)
- [官方 Compose（v1.14.3）](https://github.com/webrecorder/browsertrix-crawler/blob/v1.14.3/docker-compose.yml)
