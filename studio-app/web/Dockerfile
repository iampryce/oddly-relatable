# Dashboard image (Next.js standalone output). Build context: studio-app/web
#   docker build --build-arg API_URL=http://api:8000 -t oddstudio-web studio-app/web
FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The API address is fixed at build time into the /api rewrite; it is a private network name, not a secret.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN useradd --create-home --uid 10002 web
COPY --from=build --chown=web /app/.next/standalone ./
COPY --from=build --chown=web /app/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
