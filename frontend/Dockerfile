# Dockerfile para Azure Container Apps
# Frontend React.js - Nginx (puerto 80)
#
# BUILD CONTEXT: debe ser frontend/
#   docker build -t axxon-frontend .
#
# RUN LOCAL (testing):
#   docker run -p 5173:80 axxon-frontend
#
# VARIABLES DE ENTORNO (se pasan en build time):
#   VITE_TEXT_WS_URL  - URL WebSocket del servidor de texto (ej: wss://axxon-text.azurecontainerapps.io/ws/chat)
#   VITE_VOICE_WS_URL - URL WebSocket del servidor de voz (ej: wss://axxon-voice.azurecontainerapps.io/ws/voice)

# --- Etapa 1: Build ---
FROM node:20-alpine AS build

WORKDIR /app

# Copiar archivos de dependencias primero (cache de Docker)
COPY package.json package-lock.json ./

# Instalar dependencias
RUN npm ci

# Copiar codigo fuente
COPY . .

# Variables de entorno de Vite (se inyectan en build time con --build-arg)
ARG VITE_TEXT_WS_URL
ARG VITE_VOICE_WS_URL

# Build de produccion (Vite embebe las VITE_ vars en el JS)
RUN npm run build

# --- Etapa 2: Servir con Nginx ---
FROM nginx:alpine

# Copiar config personalizada de nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copiar build de React al directorio de nginx
COPY --from=build /app/dist /usr/share/nginx/html

# Exponer puerto 80
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
