FROM python:3.10-slim
ENV TZ=Asia/Colombo
RUN apt-get update && apt-get install -y tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt || true
CMD ["bash", "start.sh"]
