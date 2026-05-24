# AGENTS.md — 给 AI 助手 / 后续维护者的导览

> 这份文件给 Claude / Copilot / Cursor 等 AI 助手以及任何接手这个仓库的人。
> 主仓库说明请看 [README.md](README.md)；这里只放**已验证踩过的坑**和**迭代时该改哪里**。

---

## TL;DR — 这是什么

一个 Azure Function App，每天 08:30 (CST) 抓 Microsoft Learn 上的 *Foundry / OpenAI model retirement schedule* 表格，
跟昨天的快照（存在 Blob 里）做 diff，把结果 POST 给一个 Power Automate webhook，由 Flow 调 Office 365 connector 用**你自己的邮箱**发 HTML 邮件。

```
Timer (08:30 CST) ── fetch HTML ── parse + diff vs blob ── POST JSON ──► Power Automate Flow ──► Outlook 邮件
                                       │                  {subject, html}
                                       └── upsert blob   ───────────────────► storage account (MI 鉴权)
```

---

## 文件地图

| 文件 | 干什么 | 修改影响 |
|---|---|---|
| `app/function_app.py` | 入口：`daily_check` timer + `report` HTTP | 改触发器、改发邮件方式、加新 HTTP endpoint |
| `app/foundry_monitor.py` | 抓取、HTML 解析、diff、邮件/报告渲染 | 加列、改样式、改 diff 规则 |
| `app/requirements.txt` | Python 依赖 | 加包必须同步 |
| `app/host.json` | Functions host 配置 | 一般不动 |
| `app/.funcignore` | 部署时排除项 | 一般不动 |
| `infra/main.bicep` + `resources.bicep` | IaC：FC1 + Storage + MI + AppInsights | 改资源拓扑 |
| `local-version/foundry_retirement_monitor.py` | 单文件离线版，抓完直接生成 HTML 在浏览器打开 | 跟 `app/foundry_monitor.py` 保持**渲染逻辑同步** |
| `local-version/README.md` | 离线用法 | 改本地行为时一起改 |
| `*.ps1`（deploy-/trigger-/verify-/check-） | 一次性运维脚本 | 命令行兜底，**真正的真理在 README 流程** |

---

## 已验证的关键约束（**不要重蹈覆辙**）

### 1. PowerShell 把 `&` 当 token 截断 webhook URL
- 现象：`az functionapp config appsettings set --settings "MAILER_WEBHOOK_URL=https://..../triggers/manual/run?api-version=1&sp=..."`，存进去的值在第一个 `&` 处被截掉，长度只剩前一段。
- 即使外层加 `'...'` 单引号也无效（PS 把整个表达式 token 化后再传给 native exe）。
- **正解**：写一个 JSON body 文件，用 `az rest --method PUT --uri /subscriptions/.../config/appsettings?api-version=2022-03-01 --body @settings_body.json`。
- 验证：`az functionapp config appsettings list ... --query "[?name=='MAILER_WEBHOOK_URL'].value | [0]" -o tsv` 长度应 ≈ 283。

### 2. Outlook 桌面版的 Word renderer 会把 `2025-10-06` 拆成三行
- 单纯 CSS `white-space:nowrap` 在 Word renderer 下**无效**。
- 而且 Word renderer 把 `-`（U+002D ASCII hyphen）当成允许换行的位置。
- **正解（两个都要）**：
  ```python
  text = (r.version or "-").replace("-", "&#8209;")   # U+2011 non-breaking hyphen
  td = f'<td nowrap="nowrap" style="white-space:nowrap;">{text}</td>'
  ```
- Web 浏览器（含 OWA、移动 Outlook）两种都支持，所以这是兼容超集。
- 当前实现：`app/foundry_monitor.py::render_email_html()` 在 Version 和 Retirement 两列的 `<th>` / `<td>` 上都做了；`local-version/foundry_retirement_monitor.py` 用 `td.nowrap / th.nowrap` CSS class（浏览器原生支持就够了）。

### 3. 存储账号 `allowSharedKeyAccess=false`，**不能**用 connection string
- 所有 SDK 调用都必须用 `DefaultAzureCredential()` 或 `ManagedIdentityCredential(client_id=os.environ['AZURE_CLIENT_ID'])`。
- 部署包也走 MI（Flex Consumption + `deploymentStorage.authentication.type=UserAssignedIdentity`）。

### 4. 收件人列表不在代码里
- 函数只把 `{subject, html}` POST 给 webhook，**没有 To 字段**。
- 收件人在 Power Automate Flow 的 `Send an email (V2)` 步骤里维护，多人分号分隔。
- 改收件人 = 改 Flow，**不要**改函数代码 / 不要重部署。

