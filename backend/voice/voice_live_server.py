"""
voice_live_server.py - WebSocket Server para Modo Voz (SDK nuevo)

Reemplaza voice_websocket.py (SDK viejo con threading)
usando VoiceLiveSession de voice_live_manager.py que es fully async.

CAMBIOS CLAVE vs voice_websocket.py:
  - Ya no necesita threading ni event_loop manual: todo es async nativo
  - Usa VoiceLiveSession en vez de VoiceManager
  - Los callbacks son async directos (no necesitan run_coroutine_threadsafe)
  - Usa agent_name en vez de agent_id (GUID)

PROTOCOLO DE COMUNICACION (sin cambios para el frontend):

  1. Cliente conecta y envia:
     {"type": "init_voice", "user_id": "usuario_123"}

  2. Servidor responde:
     {"type": "voice_session_ready", "session_id": "..."}

  3. Cliente envia audio binario (PCM 16-bit, mono, 24kHz)

  4. Servidor envia eventos JSON:
     {"type": "user_transcript", "text": "..."}
     {"type": "agent_text", "text": "..."}
     {"type": "agent_transcript", "text": "..."}
     {"type": "input_audio_buffer.speech_started"}

  5. Servidor envia audio binario del agente (PCM 16-bit, mono, 24kHz)

  6. Cliente puede enviar:
     {"type": "stop_voice"} - detener sesion
     {"type": "response.cancel"} - interrumpir respuesta del agente

DEPENDENCIAS:
  pip install fastapi uvicorn python-dotenv
  pip install "azure-ai-voicelive[aiohttp]>=1.2.0b4" azure-identity
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
import json
import uvicorn
import logging
import asyncio
from voice_live_manager import VoiceLiveSession
import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env desde la carpeta padre (backend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Axxon AI Voice API")

# CORS: usar ALLOWED_ORIGINS del entorno (Azure) o localhost por defecto (desarrollo)
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# GESTOR DE CONEXIONES DE VOZ
# =============================================================================

class VoiceLiveConnectionManager:
    """
    Gestiona las sesiones de voz activas para cada usuario.

    Cada usuario tiene su propia VoiceLiveSession que se conecta
    independientemente a Azure Voice Live.
    """

    def __init__(self):
        # Diccionario: user_id -> (websocket, session)
        self.active_sessions: Dict[str, tuple[WebSocket, VoiceLiveSession]] = {}

    async def start_session(self, websocket: WebSocket, user_id: str) -> str:
        """
        Inicia una sesion de voz para un usuario.

        Args:
            websocket: Conexion WebSocket del cliente
            user_id: Identificador del usuario

        Returns:
            session_id del servicio Voice Live
        """
        try:
            # Crear sesion (sin audio local - el audio se envia al frontend)
            session = VoiceLiveSession(enable_local_audio=False)

            # --- Configurar callbacks async ---
            # Al ser fully async, no necesitamos run_coroutine_threadsafe
            # ni pasar el event_loop manualmente

            async def on_session_created(session_id: str):
                await _send_event(websocket, "voice_session_ready", {"session_id": session_id})

            async def on_user_transcript(transcript: str):
                await _send_event(websocket, "user_transcript", {"text": transcript})

            async def on_agent_text(text: str):
                await _send_event(websocket, "agent_text", {"text": text})

            async def on_agent_transcript(transcript: str):
                await _send_event(websocket, "agent_transcript", {"text": transcript})

            async def on_agent_audio(audio_bytes: bytes):
                logger.debug(f"Sending audio to client: {len(audio_bytes)} bytes")
                await websocket.send_bytes(audio_bytes)

            async def on_user_speech_started():
                logger.info("Notifying frontend: user interrupted")
                await _send_event(websocket, "input_audio_buffer.speech_started", {})

            session.on_session_created = on_session_created
            session.on_user_transcript = on_user_transcript
            session.on_agent_response = on_agent_text
            session.on_agent_audio_transcript = on_agent_transcript
            session.on_agent_audio = on_agent_audio
            session.on_user_speech_started = on_user_speech_started

            # Iniciar sesion de voz
            result = await session.start()

            # Guardar sesion activa
            self.active_sessions[user_id] = (websocket, session)
            logger.info(f"Voice session started for user {user_id}")
            return result

        except Exception as e:
            logger.error(f"Error starting voice session: {e}")
            raise

    async def send_audio(self, user_id: str, audio_data: bytes) -> None:
        """Envia audio del frontend a la sesion Voice Live del usuario."""
        if user_id not in self.active_sessions:
            logger.warning(f"No active voice session for user {user_id}")
            return

        _, session = self.active_sessions[user_id]
        try:
            await session.send_audio(audio_data)
        except Exception as e:
            logger.error(f"Error sending audio: {e}")

    async def cancel_response(self, user_id: str) -> None:
        """Cancela la respuesta actual del agente para un usuario."""
        if user_id not in self.active_sessions:
            logger.warning(f"No active voice session for user {user_id}")
            return

        _, session = self.active_sessions[user_id]
        try:
            await session.cancel_response()
            logger.info(f"Response cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"Error cancelling response: {e}")

    async def stop_session(self, user_id: str) -> None:
        """Detiene la sesion de voz de un usuario y libera recursos."""
        if user_id in self.active_sessions:
            _, session = self.active_sessions[user_id]
            await session.stop()
            del self.active_sessions[user_id]
            logger.info(f"Voice session stopped for user {user_id}")

    def get_stats(self) -> dict:
        """Estadisticas de sesiones activas."""
        return {
            "active_voice_sessions": len(self.active_sessions),
            "users": list(self.active_sessions.keys())
        }


# =============================================================================
# HELPER
# =============================================================================

async def _send_event(websocket: WebSocket, event_type: str, data: dict) -> None:
    """Envia un evento JSON al cliente via WebSocket."""
    try:
        message = {"type": event_type, **data}
        await websocket.send_json(message)
    except Exception as e:
        logger.error(f"Error sending event '{event_type}': {e}")


# =============================================================================
# INSTANCIA GLOBAL
# =============================================================================

connection_manager = VoiceLiveConnectionManager()


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    return {
        "message": "Axxon AI Voice API",
        "status": "online",
        "active_sessions": len(connection_manager.active_sessions)
    }


@app.get("/health")
async def health():
    stats = connection_manager.get_stats()
    return {"status": "healthy", "stats": stats}


@app.websocket("/ws/voice")
async def websocket_voice_endpoint(websocket: WebSocket):
    """WebSocket endpoint para conversacion por voz en tiempo real."""

    current_user_id = None

    try:
        await websocket.accept()
        logger.info("Voice WebSocket connection accepted")

        # Esperar mensaje de inicializacion
        init_data = await websocket.receive_json()

        if init_data.get("type") != "init_voice":
            await websocket.send_json({
                "type": "error",
                "message": "Expected 'init_voice' message first"
            })
            await websocket.close()
            return

        user_id = init_data.get("user_id", "anonymous_user")
        current_user_id = user_id

        # Iniciar sesion de voz
        try:
            session_id = await connection_manager.start_session(websocket, user_id)
            logger.info(f"Voice session {session_id} started for user {user_id}")
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Failed to start voice session: {str(e)}"
            })
            await websocket.close()
            return

        # Loop principal de mensajes
        while True:
            try:
                message = await websocket.receive()

                # Comando JSON
                if "text" in message:
                    data = json.loads(message["text"])
                    message_type = data.get("type")

                    if message_type == "stop_voice":
                        logger.info(f"Stopping voice session for {user_id}")
                        await connection_manager.stop_session(user_id)
                        await websocket.send_json({"type": "voice_session_stopped"})
                        break

                    elif message_type == "response.cancel":
                        logger.info(f"User {user_id} interrupted agent - cancelling response")
                        await connection_manager.cancel_response(user_id)

                # Audio binario del frontend
                elif "bytes" in message:
                    await connection_manager.send_audio(user_id, message["bytes"])

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })

    except WebSocketDisconnect:
        logger.info(f"Voice client disconnected: {current_user_id}")
        if current_user_id:
            await connection_manager.stop_session(current_user_id)

    except Exception as e:
        logger.error(f"Error in voice WebSocket: {e}")
        if current_user_id:
            await connection_manager.stop_session(current_user_id)


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("Axxon AI Voice Assistant API")
    print("=" * 60)
    print(f"URL: http://localhost:8001")
    print(f"WebSocket: ws://localhost:8001/ws/voice")
    print(f"Health: http://localhost:8001/health")
    print("=" * 60)
    print(f"Agent: {os.getenv('AZURE_AGENT_NAME', 'axxon-agent')}")
    print(f"Project: {os.getenv('PROJECT_NAME', 'N/A')}")
    print("=" * 60)
    print()

    uvicorn.run(
        "voice_live_server:app",
        host="0.0.0.0",
        port=8001,
        reload=True
    )
