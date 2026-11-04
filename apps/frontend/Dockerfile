# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /code
COPY apps/frontend/package*.json ./
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -s /run/secrets/proxy_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca npm ci --no-audit --no-fund; \
    else npm ci --no-audit --no-fund; fi
COPY apps/frontend/ ./
RUN npm run build

FROM nginx:stable-alpine
COPY infrastructure/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /code/dist/ /usr/share/nginx/html/
EXPOSE 8080
