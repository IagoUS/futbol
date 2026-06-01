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
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
