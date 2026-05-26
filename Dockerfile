FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Shanghai

COPY app/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY app/foundry_monitor.py /app/foundry_monitor.py
COPY app/storage.py /app/storage.py
COPY app/web.py /app/web.py
COPY app/daily_job.py /app/daily_job.py

ENV HISTORY_PATH=/data/history.json \
    WINDOW_DAYS=30 \
    PORT=8000

EXPOSE 8000

# 默认启动 web 服务；CronJob 通过 command 覆盖为 ["python","daily_job.py"]。
CMD ["sh","-c","uvicorn web:app --host 0.0.0.0 --port ${PORT}"]
