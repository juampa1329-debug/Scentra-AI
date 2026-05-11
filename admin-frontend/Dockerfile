FROM node:20 AS build

WORKDIR /app

ARG VITE_API_BASE
ARG VITE_CLIENT_APP_BASE
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_CLIENT_APP_BASE=$VITE_CLIENT_APP_BASE

COPY package*.json ./

RUN npm install

COPY . .

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
