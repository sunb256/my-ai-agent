FROM node:22-bookworm-slim AS build

WORKDIR /app

ARG VITE_AG_UI_URL=/agent
ENV VITE_AG_UI_URL=${VITE_AG_UI_URL}

COPY src/frontend/web/package*.json ./
RUN npm ci

COPY src/frontend/web/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80