### 5. webhook URL 是 secret
- 任何持有它的人都能让你的 M365 发邮件。
- **不要**进 git；`.gitignore` 已经把 `settings_body.json`、`appsettings.tmp.json`、`.azure/` 列进去。
- 如泄漏，去 Flow 编辑 trigger → **Regenerate URL**，再走 README 第 3 步把新 URL 写回。

---

## 迭代手册（"我有新需求时改哪里"）

### A. 改数据 / 数据模型
- **加表格列（例如 Region）**：
  1. `app/foundry_monitor.py` → `RetirementRecord` dataclass 加字段；
  2. 同文件 `EXPECTED_COLS` / `parse_tables()` 加列识别；
  3. `render_email_html()` 在 `<th>` 行加 `<th>Region</th>`、在 row 拼接处加对应 `<td>`；
  4. `local-version/foundry_retirement_monitor.py` 做同样三处修改（结构镜像）；
  5. 重新部署：`Compress-Archive` + `config-zip` + 手工触发一次。

- **改源 URL** / **改窗口** / **改 cron**：全部走 App Setting，**不改代码**。
  ```powershell
  az functionapp config appsettings set -g rg-foundry-monitor -n func-znnzcoperxcfc `
    --settings SOURCE_URL='https://...' WINDOW_DAYS=60 SCHEDULE_CRON='0 0 9 * * *'
  ```

### B. 改通知通道
- **加收件人 / CC / BCC**：Power Automate Flow，零代码。
- **加 Teams / Slack / 钉钉 / 飞书**：在 Flow 里 `Send email` 之后加一步对应 connector，**函数代码不变**。
- **替换整个邮件后端**：函数只 POST `{subject, html}` 到 `MAILER_WEBHOOK_URL`，把它指到任何能吃 JSON 的 endpoint 都行（Logic App / Function HTTP / IFTTT / n8n / 自建 SMTP 网关）。

### C. 改函数本身
- **加 HTTP endpoint**：`function_app.py` 末尾仿照 `report` 加 `@app.function_name + @app.route`。
- **加另一个定时任务**：再加一个 `@app.timer_trigger`；注意一个 cron 一个函数。
- **改身份**：UAMI 在 `infra/resources.bicep`，给它加 RBAC 即可。

### D. 本地开发
- 不想发邮件：不设 `MAILER_WEBHOOK_URL`，`_send_email` 会 log error 然后正常返回（不抛），其他逻辑都还会跑。
- 完全离线 + 浏览器看：`local-version/foundry_retirement_monitor.py`，没有任何 Azure 依赖。

---

## 部署/触发速查（PowerShell）

```powershell
# 打包 + 部署
cd foundry-retirement-monitor
Compress-Archive -Path app\host.json,app\function_app.py,app\foundry_monitor.py,app\requirements.txt,app\.funcignore `
                 -DestinationPath deploy.zip -Force
az functionapp deployment source config-zip -g rg-foundry-monitor -n func-znnzcoperxcfc --src deploy.zip --build-remote true

# 手工触发 daily_check
$key = az functionapp keys list -g rg-foundry-monitor -n func-znnzcoperxcfc --query masterKey -o tsv
Invoke-WebRequest -Uri "https://func-znnzcoperxcfc.azurewebsites.net/admin/functions/daily_check" `
  -Method POST -Headers @{'x-functions-key'=$key;'Content-Type'='application/json'} -Body '{"input":""}'

# 看日志（最近 30 分钟）
az monitor app-insights query -g rg-foundry-monitor --app appi-znnzcoperxcfc `
  --analytics-query "traces | where timestamp > ago(30m) | where operation_Name == 'daily_check' | order by timestamp desc | take 100"
```

---

## 当前已知技术债 / TODO

- [ ] `infra/resources.bicep` 仍然 provision ACS + Email Service —— 切到 webhook 后不再需要，**应当删除**。
- [ ] 一次性 `*.ps1` 脚本（`check-deploy.ps1` / `check-rg.ps1` / `verify.ps1` 等）跟 README 命令重复，可挑保留 1-2 个或全删。
- [ ] `local-version` 与 `app/foundry_monitor.py` 共享逻辑但**没有抽公共模块**，每次改解析/渲染要两边同步。后续可以把核心抽到一个独立包。
- [ ] 邮件正文里 "新增 N 变更 M 移除 K" 还没把"移除"明细列出来（只列了新增/变更明细）。
