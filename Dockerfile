FROM node:20-slim AS frontend-builder

WORKDIR /frontend

COPY FE/package.json FE/package-lock.json ./
RUN npm ci

COPY FE/ ./
RUN npm run build


FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 자동 인쇄용 헤드리스 크로미움 (playwright install-deps가 apt 의존성까지 같이 설치)
RUN playwright install --with-deps chromium

COPY . .

COPY --from=frontend-builder /frontend/dist ./FE/dist

COPY start.sh .
RUN chmod +x start.sh

CMD ["./start.sh"]
