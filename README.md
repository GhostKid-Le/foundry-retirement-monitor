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
│    └─ schedule: 17 23 * * *  (UTC = 07:17 CST 目标，可能被延迟)         │
│       1) python app/daily_job.py   → 抓取 + diff + 写 data/email.json│
│       2) git commit data/{history,email}.json  (快照 + 邮件入库)      │
│                                                                      │
│  Secrets: 无需自建（仅用内置 GITHUB_TOKEN 提交快照）                  │
│  Pages : https://ghostkid-le.github.io/foundry-retirement-monitor/   │
└──────────────────────────────────────────────────────────────────────┘
            ▲
            │  每天定时 HTTP GET 公开 raw URL → data/email.json
   ┌──────────────────────────────────────┐
   │ Power Automate Flow（Recurrence 定时）   │
   │  1) 定时 HTTP GET raw email.json         │
   │  2) Parse JSON → Send email (V2)         │
   │     From: 你的 M365 账号                 │
   │     To:   收件人列表（Flow 里维护）       │
   └──────────────────────────────────────┘
   （无入站 webhook：Flow 主动出站拉取，合规）
```

**两个 workflow 各司其职**：
- `refresh.yml` —— 每小时整点把最新内容刷到 GitHub Pages（**不发邮件**）
- `daily.yml` —— 每日原计划 **07:17 CST** 启动（GitHub 调度队列可能延迟），抓取 + diff + 写 `data/email.json` + commit 快照（**不发邮件、不部署 Pages**）
- **发邮件由 Power Automate 自己定时拉取 `email.json` 完成**（见下），后端不主动推送

**特点**：
- ✅ 0 云成本（GitHub Actions 公共 repo 免费）
- ✅ 0 维护：不存在 "AKS 被停了导致漏发邮件" 这种故障模式
- ✅ 历史快照走 git history，比 PVC 更可靠、可审计
- ✅ HTTPS 自动证书（GitHub Pages 内置）
- ✅ 邮件每天一封（时间由 Power Automate 定时器决定），不会因每小时刷新页面而被刷屏
- ✅ 无入站 webhook、无需任何密钥/Entra 应用：Flow 主动拉取公开 `email.json`，天然满足“触发不对任何人开放”的合规要求

---

## 仓库结构

```
foundry-retirement-monitor/
├── .github/workflows/
│   ├── refresh.yml               # 每小时整点刷新 GitHub Pages
│   └── daily.yml                 # 每日目标 07:17 CST 抓取+diff+发邮件+commit 快照
├── app/
│   ├── foundry_monitor.py        # 抓取 / 解析 / diff / 渲染 HTML
│   ├── storage.py                # JSON 历史（默认 data/history.json）
│   ├── daily_job.py              # daily.yml 调用：抓取 + diff + 写 email.json
│   ├── build_site.py             # refresh.yml 调用：实时抓取 → site/index.html
│   ├── web.py                    # 本地预览 FastAPI 服务
│   └── requirements.txt
├── data/
│   ├── history.json              # 昨日快照，GH Actions 每天 commit 进来
│   └── email.json                # 当日邮件 {subject, html, changed}，Power Automate 拉取
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

### 2) 在 Power Automate 创建 Flow（定时拉取，不接受任何入站触发）

公司合规要求触发器不能对“任何人”开放。本方案让 Flow **自己定时去拉**仓库里的邮件内容，
**根本不暴露入站触发入口**，因此无需 Entra 应用 / OIDC / 服务树 ID / 任何 secret。

1. <https://make.powerautomate.com> → **Create → Scheduled cloud flow**（定时流）。
   - 设定每天发送时间（如北京时间 08:30；建议晚于 `daily.yml` 的 07:17，给抓取+commit 留出余量）。
2. 加 **HTTP** action（GET）拉取当日邮件内容（公开 raw URL，无需认证）：
   - **Method**：`GET`
   - **URI**：`https://raw.githubusercontent.com/GhostKid-Le/foundry-retirement-monitor/main/data/email.json`
3. 加 **Parse JSON** action：
   - **Content**：上一步 HTTP 的 **Body**
   - **Schema**：
     ```json
     { "type": "object", "properties": {
         "subject": {"type":"string"}, "html": {"type":"string"},
         "changed": {"type":"boolean"}, "generated_at": {"type":"string"} } }
     ```
4. 加 **"Send an email (V2)"**（Office 365 Outlook）：
   - **To** = `you@example.com; teammate@example.com`（分号分隔，多收件人在这里维护）
   - **Subject** = Parse JSON 的 `subject`
   - **Body** = 切到 `</>` code view，填 Parse JSON 的 `html`
5. （可选）只想“有变化才发”：在 Send email 外套一个 **Condition**，判断 Parse JSON 的 `changed` 等于 `true`。
6. Save。

