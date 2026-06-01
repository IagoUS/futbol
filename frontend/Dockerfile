# Multi-stage: build React → servir estáticos con nginx
# Build args para inyectar REACT_APP_API_URL en tiempo de build
# (CRA congela las env vars en build time, no runtime).

FROM node:20-alpine AS build
WORKDIR /app
ARG REACT_APP_API_URL=https://biwenger-backend.fly.dev
ENV REACT_APP_API_URL=$REACT_APP_API_URL
COPY package*.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
EXPOSE 8080
# Railway inyecta PORT en runtime; Fly pasa PORT vía [env] en fly.toml.
# Si no hay PORT (build local), usamos 8080.
CMD ["/bin/sh", "-c", "export PORT=${PORT:-8080} && envsubst '${PORT}' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
