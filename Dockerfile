FROM python:3.11-slim

LABEL maintainer="Ostap Konstantinov <o.konstantinov@pay-s.ru>"

WORKDIR /opt/app

RUN apt-get update \
    && apt-get install -y locales locales-all \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE 1 \
    PYTHONUNBUFFERED 1

COPY requirements.txt entrypoint.sh ./
RUN pip install -r requirements.txt \
    && chmod +x ./entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
