# syntax=docker/dockerfile:1
# Dev-mode image: runs `next dev` so `docker compose up` brings the whole stack
# up live at a URL. Production build (standalone output + `next start`) lands with
# the Kamal deploy slice.
FROM node:22-alpine
WORKDIR /app
# Corepack pins pnpm to the `packageManager` field so the container installs with
# the exact pnpm that wrote the lockfile (avoids pnpm 11's stricter defaults).
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack install
RUN pnpm install --frozen-lockfile
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]
