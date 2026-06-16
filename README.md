# Foundry Retirement Monitor

定时抓取 [Microsoft Learn — Azure AI Foundry / OpenAI model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule)，与昨日快照对比，由 **GitHub Actions 直接调用 Resend 邮件 API** 发出美观的 HTML 邮件，同时把**最新报告**发布在 GitHub Pages 上随时浏览。

> **当前形态（v3 · 全免费）**：GitHub Actions 定时任务 + GitHub Pages。无任何云资源、$0/月。
> 历史版本 v2 (AKS + AppGw + AGIC) 与 v1 (Flex Consumption Functions + ACS) 均已下线并清理；代码在 git history 里可追溯。

---

## 架构

```
┌──────────────────────────────────────────────────────────────────────┐
│ GitHub repo: GhostKid-Le/foundry-retirement-monitor                   │
│                                                                      │
│  .github/workflows/refresh.yml    （页面实时刷新）                    │
│    └─ schedule: 0 * * * *  (每小时整点 · UTC)                        │
│       + workflow_dispatch + push(app/**)                             │
│       1) python app/build_site.py  → 实时抓取 → site/index.html      │
│       2) actions/deploy-pages       → 部署到 GitHub Pages            │
│                                                                      │
│  .github/workflows/daily.yml      （每日邮件）                        │
│    └─ schedule: 30 0 * * *  (UTC = 08:30 CST 发送，免费 cron 可能延迟) │
│       1) python app/daily_job.py → 抓取 + diff + 渲染 HTML          │
│       2) 调 Resend API 直接发信 + commit 快照(history/email.json)    │
│                                                                      │
│  Secrets: RESEND_API_KEY + MAIL_TO (+ 可选 MAIL_FROM)               │
│  Pages : https://ghostkid-le.github.io/foundry-retirement-monitor/   │
└───────────────────────────────────────────────────┐
            │
            ▼  POST https://api.resend.com/emails   (仅 daily.yml 调用)
   ┌────────────────────────────────────┐
   │ Resend 邮件 API                          │
   │  From: MAIL_FROM（默认 resend.dev 测试地址）│
   │  To:   MAIL_TO（GitHub Secret 维护）      │
   └────────────────────────────────────┘
   （API key 存 GitHub Secret，外部无人可触发）
```

**两个 workflow 各司其职**：
- `refresh.yml` —— 每小时整点把最新内容刷到 GitHub Pages（**不发邮件**）
- `daily.yml` —— 每日北京时间 **08:30**（免费 cron 可能延迟到 08:30–09:xx）启动，抓取 + diff + 渲染 + 调 Resend API 发信 + commit 快照（**不部署 Pages**）

**特点**：
- ✅ 0 云成本（GitHub Actions 公共 repo 免费）
- ✅ 0 维护：不存在 "AKS 被停了导致漏发邮件" 这种故障模式
- ✅ 历史快照走 git history，比 PVC 更可靠、可审计
- ✅ HTTPS 自动证书（GitHub Pages 内置）
- ✅ 邮件每天一封（北京 08:30 前后），不会因每小时刷新页面而被刷屏
- ✅ 无入站 webhook、无 Entra 应用：GitHub Actions 持密钥主动外发，外部任何人无法触发（只能靠 schedule / 仓库写权限手动触发）

---

## 仓库结构

```
foundry-retirement-monitor/
├── .github/workflows/
│   ├── refresh.yml               # 每小时整点刷新 GitHub Pages
│   ├── daily.yml                 # 每日北京 08:30 抓取+diff+Resend 发信+commit 快照
├── app/
│   ├── foundry_monitor.py        # 抓取 / 解析 / diff / 渲染 HTML
│   ├── storage.py                # JSON 历史（默认 data/history.json）
│   ├── daily_job.py              # daily.yml 调用：抓取 + diff + 渲染 + Resend 发信
│   ├── build_site.py             # refresh.yml 调用：实时抓取 → site/index.html
│   ├── web.py                    # 本地预览 FastAPI 服务
│   └── requirements.txt
├── data/
│   ├── history.json              # 昨日快照，GH Actions 每天 commit 进来
│   └── email.json                # 当日邮件 {subject, html, changed} 审计快照
├── local-version/                # 本地一次性脚本版本
├── page.html                     # 静态预览样例
└── README.md
```

---

