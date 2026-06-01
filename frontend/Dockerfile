# Multi-stage: build React → servir estáticos con `serve` (Node).
# REACT_APP_API_URL llega como build-arg porque CRA congela env vars en build time.

FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG REACT_APP_API_URL
ENV REACT_APP_API_URL=$REACT_APP_API_URL
RUN npm run build

FROM node:18-alpine
RUN npm install -g serve
WORKDIR /app
COPY --from=build /app/build ./build
EXPOSE 3000
CMD ["serve", "-s", "build", "-l", "3000"]
