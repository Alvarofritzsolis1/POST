FROM node:22-alpine AS build
WORKDIR /code
COPY apps/frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY apps/frontend/ ./
RUN npm run build

FROM nginx:stable-alpine
COPY infrastructure/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /code/dist/ /usr/share/nginx/html/
EXPOSE 8080