## 从零部署（首次 ~10 分钟）

### 1) Fork / clone 仓库
```powershell
git clone https://github.com/GhostKid-Le/foundry-retirement-monitor.git
cd foundry-retirement-monitor
```

### 2) 注册 Resend，配置 GitHub Secrets

公司 corp 租户禁用了 Power Automate 的 HTTP 连接器、且不允许把 Entra 应用联合到个人 GitHub，
故改由 GitHub Actions 直接调 Resend 发信。API key 存 GitHub Secret，**非任何人可触发**，满足合规。

1. 注册 <https://resend.com>（免费额度：100 封/天，足够每日一封），在 **API Keys** 里 **Create API Key**（权限选 Sending access），复制 `re_...` 开头的 key。
2. 发件地址二选一：
   - **快速起步（无自有域名）**：用 Resend 提供的 `onboarding@resend.dev` 作发件人 —— **但 Resend 限制此地址只能发到你注册 Resend 用的那个邮箱**，自用足够。
   - **正式（有自有域名）**：在 Resend **Domains** 里验证你的域名（加几条 DNS 记录），之后可用 `you@yourdomain.com` 发给任意收件人。
3. 在 GitHub 加 Secrets：<https://github.com/GhostKid-Le/foundry-retirement-monitor/settings/secrets/actions> → **New repository secret**：

| Name | 值 | 必需 |
|---|---|---|
| `RESEND_API_KEY` | 第 1 步的 `re_...` key | ✅ |
| `MAIL_TO` | 收件人，多个用 `,` 或 `;` 分隔 | ✅ |
| `MAIL_FROM` | 发件人，如 `Foundry Monitor <you@yourdomain.com>`；不填则默认 `onboarding@resend.dev` | 可选 |

> **合规说明**：触发完全由 GitHub `schedule` / 手动 `workflow_dispatch` 控制，二者都需仓库写权限，外部任何人无法触发；Resend key 是出站调用的私密凭据，存在 GitHub Secret 中不外泄。

### 3) 启用 GitHub Pages
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/settings/pages>
2. **Source** 选 **GitHub Actions**（**不是** "Deploy from a branch"）
3. Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**

### 4) 手动触发首次运行
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/refresh.yml> → **Run workflow** → 等 1-2 分钟，页面就上线
2. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/daily.yml> → **Run workflow** → 应收到一封邮件，且 `data/{email,history}.json` 被 commit 进 main
3. 没收到？看该 run 日志：「Resend 已接受邮件」=成功；「未配置 RESEND_API_KEY / MAIL_TO」=Secret 没加好；若 Resend 报 403/422，多半是发件人未验证（见步骤 2）或收件人不被 `onboarding@resend.dev` 允许

之后每小时整点自动刷页面、每天北京 08:30 前后自动发邮件，无需任何干预。

---

## 运行时配置（环境变量）

| 名称 | 默认 | 说明 |
|---|---|---|
| `HISTORY_PATH` | `data/history.json`（daily.yml 里用 `../data/history.json`） | 快照路径 |
| `WINDOW_DAYS` | `30` | 关注未来 N 天内退役的型号 |
| `SOURCE_URL` | learn.microsoft.com 默认 | 抓取源（带回落） |
| `EMAIL_PAYLOAD_PATH` | `data/email.json`（daily.yml 里用 `../data/email.json`） | 当日邮件 JSON 审计快照输出路径 |
| `RESEND_API_KEY` | — | **daily.yml 发信必需**，从 GitHub Secret 注入；缺失则跳过发信只写快照 |
| `MAIL_TO` | — | **daily.yml 发信必需**，收件人（`,`/`;` 分隔） |
| `MAIL_FROM` | `Foundry Monitor <onboarding@resend.dev>` | 发件人；发给任意收件人需在 Resend 验证域名 |
| `SITE_OUT` | `../site`（refresh.yml） | 静态站输出目录 |
| `TZ` | `Asia/Shanghai` | runner 时区，影响日志 / 页面时间戳 |

### 改触发时间
- **页面刷新频率**：`refresh.yml` 的 `cron: '0 * * * *'`（每小时整点 UTC = 每小时整点 CST）。改成每 30 分钟：`'*/30 * * * *'`。
- **邮件发送时间**：`daily.yml` 的 `cron: '30 0 * * *'`（UTC 00:30 = 北京时间 08:30）。免费 GitHub cron 无 SLA，可能延迟 1-N 小时，故实际多在 08:30–09:xx 到达。想更早就把它提前。

