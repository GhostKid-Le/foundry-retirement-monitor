# Foundry Retirement Monitor

每日抓取 [Microsoft Learn — Azure AI Foundry / OpenAI model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule)，与昨日快照对比，通过 **Power Automate** 把美观的 HTML 邮件发到 Outlook（发件人 = 你自己），同时把**最新报告**挂在公开 HTTPS URL 上随时浏览。

> **当前形态**：AKS + Application Gateway (AGIC) + cert-manager (Let's Encrypt)。Web 服务一直在线，每日 08:30 CST 由 K8s CronJob 跑抓取+diff+发邮件。
> 历史版本（Flex Consumption Functions + ACS）已下线，相关代码已从仓库移除。

---

## 架构

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Resource Group: rg-foundry-monitor (westus2)                               │
│                                                                            │
│  Internet ─► Public IP (20.59.39.98)                                       │
│          ─► Application Gateway v2 (agw-foundry-monitor)                   │
│             ├─ HTTP  :80  → 301 redirect to HTTPS                          │
│             └─ HTTPS :443 (cert: Let's Encrypt, 自动续期)                  │
│                  │                                                         │
│                  ▼  AGIC (AKS addon, UAMI)                                 │
│             ┌──────────────────────────────────────────────────┐           │
│             │ AKS: aks-foundry-monitor                          │           │
│             │  ns foundry-monitor                               │           │
│             │  ├ Deployment web (uvicorn web:app, /healthz)    │           │
│             │  ├ Service web :80 → :8000                       │           │
│             │  ├ Ingress web  (tls=web-tls, host=*.cloudapp..) │           │
│             │  ├ PVC state    (Azure Files, history.json)      │           │
│             │  └ CronJob daily-check  30 0 * * * (UTC)         │           │
│             │       └─ POST JSON → Power Automate webhook      │           │
│             │  ns cert-manager (v1.15.3)                        │           │
│             │  ns kube-system: AGIC pod, omsagent               │           │
│             └──────────────────────────────────────────────────┘           │
│                                                                            │
│  ACR: acrfoundrymonitor  (kubelet identity → AcrPull)                      │
│  Log Analytics: log-foundry-monitor  (Container Insights)                  │
└────────────────────────────────────────────────────────────────────────────┘
                  │
                  ▼  POST {subject, html}
        ┌──────────────────────────────────┐
        │ Power Automate flow              │
        │  → Send email (V2) Office 365    │
        │     From: 你的 M365 账号         │
        │     To:   收件人列表（Flow 里维护）│
        └──────────────────────────────────┘
```

**公开访问**：<https://foundry-monitor.westus2.cloudapp.azure.com/>

### Azure 资源（`rg-foundry-monitor` / westus2）

| 资源 | 名称 | 备注 |
|---|---|---|
| AKS | `aks-foundry-monitor` | Standard_D2s_v5 ×2，addons: `omsagent` + `ingressApplicationGateway` |
| Application Gateway v2 | `agw-foundry-monitor` | autoscale 1-2，PIP `20.59.39.98` |
| VNet | `vnet-foundry-monitor` (10.30.0.0/16) | `snet-aks` 10.30.0.0/22，`snet-appgw` 10.30.4.0/24 |
| NSG | `nsg-snet-appgw` | 允许 Internet→80/443、GatewayManager、AzureLoadBalancer |
| ACR | `acrfoundrymonitor` | kubelet MI 拉取 |
| Log Analytics | `log-foundry-monitor` | Container Insights |
| User-Assigned MI | AGIC addon 自动创建 | 已授予 VNet `Network Contributor` |

> 部署会出现**第二个**资源组 `MC_rg-foundry-monitor_aks-foundry-monitor_westus2`，由 AKS 自动管理（VMSS、节点 LB、磁盘等），**不要手动改**。

---

## 仓库结构

```
foundry-retirement-monitor/
├── app/                       # Python 应用
│   ├── foundry_monitor.py     # 抓取 / 解析 / diff / 渲染 HTML 邮件
│   ├── storage.py             # 本地 JSON 历史（PVC 挂 /data）
│   ├── web.py                 # FastAPI: /  /report  /healthz
│   ├── daily_job.py           # CronJob 入口：跑一次 diff + 发邮件
│   └── requirements.txt
├── Dockerfile                 # python:3.11-slim + tzdata(Asia/Shanghai)
├── infra/
│   ├── main.bicep             # AKS + AppGw + VNet + NSG + RBAC（RG 作用域）
│   └── main.json              # 编译产物
├── k8s/
│   ├── 00-namespace.yaml
│   ├── 10-pvc.yaml            # Azure Files PVC (history.json 持久化)
│   ├── 20-secret.example.yaml # 复制为 20-secret.yaml 填 webhook URL
│   ├── 30-web.yaml            # Deployment + Service
│   ├── 40-ingress.yaml        # AGIC + cert-manager TLS
│   ├── 50-cronjob.yaml        # 每天 00:30 UTC = 08:30 CST
│   └── 60-clusterissuer.yaml  # Let's Encrypt prod (HTTP-01 via AppGw)
├── scripts/                   # PowerShell 助手脚本（部署 / 探活 / 重对账）
├── page.html                  # 渲染样例（手动预览邮件外观）
├── AGENTS.md                  # 给 AI 助手 / 后续维护者的导览
└── README.md
```

---

## 从零部署

> 前置：`az`、`kubectl`、Docker Desktop、订阅 Owner。Region 默认 westus2。

### 1) 部署基础设施（Bicep）

```powershell
cd foundry-retirement-monitor
az login
az account set --subscription <YOUR_SUB>
az group create -n rg-foundry-monitor -l westus2
az deployment group create -g rg-foundry-monitor -f infra\main.bicep
```

输出会包含 ACR / AKS / AppGw / PIP FQDN。

### 2) 构建镜像并推到 ACR

```powershell
$acr = 'acrfoundrymonitor'
az acr login -n $acr
docker build -t "$acr.azurecr.io/foundry-monitor:latest" .
docker push "$acr.azurecr.io/foundry-monitor:latest"
```

### 3) 取 AKS 凭据 + 安装 cert-manager

```powershell
az aks get-credentials -g rg-foundry-monitor -n aks-foundry-monitor --overwrite-existing
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml
kubectl -n cert-manager rollout status deploy/cert-manager-webhook
```

### 4) Power Automate Flow（拿 webhook URL）

1. <https://make.powerautomate.com> → **Create → Instant cloud flow** → trigger **"When a HTTP request is received"**。
2. Request body schema：
   ```json
   { "type": "object", "properties": { "subject": {"type":"string"}, "html": {"type":"string"} } }
   ```
3. 加 **"Send an email (V2)"** (Office 365 Outlook)：
   - **To** = `you@example.com; teammate@example.com`（分号分隔）
   - **Subject** = 表达式 `triggerBody()?['subject']`
   - **Body** = 切到 `</>` code view，填 `triggerBody()?['html']`
4. Save，复制 trigger 的 **HTTP POST URL**。

### 5) 创建 K8s 资源

```powershell
# 修改 60-clusterissuer.yaml 里的 email，再 apply
kubectl apply -f k8s\00-namespace.yaml
kubectl apply -f k8s\10-pvc.yaml
kubectl apply -f k8s\60-clusterissuer.yaml

# 把 webhook URL 放进 secret（不要进 git）
kubectl -n foundry-monitor create secret generic mailer-webhook --from-literal=url='<PASTE_FULL_URL>'

# 把 30-web.yaml / 50-cronjob.yaml 里的 __IMAGE__ 替换成 acr 全名
$img = "acrfoundrymonitor.azurecr.io/foundry-monitor:latest"
(Get-Content k8s\30-web.yaml)     -replace '__IMAGE__', $img | kubectl apply -f -
(Get-Content k8s\50-cronjob.yaml) -replace '__IMAGE__', $img | kubectl apply -f -
kubectl apply -f k8s\40-ingress.yaml
```

### 6) 验证

```powershell
kubectl -n foundry-monitor get pods,svc,ingress,certificate
# 等 certificate web-tls READY=True（首次 60-180s）

curl.exe -s -o NUL -w "https=%{http_code}`n" https://foundry-monitor.westus2.cloudapp.azure.com/healthz
# 期望 https=200
```

### 7) 手动触发一次 baseline 邮件

```powershell
kubectl -n foundry-monitor create job --from=cronjob/daily-check manual-1
kubectl -n foundry-monitor logs -l job-name=manual-1 -f
```

---

## 运行时配置

### Pod 环境变量

| 名称 | 默认 | 说明 |
|---|---|---|
| `HISTORY_PATH` | `/data/history.json` | 持久化文件路径（PVC 挂在 `/data`） |
| `WINDOW_DAYS` | `30` | 关注未来 N 天内退役的型号 |
| `SOURCE_URL` | learn.microsoft.com 默认 | 抓取源 |
| `MAILER_WEBHOOK_URL` | — | **CronJob 必需**，来自 secret `mailer-webhook` |
| `TZ` | `Asia/Shanghai` | 容器时区，邮件 / 日志时间戳显示 CST |

### CronJob 调度

`k8s/50-cronjob.yaml` 的 `schedule: "30 0 * * *"` 是 UTC 时间 = 北京时间 08:30。修改时间直接改这一行后 `kubectl apply`。

### 邮件收件人 / 抄送 / 抄送规则

**全部在 Power Automate Flow 内维护**，不动代码、不动 K8s。

---

## 常用运维

```powershell
# 看 web pod
kubectl -n foundry-monitor get pods
kubectl -n foundry-monitor logs deploy/web --tail=200

# 看最近一次 CronJob
kubectl -n foundry-monitor get jobs --sort-by=.status.startTime
kubectl -n foundry-monitor logs -l job-name=<jobname>

# 强制触发邮件
kubectl -n foundry-monitor create job --from=cronjob/daily-check manual-$(Get-Date -Format yyyyMMddHHmm)

# 看证书 / 续期
kubectl -n foundry-monitor get certificate,certificaterequest,order,challenge
kubectl describe certificate web-tls -n foundry-monitor

# 让 AGIC 立即把 Ingress 同步回 AppGw（部署完 Bicep 之后非常有用）
.\scripts\agic-reconcile.ps1

# 探活
.\scripts\probe.ps1   # 同时探 https / http
```

---

## 故障排查

- **`https` 502/timeout**：先看 AGIC 是否健康 (`kubectl -n kube-system logs -l app=ingress-appgw --tail=100`)，再看 `kubectl -n foundry-monitor get pods`。
- **`https` 直接 connection refused**：通常是 NSG 把 80/443 拦了。本仓库 Bicep 已经声明 `nsg-snet-appgw` 并把入站 80/443 加好；但 **Defender for Cloud 有时会自动创建/重挂 NSG**，发生后重跑 `az deployment group create -g rg-foundry-monitor -f infra\main.bicep` 即可把 Bicep 管的 NSG 挂回去。
- **每次 `az deployment group create` 之后 HTTPS 短暂 502 / 监听器消失**：Bicep 只声明 AppGw 骨架，HTTPS 监听器/SSL 证书是由 AGIC 动态写入的，部署会把它们短暂抹掉。30-60 秒后 AGIC 会自动重建，或手动跑 `.\scripts\agic-reconcile.ps1` 立刻刷新。
- **证书 `READY=False`**：`kubectl describe certificate web-tls -n foundry-monitor` 看 Order/Challenge 状态。常见原因：Let's Encrypt 限流（同域名 7 天 5 次），或 DNS / FQDN 没指向 PIP。
- **邮件没发出去 / `MAILER_WEBHOOK_URL` 截断**：必须用 `kubectl create secret --from-literal=url='<完整URL>'`，带引号；不要写进 YAML 提交进 git。
- **抓取失败但页面在浏览器能打开**：MS Learn 偶尔加 anti-bot，看 `daily-check` job 的日志里的 HTTP 状态码。

---

## 二次迭代路径

| 需求 | 改哪里 |
|---|---|
| 新增邮件表格列 | `app/foundry_monitor.py`：① `RetirementRecord` 加字段 ② `parse_tables()` 加列识别 ③ `render_email_html()` 的 `<th>`/`<td>` 追加 |
| 改抓取源 / 时间窗口 | Deployment / CronJob 的 `SOURCE_URL` / `WINDOW_DAYS` env |
| 改触发时间 | `k8s/50-cronjob.yaml` 的 `schedule`（Cron 走 UTC） |
| 加 / 改收件人 / 发件人 | **不动代码**，直接改 Power Automate Flow |
| 加 Teams / Slack 通知 | Power Automate Flow 里并联 Teams 步骤；后端不动 |
| 改邮件样式 | `app/foundry_monitor.py` → `render_email_html()`；Outlook desktop 注意 inline CSS + `nowrap` |
| 新增公开 API / 页面 | `app/web.py` 加 FastAPI route |
| 本地调试不发邮件 | 不设 `MAILER_WEBHOOK_URL`，CronJob 代码会 log 后跳过 |

---

## 本地版

只想在自己机器上跑一次、浏览器看 HTML，不想搞 Azure：见 [`local-version/README.md`](local-version/README.md)。
