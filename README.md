# Foundry Retirement Monitor

每日抓取 [Microsoft Learn — Azure AI Foundry / OpenAI model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) 页面，与昨日快照比较，通过 **Power Automate** 把美观的 HTML 邮件发到你的 Outlook（发件人 = 你自己，而不是 `DoNotReply@...`）。

> 项目特色：
> - **零 Key**：Function App 跑在 Flex Consumption + 全 Managed Identity 上，订阅级 `disableLocalAuth`/`allowSharedKeyAccess=false` 也兼容。
> - **零 SMTP / 零 ACS 域名**：邮件经由 Power Automate webhook → Office 365 connector，发件人就是你的 M365 账号。
> - **公开 HTTP 报告**：除了每日邮件，还暴露 `/api/report` 匿名 URL，可直接分享。

---

## 架构

```
┌────────────────────────────┐    08:30 CST    ┌──────────────────────────┐
│ Azure Functions FC1 (Py3.11) ├────────────────► daily_check (timer)     │
│ func-znnzcoperxcfc (westus2) │                 └────┬─────────────────┬─┘
└────────────────────────────┘                       │                 │
              ▲                                       │ scrape +        │ POST JSON
              │ GET /api/report                       │ diff vs blob    │ {subject, html}
              │ (anonymous)                           ▼                 ▼
        anyone with URL                ┌──────────────────┐   ┌──────────────────────┐
                                       │ Storage Blob      │   │ Power Automate Flow   │
                                       │ history/...json   │   │ "Foundry Retirement   │
                                       │ (MI, no keys)     │   │  Mailer"              │
                                       └──────────────────┘   │  → Send email (V2)    │
                                                              │  From: <你>           │
                                                              │  To:   <收件人列表>   │
                                                              └──────────────────────┘
```

### Azure 资源（resource group `rg-foundry-monitor`，westus2）

| 资源 | 名称 | 作用 |
|---|---|---|
| Function App (FC1, Linux, Py3.11) | `func-znnzcoperxcfc` | timer + http |
| Storage Account | `stznnzcoperxcfc` | `history/foundry_retirement_history.json` + 部署包；`allowSharedKeyAccess=false` |
| User-Assigned Managed Identity | `id-znnzcoperxcfc` | 函数访问 storage 的身份 |
| Application Insights / Log Analytics | `appi-…` / `log-…` | 日志、监控 |

> ⚠️ 早期版本里挂的 **Azure Communication Services + Email Service**（`acs-znnzcoperxcfc` / `email-znnzcoperxcfc`）**已废弃**，请参考 [docs: 删除 ACS](#可选清理已废弃的-acs-资源)。

---

## 快速开始

### 1) 部署基础设施

```powershell
cd foundry-retirement-monitor

az login
az account set --subscription <YOUR_SUB>

az bicep build -f .\infra\main.bicep --outfile .\infra\main.json

az deployment sub create `
  --name foundry-monitor `
  --location westus2 `
  --template-file .\infra\main.json `
  --parameters environmentName=foundry-monitor location=westus2 `
               recipientAddress=<YOUR_EMAIL> `
               scheduleCron='0 30 8 * * *' timeZone='China Standard Time'
```

> `recipientAddress` 只是写进 App Setting 用于日志/调试；**真实收件人列表在 Power Automate Flow 里维护**。

### 2) 创建 Power Automate Flow 并拿 webhook URL

1. 打开 https://make.powerautomate.com → **Create → Automated cloud flow** → trigger 选 **"When a HTTP request is received"**。
2. Request body schema（直接 paste）：
   ```json
   { "type": "object", "properties": { "subject": {"type": "string"}, "html": {"type": "string"} } }
   ```
3. Trigger 高级设置 → **Who can trigger the flow = Anyone**。
4. 加一步 **"Send an email (V2)"** (Office 365 Outlook connector，登录你的 M365 账号)：
   - **From** = 你（默认）
   - **To** = `wang.le@microsoft.com; you@example.com`（多人用分号分隔）
   - **Subject** = `triggerBody()?['subject']`（点 Expression）
   - **Body** = `triggerBody()?['html']`，并把 Body 输入框右下角切到 **<\/>** code-view（保留 HTML 原文）
5. **Save**，然后回到第 1 步那个 trigger，复制 **HTTP POST URL**（带 sig= 的长 URL）—— 这就是 webhook。

### 3) 把 webhook URL 写到 Function App

URL 里有 `&` 字符，PowerShell 原生 arg parser 会把它当作命令分隔符**截断**值，即使加引号也会出错。**必须**走 `az rest`：

```powershell
$webhook = '<paste-your-full-URL-here>'
$body = @{
  properties = @{
    MAILER_WEBHOOK_URL = $webhook
    # ... 其他要保留的设置（先 az functionapp config appsettings list 拿到 JSON 合并）
  }
} | ConvertTo-Json -Depth 5 -Compress
$body | Out-File settings_body.json -Encoding utf8 -NoNewline

$subId = az account show --query id -o tsv
az rest --method PUT `
  --uri "/subscriptions/$subId/resourceGroups/rg-foundry-monitor/providers/Microsoft.Web/sites/func-znnzcoperxcfc/config/appsettings?api-version=2022-03-01" `
  --body '@settings_body.json'

Remove-Item settings_body.json
```

验证：

```powershell
$len = (az functionapp config appsettings list -g rg-foundry-monitor -n func-znnzcoperxcfc `
        --query "[?name=='MAILER_WEBHOOK_URL'].value | [0]" -o tsv).Length
