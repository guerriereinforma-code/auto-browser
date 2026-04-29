FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    fluxbox \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxkbcommon0 \
    nodejs \
    novnc \
    npm \
    procps \
    websockify \
    x11vnc \
    xvfb \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/browser-node

COPY package.json ./
# Install patchright (the undetected drop-in fork of Playwright) and pull
# its patched Chromium build. Patchright launches Chromium without
# `--enable-automation`, Runtime.enable / Console.enable / Page.frameAttached
# signals that Cloudflare-class detectors key on — the bot fingerprint we
# saw on HeyGen Studio. The patched binary is used by chromium.launchServer
# inside server.mjs (which imports from `patchright` instead of `playwright`).
RUN npm install --no-audit --no-fund \
  && npx patchright install chromium

COPY entrypoint.sh /entrypoint.sh
COPY server.mjs /opt/browser-node/server.mjs
RUN chmod +x /entrypoint.sh

EXPOSE 5900 6080 9223

CMD ["/entrypoint.sh"]
