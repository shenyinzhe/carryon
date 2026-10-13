# Carry-On

**换 AI 订阅，不丢记忆。** 把 ChatGPT / Claude / Gemini 的官方导出合并成一个可搜索的库，放在自己的设备上，
通过 [MCP](https://modelcontextprotocol.io) 提供给任何一家 AI：今天用哪家，都能查到你和其他几家聊过什么。

以 Home Assistant add-on 或普通 Docker 容器运行（aarch64 / amd64），内置可选的 Tailscale Funnel，无需域名和端口转发，
claude.ai 和 chatgpt.com 的网页端连接器即可直接访问。

[English](README.md)

## 1. 安装
[![添加仓库到 Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fshenyinzhe%2Fcarryon)

或在加载项商店 → 右上角 ⋮ → 仓库，添加 `https://github.com/shenyinzhe/carryon`，然后安装 **Carry-On**
（直接拉取预构建镜像，几秒完成）。

配置页填 `secret`：在电脑上运行 `python -c "import secrets;print(secrets.token_urlsafe(32))"` 生成。启动。

**不用 Home Assistant**：用 Docker 运行。
```bash
curl -O https://raw.githubusercontent.com/shenyinzhe/carryon/main/compose.yaml
echo "CARRYON_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > .env
docker compose up -d
```
导出的 zip 放进 `./share/inbox/`，本机地址是 `http://127.0.0.1:8765/<secret>/mcp`。下文的 add-on 选项对应环境变量
`CARRYON_SECRET`、`CARRYON_TAILSCALE_FUNNEL`、`CARRYON_TAILSCALE_HOSTNAME`（写进 `.env`），
Tailscale 登录链接在 `docker compose logs` 里。

## 2. 导入记录
把导出的 zip 原样放进 `share/carryon/inbox/`（Samba 的 `share` 目录）。
add-on 每 5 分钟扫描一次，导入后移到 `share/carryon/imported/`。日志里能看到导入数量。
以后定期重新导出、再丢进去即可：按会话 id + 更新时间去重，只增量更新。

| 来源 | 导出 |
|---|---|
| ChatGPT | Settings → Data controls → Export data |
| Claude | Settings → Privacy → Export data |
| Gemini | Takeout → My Activity（JSON 格式）→ 只勾 Gemini Apps |

## 3. 对外暴露（内置 Tailscale Funnel，免费、无需域名）
1. add-on 配置里打开 `tailscale_funnel`（`tailscale_hostname` 默认 `carryon`），重启。
2. 日志里出现 `To authenticate, visit: https://login.tailscale.com/...`，打开并登录 Tailscale，批准设备。
3. 若提示 `Funnel is not enabled on your tailnet`，打开给出的链接启用 Funnel。
4. 日志打印 `public endpoint: https://carryon.<tailnet>.ts.net/<secret>/mcp`。新域名的公网 DNS 可能要几分钟才生效。

Tailscale 以用户态运行在 add-on 容器内，只转发到容器内的 8765 端口；登录状态保存在 add-on 的 `/data/tailscale`。
tailscaled 的输出被丢弃（可能含请求路径，即 secret）。**不要**在路由器上做端口转发。

整个 MCP 地址 `https://carryon.<tailnet>.ts.net/<secret>/mcp` 等同于密码。

## 4. 接入
- **Claude**：Settings → Connectors → Add custom connector，填上面的 URL。
- **ChatGPT**：需要在 Settings → Apps & Connectors → Advanced 打开 Developer mode，再新建连接器，认证选 No auth。

工具：`search(query, source?)`、`fetch(id)`、`list_recent`、`archive_stats`。

## 开发
```bash
pip install -r carryon/requirements.txt pytest
pytest                      # 三家格式的合成导出，不含个人数据
cd carryon
python -m carryon.cli --db carryon.db import chatgpt-export.zip claude-export.zip takeout.zip
python -m carryon.cli --db carryon.db search "向量数据库"
```
有 SSH（Advanced SSH & Web Terminal）时：在 `~/.ssh/config` 配好 `Host haos`，然后 `./deploy.sh`
把 `carryon/` 推到 `/addons/carryon` 并以本地 add-on 安装或重建（`./deploy.sh --sync` 只同步）。

## 已知限制 / 下一步
- 认证是"秘密路径"：Claude 自定义连接器目前只支持无认证或 OAuth，这是两边都能用的最简方案。泄露 URL 就等于泄露记录；之后加 OAuth。
- 目前只有关键词检索（FTS5 trigram，中文可用；少于 3 个字的词走 LIKE，较慢但能用）。向量检索是下一步。
- Gemini 按 Takeout 里的会话链接（`gemini.google.com/app/<id>`）分组；Canvas 内容和附件文件名也会导入（附件本身不导入）。
- Gemini 活动默认 18 个月自动删除：重新导出时，库里已有的更早消息会保留并合并，不会被覆盖。

## License
[MIT](LICENSE)
