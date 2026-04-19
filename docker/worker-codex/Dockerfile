FROM node:24-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        gh \
        git \
        jq \
        python3 \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex@0.121.0

WORKDIR /workspace
