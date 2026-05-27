# Foundry Retirement Monitor

定时抓取 [Microsoft Learn — Azure AI Foundry / OpenAI model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule)，与昨日快照对比，通过 **Power Automate** 把美观的 HTML 邮件发到 Outlook（发件人 = 你自己），同时把**最新报告**发布在 GitHub Pages 上随时浏览。

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
│    └─ schedule: 30 0 * * *  (UTC = 08:30 Asia/Shanghai)              │
│       1) python app/daily_job.py   → 抓取 + diff + POST webhook      │
│       2) git commit data/history.json  (快照入库)                    │
│                                                                      │
│  Secret: MAILER_WEBHOOK_URL  (Power Automate trigger URL)            │
│  Pages : https://ghostkid-le.github.io/foundry-retirement-monitor/   │
└──────────────────────────────────────────────────────────────────────┘
            │
            ▼  POST {subject, html}   （仅 daily.yml 调用）
   ┌──────────────────────────────────┐
   │ Power Automate Flow              │
   │  → Send email (V2) Office 365    │
   │     From: 你的 M365 账号         │
   │     To:   收件人列表（Flow 里维护）│
   └──────────────────────────────────┘
```

**两个 workflow 各司其职**：
- `refresh.yml` —— 每小时整点把最新内容刷到 GitHub Pages（**不发邮件**）
- `daily.yml` —— 每天 08:30 CST 抓取 + diff + 发邮件 + commit 快照（**不部署 Pages**）

**特点**：
- ✅ 0 云成本（GitHub Actions 公共 repo 免费）
- ✅ 0 维护：不存在 "AKS 被停了导致漏发邮件" 这种故障模式
- ✅ 历史快照走 git history，比 PVC 更可靠、可审计
- ✅ HTTPS 自动证书（GitHub Pages 内置）
- ✅ 邮件只在每天 08:30 一次，不会因为每小时刷新页面而被刷屏

---

## 仓库结构

```
foundry-retirement-monitor/
├── .github/workflows/
│   ├── refresh.yml               # 每小时整点刷新 GitHub Pages
│   └── daily.yml                 # 每天 08:30 CST 抓取+diff+发邮件+commit 快照
├── app/
│   ├── foundry_monitor.py        # 抓取 / 解析 / diff / 渲染 HTML
│   ├── storage.py                # JSON 历史（默认 data/history.json）
│   ├── daily_job.py              # daily.yml 调用：抓取 + diff + 发邮件
│   ├── build_site.py             # refresh.yml 调用：实时抓取 → site/index.html
│   ├── web.py                    # 本地预览 FastAPI 服务
│   └── requirements.txt
├── data/
│   └── history.json              # GH Actions 每天 commit 进来
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

### 2) 在 Power Automate 创建 Flow
1. <https://make.powerautomate.com> → **Create → Instant cloud flow** → trigger **"When a HTTP request is received"**。
2. Request body schema：
   ```json
   { "type": "object", "properties": { "subject": {"type":"string"}, "html": {"type":"string"} } }
   ```
3. 加 **"Send an email (V2)"** (Office 365 Outlook)：
   - **To** = `you@example.com; teammate@example.com`（分号分隔，多收件人在这里维护）
   - **Subject** = 表达式 `triggerBody()?['subject']`
   - **Body** = 切到 `</>` code view，粘入 `triggerBody()?['html']`
4. Save → 复制 trigger 的 **HTTP POST URL**（包含 `sig=` 签名）。

> **⚠️ 这个 URL 是机密**：任何拿到它的人都能调用你的 Flow（发邮件）。不要贴到聊天/issue/log；如不慎泄露，立即在 Power Automate 里删除并重建触发器以失效旧 URL。

### 3) 在 GitHub 加 Secret
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/settings/secrets/actions> → **New repository secret**
2. Name: `MAILER_WEBHOOK_URL`
3. Secret: 粘贴第 2 步拿到的 URL

### 4) 启用 GitHub Pages
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/settings/pages>
2. **Source** 选 **GitHub Actions**（**不是** "Deploy from a branch"）
3. Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**

### 5) 手动触发首次运行
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/refresh.yml> → **Run workflow** → 等 1-2 分钟，页面就上线
2. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/daily.yml> → **Run workflow** → 收一封 "首次运行 baseline" 邮件、`data/history.json` 被 commit 进 main

之后每小时整点自动刷页面、每天 08:30 CST 自动发邮件，无需任何干预。

---

## 运行时配置（环境变量）

