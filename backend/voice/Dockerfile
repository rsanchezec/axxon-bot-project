# Dockerfile para Azure Container Apps
# Servidor de voz - FastAPI WebSocket (puerto 8001)
#
# BUILD CONTEXT: debe ser backend/ (no backend/voice/)
#   docker build -f voice/Dockerfile -t axxon-voice-api .
#
# RUN LOCAL (testing):
#   docker run --env-file .env -p 8001:8001 axxon-voice-api

# Python 3.13 slim (3.14 aun no tiene imagen slim oficial)
FROM python:3.13-slim

# Variables de entorno para Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Crear directorio de trabajo
WORKDIR /app

# Instalar dependencias del servidor de voz
# (no se necesitan numpy ni sounddevice - son solo para el cliente standalone con mic/altavoces)
RUN pip install --no-cache-dir \
    "azure-ai-voicelive[aiohttp]>=1.2.0b4" \
    azure-identity \
    python-dotenv \
    fastapi \
    "uvicorn[standard]"

# Copiar los dos archivos del servidor de voz
COPY voice/voice_live_manager.py .
COPY voice/voice_live_server.py .

# NO copiar .env - las variables se configuran como secrets/env-vars en Azure Container Apps

# Usuario no-root por seguridad (crear ANTES de cambiar de usuario)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Exponer puerto 8001
EXPOSE 8001

# Health check para Azure (usa urllib de stdlib, no requiere requests)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

# Iniciar la aplicacion
CMD ["python", "-m", "uvicorn", "voice_live_server:app", "--host", "0.0.0.0", "--port", "8001"]
