FROM python:3.11-slim

# Node.js install (JS bots ke liye)
RUN apt-get update && apt-get install -y \
    curl procps && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p hosted_bots pending_uploads data

CMD ["python", "fix.py"]