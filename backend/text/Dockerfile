# Dockerfile para Azure Container Apps
# Servidor de texto - FastAPI WebSocket (puerto 8000)
#
# BUILD CONTEXT: debe ser backend/ (no backend/text/)
#   docker build -f text/Dockerfile -t axxon-text-api .
#
# RUN LOCAL (testing):
#   docker run --env-file .env -p 8000:8000 axxon-text-api

# Python 3.13 slim (3.14 aun no tiene imagen slim oficial)
FROM python:3.13-slim

# Variables de entorno para Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Crear directorio de trabajo
WORKDIR /app

# Instalar solo las dependencias necesarias para el servidor de texto
# (no se necesitan azure-ai-voicelive, numpy, sounddevice que son solo para voz)
RUN pip install --no-cache-dir \
    "azure-ai-projects==2.0.0b3" \
    "openai==2.15.0" \
    python-dotenv \
    azure-identity \
    jsonref \
    fastapi \
    "uvicorn[standard]"

# Copiar el servidor de texto
COPY text/agent_text_web_socket.py .

# NO copiar .env - las variables se configuran como secrets/env-vars en Azure Container Apps

# Usuario no-root por seguridad (crear ANTES de cambiar de usuario)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Exponer puerto 8000
EXPOSE 8000

# Health check para Azure (usa urllib de stdlib, no requiere requests)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Iniciar la aplicacion
CMD ["python", "-m", "uvicorn", "agent_text_web_socket:app", "--host", "0.0.0.0", "--port", "8000"]
