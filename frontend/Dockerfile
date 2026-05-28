FROM node:20 AS build

WORKDIR /app

ARG VITE_API_BASE
ARG VITE_CAPTCHA_ENABLED
ARG VITE_TURNSTILE_SITE_KEY
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_CAPTCHA_ENABLED=$VITE_CAPTCHA_ENABLED
ENV VITE_TURNSTILE_SITE_KEY=$VITE_TURNSTILE_SITE_KEY

COPY package*.json ./

RUN npm install

COPY . .

RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
