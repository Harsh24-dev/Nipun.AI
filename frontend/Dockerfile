# ── Stage 1: build the Vite app ───────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Install deps against the lockfile for reproducible builds.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Optional: bake in the backend URL at build time (Vite inlines VITE_* at build).
# Leave unset to use the app's default (http://localhost:8000) / same-origin via nginx.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ── Stage 2: serve the static build ───────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app
# `serve -s` serves the SPA with history-API fallback (client-side routing works).
RUN npm install -g serve@14

COPY --from=build /app/dist ./dist

EXPOSE 3000
CMD ["serve", "-s", "dist", "-l", "3000"]