| 名称 | 默认 | 说明 |
|---|---|---|
| `HISTORY_PATH` | `data/history.json`（daily.yml 里用 `../data/history.json`） | 快照路径 |
| `WINDOW_DAYS` | `30` | 关注未来 N 天内退役的型号 |
| `SOURCE_URL` | learn.microsoft.com 默认 | 抓取源（带回落） |
| `MAILER_WEBHOOK_URL` | — | **daily.yml 必需**，从 GitHub Secret 注入 |
| `SITE_OUT` | `../site`（refresh.yml） | 静态站输出目录 |
| `TZ` | `Asia/Shanghai` | runner 时区，影响日志 / 页面时间戳 |

### 改触发时间
- **页面刷新频率**：`refresh.yml` 的 `cron: '0 * * * *'`（每小时整点 UTC = 每小时整点 CST）。改成每 30 分钟：`'*/30 * * * *'`。
- **邮件发送时间**：`daily.yml` 的 `cron: '30 0 * * *'`（UTC，= 北京时间 08:30）。改成北京时间 09:00 → `'0 1 * * *'`。

### 改收件人 / 抄送 / 抄送规则
**全部在 Power Automate Flow 内维护**，不动代码、不动 workflow。

---

## 本地手动跑

```powershell
$env:MAILER_WEBHOOK_URL = '<paste-only-locally-do-not-commit>'
$env:HISTORY_PATH = 'data/history.json'
cd app
pip install -r requirements.txt
python daily_job.py           # 抓取 + diff + 发邮件
python build_site.py          # 生成 site/index.html
```

只想本地 FastAPI 预览页面（不发邮件）：
```powershell
cd app
uvicorn web:app --reload --port 8000
# http://localhost:8000/  → 报告页
# http://localhost:8000/?fresh=1 → 强制重新抓取
```

---

## 故障排查

- **Workflow 失败 — "MAILER_WEBHOOK_URL 未配置"**：Secret 没加好，或者名字大小写不对，必须严格等于 `MAILER_WEBHOOK_URL`。
- **Workflow 成功但没收到邮件**：去 Power Automate → Flow 的 **Run history** 看最近一次执行。可能是 Send-Email 步骤失败（M365 账号 / 权限问题）。
- **GitHub Pages 部署失败 — 403**：Settings → Pages 的 Source 必须选 **GitHub Actions**；Settings → Actions → General → Workflow permissions 必须允许 "Read and write"。
- **页面打开是 404**：第一次部署有 1-2 分钟延迟；之后看 Actions 是否绿，Pages settings 里是否显示 site URL。
- **抓取失败 — MS Learn 偶发 anti-bot**：workflow 日志里看 HTTP 状态码。`foundry_monitor.fetch_html` 已有多个回落 URL，重跑一次通常能过；`build_site.py` 抓不到时会渲染 "⚠️ 抓取失败" 横幅而不会让 workflow 失败。
- **快照没被 commit**：daily.yml 的 commit 步骤会跳过 "no changes" 的提交，这是正常的（说明今天数据没变）。
- **GitHub cron 延迟**：免费 runner 调度高峰期可能延迟几分钟，08:30 邮件偶尔变成 08:33，属正常现象。

---

## 二次迭代路径

| 需求 | 改哪里 |
|---|---|
| 新增邮件表格列 | `app/foundry_monitor.py`：① `RetirementRecord` 加字段 ② `parse_tables()` 加列识别 ③ `render_email_html()` 的 `<th>`/`<td>` 追加 |
| 改抓取源 / 时间窗口 | 两个 workflow 的 env |
| 改页面刷新频率 | `.github/workflows/refresh.yml` 的 `cron` |
| 改邮件发送时间 | `.github/workflows/daily.yml` 的 `cron`（UTC） |
| 加 / 改收件人 / 发件人 | **不动代码**，直接改 Power Automate Flow |
| 加 Teams / Slack 通知 | Power Automate Flow 里并联 Teams 步骤；后端不动 |
| 改邮件样式 | `app/foundry_monitor.py` → `render_email_html()`；Outlook desktop 注意 inline CSS |
| 改页面样式 | `app/build_site.py` 的渲染部分 |
| 自定义域名 | `site/CNAME` 写域名 + DNS 配 CNAME 到 `<owner>.github.io`，参考 [GitHub Pages 文档](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site) |

---

## 本地版

只想在自己机器上跑一次、浏览器看 HTML，不想推 GitHub：见 [`local-version/README.md`](local-version/README.md)。
