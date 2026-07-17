FROM python:3.12-slim AS builder

COPY requirements.txt ./requirements.txt

RUN pip3 install --no-cache-dir --user -r requirements.txt


FROM python:3.12-slim

RUN groupadd -r appuser && useradd -r -m -g  appuser appuser -d /home/appuser

WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . /app/web/

RUN chown -R appuser:appuser /home/appuser
RUN chown -R appuser:appuser /app
RUN chown -R appuser:appuser /app/web/web_logs
RUN chmod -R 777 /app/web/web_logs

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

USER appuser


CMD ["python", "-m", "web.main"]