"STORED LEN=$len"   # 期望 ~283
```

### 4) 部署函数代码

```powershell
Compress-Archive -Path app\host.json,app\function_app.py,app\foundry_monitor.py,app\requirements.txt,app\.funcignore `
                 -DestinationPath deploy.zip -Force
az functionapp deployment source config-zip `
  -g rg-foundry-monitor -n func-znnzcoperxcfc --src deploy.zip --build-remote true
```

### 5) 手工触发一次建立 baseline

```powershell
$key = az functionapp keys list -g rg-foundry-monitor -n func-znnzcoperxcfc --query masterKey -o tsv
Invoke-WebRequest -Uri "https://func-znnzcoperxcfc.azurewebsites.net/admin/functions/daily_check" `
  -Method POST -Headers @{'x-functions-key'=$key;'Content-Type'='application/json'} -Body '{"input":""}'
```

3-5 秒后 inbox 应收到 *"首次运行 baseline (N 条)"* 邮件。

---

## 运行时环境变量

| 名称 | 是否必须 | 默认 | 说明 |
|---|---|---|---|
| `MAILER_WEBHOOK_URL` | **是** | — | Power Automate trigger URL，**不要提交进 git** |
| `STORAGE_ACCOUNT_NAME` | 是 | — | Bicep 注入；MI 模式 |
| `AZURE_CLIENT_ID` | 是 | — | UAMI client id；Bicep 注入 |
| `HISTORY_CONTAINER` | 否 | `history` | blob 容器名 |
| `HISTORY_BLOB` | 否 | `foundry_retirement_history.json` | blob 文件名 |
| `SOURCE_URL` | 否 | learn.microsoft.com OpenAI retirement | 抓取源 |
| `WINDOW_DAYS` | 否 | `30` | 关注未来 N 天内退役的型号 |
| `SCHEDULE_CRON` | 否 | `0 30 8 * * *` | NCRONTAB，受 `WEBSITE_TIME_ZONE` 影响 |
| `WEBSITE_TIME_ZONE` | 否 | `China Standard Time` | timer 时区 |
| ~~`ACS_CONNECTION_STRING`~~ | — | — | **已废弃**，可删 |
| ~~`SENDER_ADDRESS`~~ | — | — | **已废弃**，可删 |
| ~~`RECIPIENT_ADDRESS`~~ | — | — | 仅 baseline 用过；收件人现在在 Flow 内 |

---

## 仓库结构

```
foundry-retirement-monitor/
├── app/                              # Function App 源码（云端版）
│   ├── function_app.py               # daily_check timer + report HTTP
│   ├── foundry_monitor.py            # 抓取/解析/diff/邮件渲染
│   ├── host.json
│   ├── requirements.txt
│   ├── local.settings.sample.json
│   └── .funcignore
├── infra/                            # Bicep IaC
│   ├── main.bicep                    # 订阅级入口
│   ├── resources.bicep               # RG 内资源
│   ├── main.parameters.json
│   ├── abbreviations.json
│   └── main.json                     # 编译后 ARM（git ignored OK）
├── local-version/                    # 独立本地脚本版（无 Azure 依赖）
│   ├── foundry_retirement_monitor.py
│   ├── requirements.txt
│   └── README.md
├── deploy-infra.ps1 / deploy-code.ps1
├── trigger-func.ps1 / verify-blob.ps1
├── azure.yaml                        # azd 元数据（可选）
├── AGENTS.md                         # 给 AI 助手 / 后续维护者的导览
├── README.md
└── .gitignore
```

