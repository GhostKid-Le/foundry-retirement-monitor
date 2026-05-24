# 本地版（local-version）

云端版（Azure Functions）部署在 `..\app\`，每天 08:30 自动跑 + 发邮件 + 公开 URL。
这里是**独立、可离线运行**的版本——一个 Python 脚本，跑完直接在浏览器打开 HTML。

## 用法

```powershell
cd local-version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python foundry_retirement_monitor.py
# 完成后会自动打开 foundry_retirement_report.html
```

## 文件

| 文件 | 说明 |
| --- | --- |
| `foundry_retirement_monitor.py` | 抓取 + 解析 + 渲染的单文件脚本 |
| `foundry_retirement_report.html` | 最近一次输出（可直接在浏览器打开） |
| `foundry_retirement_history.json` | 上次结果，用于「与昨日 diff」 |
| `requirements.txt` | `requests` + `beautifulsoup4` |

## 与云端版的区别

- 本地版渲染的是**网页报告**（深色卡片 + 表格）。
- 云端版渲染的是**邮件 HTML**（同样美观、移动端自适应），逻辑相同。
- 两者共享同一抓取/解析/diff 算法（云端版抽到了 `..\app\foundry_monitor.py`）。
