# Repository Guidelines

## 项目结构与模块组织

本仓库是 1Panel 第三方本地应用商店配置集合，核心内容位于 `apps/`。每个应用使用独立目录，例如 `apps/answer/`，通常包含应用级 `data.yml`、`README.md`、`logo.png`，以及一个或多个版本目录。版本目录可命名为 `latest`、具体版本号或变体名，内部放置 `docker-compose.yml`、版本级 `data.yml`，可选 `env.sample`、`scripts/`、`data/` 等运行资源。`docs/` 保存 README 图片素材，`.github/workflows/` 主要用于 Renovate 自动更新。

## 构建、测试与本地开发命令

本仓库没有统一构建步骤。新增或修改应用时，优先在对应版本目录验证：

```bash
docker compose -f apps/answer/latest/docker-compose.yml config
docker compose -f apps/answer/latest/docker-compose.yml up -d
docker compose -f apps/answer/latest/docker-compose.yml down
```

第一条用于检查 Compose 语法和变量引用；后两条用于本地试运行与清理。提交前可用 `git diff -- apps/<app>/` 复核只改动目标应用。

## 编码风格与命名约定

YAML 使用 2 空格缩进，保持键名与现有样例一致。应用目录使用小写字母、数字和连字符，例如 `chatgpt-next-web`。Compose 主服务必须使用 `container_name: ${CONTAINER_NAME}`，持久化目录优先使用相对路径，例如 `./data:/app/data`。镜像标签应明确；自用应用可按需求保留官方 `latest`。

## 应用打包定制规则

创建新应用时只保留一个 `latest` 版本目录，不生成历史版本目录。根 `data.yml` 中设置 `crossVersionUpdate: false`，应用更新不走 1Panel App 的多版本更新逻辑。

默认不配置 `ports`、`PANEL_APP_PORT_*` 或宿主机端口映射。服务加入 `1panel-network`，通过 `expose` 标注容器端口即可，由反向代理访问容器端口。只有在用户明确要求，或官方应用必须通过监听 `127.0.0.1`、`0.0.0.0`、宿主机端口才能正常运行时，才添加端口相关配置，并在说明中写清原因。

安装表单尽可能保持极简。默认隐藏数据库账号、内部 Token、认证密钥、SMTP、OAuth、S3、AI Provider 等可自动生成或后续在应用内配置的选项；需要密钥时优先通过 `scripts/init.sh` 首次启动前生成本地 `.env`，并避免覆盖已存在的配置。若确实需要在表单中暴露配置，通常只保留一个服务访问端口字段，例如 `PANEL_APP_PORT_HTTP`，不要把内部服务端口或非必要高级配置暴露给用户。

如果应用需要 `TZ`、`TIME_ZONE` 等时区变量，默认跟随 VPS 时区，不把时区做成安装表单项。优先使用容器或宿主环境已有时区；必须显式传入时，使用部署目标 VPS 的时区作为默认值，并避免写死与目标环境不符的时区。

## 测试指南

没有集中式测试框架。每次改动至少运行 `docker compose config`，并确认 `data.yml` 中的 `additionalProperties.key` 与应用目录一致。涉及脚本时，检查 `scripts/*.sh` 可执行逻辑、路径和环境变量，不要写死本机路径。能启动的应用应完成一次 `up -d` 冒烟测试。

## Commit 与 Pull Request 规范

近期提交使用 `feat(scope): ...`、`Update app version [skip ci]`、Renovate 自动更新和合并提交。人工提交建议使用简短英文摘要，例如 `feat(hermes): add uid gid migration support`。PR 应说明新增或更新的应用、镜像来源、测试命令结果、兼容架构，并在界面或端口行为变化时附截图或简要说明。仅提交与目标应用相关的文件。

## 安全与配置提示

不要提交真实 Token、密码、私钥或本地数据库。示例配置使用占位值或 `env.sample`。对外暴露端口、特权模式、宿主机挂载和 `network_mode: host` 需要在 PR 描述中说明理由。