### 改收件人 / 发件人
改 GitHub Secret 的 `MAIL_TO` / `MAIL_FROM` 即可，不动代码、不动 workflow。

---

## 本地手动跑

```powershell
$env:HISTORY_PATH = 'data/history.json'
$env:EMAIL_PAYLOAD_PATH = 'data/email.json'
cd app
pip install -r requirements.txt
python daily_job.py           # 抓取 + diff + 写 data/email.json（不发信）
python build_site.py          # 生成 site/index.html
```

> 注：本地未设 `RESEND_API_KEY` / `MAIL_TO` 时，`daily_job.py` **只写 `email.json` 快照、自动跳过发信**（日志显示“未配置…跳过发信”），可安全用来验证抓取/diff/渲染。要本地真发信，设 `$env:RESEND_API_KEY` 与 `$env:MAIL_TO` 再跑。

只想本地 FastAPI 预览页面（不发邮件）：
```powershell
cd app
uvicorn web:app --reload --port 8000
# http://localhost:8000/  → 报告页
# http://localhost:8000/?fresh=1 → 强制重新抓取
```

---

## 故障排查

- **没收到邮件，run 日志显示「未配置 RESEND_API_KEY / MAIL_TO」**：GitHub Secret 没加或名字不对，必须严格等于 `RESEND_API_KEY` / `MAIL_TO`。
- **Resend 返回 403 / 422**：发件人 `MAIL_FROM` 用了未验证域名，或仍用 `onboarding@resend.dev` 却发给非注册邮箱。解决：在 Resend 验证自有域名，或把收件人改成你注册 Resend 用的邮箱。
- **超出额度**：Resend 免费 100 封/天；本项目每天 1 封，正常不会触顶。
- **GitHub Pages 部署失败 — 403**：Settings → Pages 的 Source 必须选 **GitHub Actions**；Settings → Actions → General → Workflow permissions 必须允许 "Read and write"。
- **页面打开是 404**：第一次部署有 1-2 分钟延迟；之后看 Actions 是否绿，Pages settings 里是否显示 site URL。
- **抓取失败 — MS Learn 偶发 anti-bot**：workflow 日志里看 HTTP 状态码。`foundry_monitor.fetch_html` 已有多个回落 URL，重跑一次通常能过；`build_site.py` 抓不到时会渲染 "⚠️ 抓取失败" 横幅而不会让 workflow 失败。
- **快照没被 commit**：daily.yml 的 commit 步骤会跳过 "no changes" 的提交，这是正常的（说明今天数据没变）。
- **GitHub cron 延迟**：免费 runner 调度高峰期可能延迟 1-N 小时，北京 08:30 的邮件偶尔到 09:xx，属正常。想更准时可把 `daily.yml` 的 cron 适当提前。

---

## 二次迭代路径

| 需求 | 改哪里 |
|---|---|
| 新增邮件表格列 | `app/foundry_monitor.py`：① `RetirementRecord` 加字段 ② `parse_tables()` 加列识别 ③ `render_email_html()` 的 `<th>`/`<td>` 追加 |
| 改抓取源 / 时间窗口 | 两个 workflow 的 env |
| 改页面刷新频率 | `.github/workflows/refresh.yml` 的 `cron` |
| 改邮件发送时间 | `.github/workflows/daily.yml` 的 `cron`（UTC） |
| 加 / 改收件人 / 发件人 | 改 GitHub Secret 的 `MAIL_TO` / `MAIL_FROM`，不动代码 |
| 加 Teams / Slack 通知 | `daily_job.py` 里在 `_send_email` 后并联一个 webhook POST（Teams/Slack incoming webhook） |
| 改邮件样式 | `app/foundry_monitor.py` → `render_email_html()`；Outlook desktop 注意 inline CSS |
| 改页面样式 | `app/build_site.py` 的渲染部分 |
| 自定义域名 | `site/CNAME` 写域名 + DNS 配 CNAME 到 `<owner>.github.io`，参考 [GitHub Pages 文档](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site) |

---

## 本地版

只想在自己机器上跑一次、浏览器看 HTML，不想推 GitHub：见 [`local-version/README.md`](local-version/README.md)。