---

## 二次迭代路径（"我新增需求时该改哪里"）

| 需求 | 改哪里 |
|---|---|
| **新增邮件表格列**（比如 "Region"） | `app/foundry_monitor.py`: ① `RetirementRecord` dataclass 加字段 ② `parse_tables()` 加列识别 ③ `render_email_html()` 的 `<th>` / `<td>` 追加 |
| **改抓取源 URL** | App Setting `SOURCE_URL`（无需改代码） |
| **改时间窗口 N 天** | App Setting `WINDOW_DAYS` |
| **改触发时间** | App Setting `SCHEDULE_CRON` + `WEBSITE_TIME_ZONE`，6 字段 NCRONTAB |
| **加 / 改收件人** | **不动代码**：去 Power Automate Flow → Send an email (V2) → To 字段，分号分隔 |
| **改发件人** | Power Automate Flow → Send email step → 用其他 M365 账号重新建 connection；或换成 Outlook.com / Gmail connector |
| **加抄送 / 密送** | Power Automate Flow → Send email (V2) 的高级选项里有 CC/BCC |
| **加 Teams / Slack / 钉钉 通知** | Power Automate Flow 里在 "Send email" 后并联一步 Teams Post message / Webhook，**函数代码不动**（webhook 接的是 Flow，不是某个具体 connector） |
| **改邮件样式** | `app/foundry_monitor.py` → `render_email_html()`；Outlook desktop 要点见 [AGENTS.md](AGENTS.md) |
| **新增公开页面 / API** | `app/function_app.py` 末尾仿 `@app.route("report")` 加一个新 route |
| **本地调试不发邮件** | 不设 `MAILER_WEBHOOK_URL`，代码会 log error 但不抛；或本地跑 `local-version/foundry_retirement_monitor.py`（生成 HTML 不发邮件） |

---

## 故障排查

- **`KeyBasedAuthenticationNotPermitted`** — 订阅策略禁用共享密钥。本项目已是 FC1 + 全 MI，理论上不会触发；如触发，确认 `allowSharedKeyAccess=false` 且没有用 SAS。
- **`InternalSubscriptionIsOverQuotaForSku` (Y1)** — 切 region；FC1 不受 Y1 限制。
- **`MAILER_WEBHOOK_URL` 存进去后值被截断到 `&` 处** — 不要用 `az functionapp config appsettings set`，改用本 README 第 3 步的 `az rest PUT`。
- **Outlook 桌面版日期列变成 3 行竖着写** — `2025-10-06` 这种带连字符的字符串在 Word renderer 里会换行。`render_email_html()` 已经在 Version / Retirement td 上加了 `nowrap="nowrap"` HTML 属性 + 替换 `-` 为 `&#8209;`（U+2011 non-breaking hyphen），如再发生检查这两处。
- **本地命令行看不到 blob** — 给自己加 `Storage Blob Data Reader`：
  ```powershell
  $me = az ad signed-in-user show --query id -o tsv
  az role assignment create --assignee $me --role 'Storage Blob Data Reader' `
    --scope (az storage account show -g rg-foundry-monitor -n stznnzcoperxcfc --query id -o tsv)
  ```

---

## 可选：清理已废弃的 ACS 资源

切换到 Power Automate 后，ACS / Email Service / managed domain 已经不再用，可以删：

```powershell
az communication email domain delete -g rg-foundry-monitor `
  --email-service-name email-znnzcoperxcfc --name AzureManagedDomain --yes
az communication email delete -g rg-foundry-monitor -n email-znnzcoperxcfc --yes
az communication delete       -g rg-foundry-monitor -n acs-znnzcoperxcfc   --yes

# 同时清掉 Function App 里残留的环境变量
az functionapp config appsettings delete -g rg-foundry-monitor -n func-znnzcoperxcfc `
  --setting-names ACS_CONNECTION_STRING SENDER_ADDRESS
```

> 也建议把 `infra/resources.bicep` 里 ACS / Email Service 段落删除，下次 `az deployment sub create` 时会自动清。

---

## 本地版

如果你只想在自己的机器上跑一次 + 在浏览器看 HTML 报告，不想搞 Azure：见 [`local-version/README.md`](local-version/README.md)。
