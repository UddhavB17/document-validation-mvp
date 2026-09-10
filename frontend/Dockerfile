# DMEF frontend image (owned by ws-j-deploy-smoke). Next.js 14 standalone.
#
# Build:  docker build -f frontend/Dockerfile -t dmef-frontend:local .
# Run:    docker run -p 3000:3000 -e NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 dmef-frontend:local
#
# Cloud Run deploys this as a separate service with NEXT_PUBLIC_API_BASE_URL
# pointing at the API service URL. The brief names this NEXT_PUBLIC_API_URL;
# the codebase canonical name is NEXT_PUBLIC_API_BASE_URL (frontend/lib/api.ts);
# both are honoured at build time (URL wins when both are set).
FROM node:20-slim AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
# Resolve the brief/codebase env-name alias at build time.
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_URL:-${NEXT_PUBLIC_API_BASE_URL}}
RUN npm run build

FROM node:20-slim AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

COPY --from=builder --chown=appuser:appuser /app/.next/standalone ./
COPY --from=builder --chown=appuser:appuser /app/.next/static ./.next/static
COPY --from=builder --chown=appuser:appuser /app/public ./public

EXPOSE 3000

CMD ["node", "server.js"]