> **为什么合规**：Flow 只有一个 **Recurrence（定时）** 触发器 + 出站 HTTP GET，**没有任何入站 webhook**，所以不存在“谁可以触发流”这个设置项，也就不可能被任何人触发。`email.json` 走公开 raw URL，里面只有已对外发布的退役信息，无敏感数据。

### 3) 启用 GitHub Pages
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/settings/pages>
2. **Source** 选 **GitHub Actions**（**不是** "Deploy from a branch"）
3. Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**

### 4) 手动触发首次运行
1. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/refresh.yml> → **Run workflow** → 等 1-2 分钟，页面就上线
2. <https://github.com/GhostKid-Le/foundry-retirement-monitor/actions/workflows/daily.yml> → **Run workflow** → `data/email.json` + `data/history.json` 被 commit 进 main
3. 浏览器打开 `https://raw.githubusercontent.com/GhostKid-Le/foundry-retirement-monitor/main/data/email.json` 确认能看到 JSON
4. 在 Power Automate 里手动 **Test → Run** 一次该 Flow，确认收到邮件

之后每小时整点自动刷页面、每天由 Power Automate 定时发邮件，无需任何干预。

---

## 运行时配置（环境变量）

| 名称 | 默认 | 说明 |
|---|---|---|
| `HISTORY_PATH` | `data/history.json`（daily.yml 里用 `../data/history.json`） | 快照路径 |
| `WINDOW_DAYS` | `30` | 关注未来 N 天内退役的型号 |
| `SOURCE_URL` | learn.microsoft.com 默认 | 抓取源（带回落） |
| `EMAIL_PAYLOAD_PATH` | `data/email.json`（daily.yml 里用 `../data/email.json`） | 当日邮件 JSON 输出路径，供 Power Automate 拉取 |
| `SITE_OUT` | `../site`（refresh.yml） | 静态站输出目录 |
| `TZ` | `Asia/Shanghai` | runner 时区，影响日志 / 页面时间戳 |

### 改触发时间
- **页面刷新频率**：`refresh.yml` 的 `cron: '0 * * * *'`（每小时整点 UTC = 每小时整点 CST）。改成每 30 分钟：`'*/30 * * * *'`。
- **邮件实际发送时间**：由 **Power Automate 的 Recurrence 定时器**决定（在 Flow 里改），不再由 GitHub cron 控制。
- **`daily.yml` 的 `cron: '17 23 * * *'`**（UTC 23:17 = 北京时间 07:17）只决定**几点把 `email.json` 准备好**；请把 Flow 的发送时间设得**晚于**它，给抓取+commit+raw 缓存留出余量。

### 改收件人 / 抄送 / 抄送规则
**全部在 Power Automate Flow 内维护**，不动代码、不动 workflow。

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

> 注：`daily_job.py` 只**写出 `email.json`**、不发信；真正发信由 Power Automate 定时拉取完成。本地跑可用来验证抓取/diff/渲染是否正常，或预览 `data/email.json` 的内容。

只想本地 FastAPI 预览页面（不发邮件）：
```powershell
cd app
uvicorn web:app --reload --port 8000
# http://localhost:8000/  → 报告页
# http://localhost:8000/?fresh=1 → 强制重新抓取
```

---

## 故障排查

- **Flow 拉到的是旧内容**：`raw.githubusercontent.com` 有约 5 分钟 CDN 缓存，且 `daily.yml` commit 需要时间。把 Flow 的定时设得**晚于** `daily.yml`（如晚 1 小时）即可。
- **Flow 报 404 / 拉不到 `email.json`**：确认 `daily.yml` 至少成功跑过一次（`data/email.json` 已 commit 进 main）；核对 raw URL 的 owner/repo/branch/路径与实际一致。
- **Flow 成功但没收到邮件**：去 Power Automate → Flow 的 **Run history** 看最近一次执行；可能是 Send-Email 步骤失败（M365 账号/权限），或套了 `changed=true` 条件而当天无变化。
- **HTTP action 提示需要 premium**：Flow 里的 HTTP connector 属 premium。若无许可，可改用 **GitHub** 内置 connector 的 “Get file content” 读取 `data/email.json`，效果相同。
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
| 改邮件发送时间 | **Power Automate Flow 的 Recurrence**（`daily.yml` 的 cron 只决定 `email.json` 几点就绪） |
| 加 / 改收件人 / 发件人 | **不动代码**，直接改 Power Automate Flow |
| 加 Teams / Slack 通知 | Power Automate Flow 里并联 Teams 步骤；后端不动 |
| 改邮件样式 | `app/foundry_monitor.py` → `render_email_html()`；Outlook desktop 注意 inline CSS |
| 改页面样式 | `app/build_site.py` 的渲染部分 |
| 自定义域名 | `site/CNAME` 写域名 + DNS 配 CNAME 到 `<owner>.github.io`，参考 [GitHub Pages 文档](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site) |

---

## 本地版

只想在自己机器上跑一次、浏览器看 HTML，不想推 GitHub：见 [`local-version/README.md`](local-version/README.md)。
