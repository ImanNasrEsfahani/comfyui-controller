FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .

# Vite embeds these flags at BUILD TIME; root compose env_file does not set them.
ARG VITE_AUTH_UI_ENABLED=true
ARG VITE_WORKFLOW_STUDIO_ENABLED=true
ENV VITE_AUTH_UI_ENABLED=${VITE_AUTH_UI_ENABLED}
ENV VITE_WORKFLOW_STUDIO_ENABLED=${VITE_WORKFLOW_STUDIO_ENABLED}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
