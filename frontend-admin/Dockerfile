# Administration de la plateforme (ADR 0089), image à part du front commerçant. Construit dans GitHub Actions, jamais sur
# le VPS : un `next build` prendrait la mémoire de la production.
#
#   docker build -t coges/admin:local frontend-admin
#
# Trois étapes : dépendances (pnpm, lockfile figé), build en `output: "standalone"`, puis
# une image d'exécution sans pnpm ni sources, sous un utilisateur sans privilège.

ARG NODE_IMAGE=node:22.23.3-bookworm-slim

FROM ${NODE_IMAGE} AS deps
WORKDIR /src
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

FROM ${NODE_IMAGE} AS build
WORKDIR /src
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NEXT_TELEMETRY_DISABLED=1
# Filet seulement : en production, Caddy envoie /api/v1/* à l'API avant le front.
ARG COGES_API_URL=http://api:8000
ENV COGES_API_URL=${COGES_API_URL}
COPY --from=deps /src/node_modules ./node_modules
COPY . .
RUN corepack enable && pnpm build

FROM ${NODE_IMAGE} AS runtime
WORKDIR /srv/admin
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /src/.next/standalone ./
COPY --from=build --chown=node:node /src/.next/static ./.next/static
COPY --from=build --chown=node:node /src/public ./public
# `node` (uid 1000) existe dans l'image officielle : aucun processus ne tourne en root.
USER node
EXPOSE 3000
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=30s \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
