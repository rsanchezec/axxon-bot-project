"""
voice_live_manager.py - Gestor de sesiones de voz con Azure Voice Live API (SDK nuevo)

Reemplaza voice_manager.py (SDK viejo con WebSocket manual + threading)
usando el SDK azure-ai-voicelive que es fully async.

CAMBIOS CLAVE vs voice_manager.py:
  - SDK viejo: websocket-client manual, URL construida a mano, agent-id (GUID),
    agent-connection-string, threading sincronico
  - SDK nuevo: azure-ai-voicelive con connect(), AgentSessionConfig por nombre,
    fully async con asyncio

DEPENDENCIAS:
  pip install "azure-ai-voicelive[aiohttp]>=1.2.0b4" azure-identity python-dotenv
  pip install numpy sounddevice
"""

import os
import json
import base64
import logging
import asyncio
import threading
import numpy as np
import sounddevice as sd
from collections import deque
from typing import Optional, Callable, Any
from azure.identity.aio import DefaultAzureCredential
from azure.ai.voicelive.aio import connect, AgentSessionConfig

logger = logging.getLogger(__name__)

AUDIO_SAMPLE_RATE = 24000  # 24 kHz - formato requerido por Voice Live


# =============================================================================
# HELPER: _sdk_event_to_dict
# =============================================================================

def _sdk_event_to_dict(raw_event) -> dict:
    """Convierte un evento del SDK (string, dict, o objeto tipado) a dict."""
    if isinstance(raw_event, str):
        return json.loads(raw_event)

    if isinstance(raw_event, dict):
        return raw_event

    # Objeto tipado del SDK - intentar multiples formas de convertirlo
    for method_name in ('model_dump', 'as_dict', 'to_dict'):
        method = getattr(raw_event, method_name, None)
        if method:
            try:
                return method()
            except Exception:
                pass

    if hasattr(raw_event, 'model_dump_json'):
        try:
            return json.loads(raw_event.model_dump_json())
        except Exception:
            pass

    if hasattr(raw_event, '__dict__'):
        result = {k: v for k, v in raw_event.__dict__.items() if not k.startswith('_')}
        if result:
            return result

    event_type = getattr(raw_event, 'type', None)
    if event_type:
        return {"type": str(event_type), "_raw": str(raw_event)[:500]}

    return {"type": "unknown", "_raw": str(raw_event)[:500]}


# =============================================================================
# CLASE: AudioPlayerAsync
# =============================================================================

class AudioPlayerAsync:
    """Reproduce audio usando un buffer en cola con sounddevice.
    Usado solo cuando enable_local_audio=True (testing local)."""

    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()
        self.stream = sd.OutputStream(
            callback=self._callback,
            samplerate=AUDIO_SAMPLE_RATE,
            channels=1,
            dtype=np.int16,
            blocksize=2400,
        )
        self.playing = False

    def _callback(self, outdata, frames, time_info, status):
        if status:
            logger.warning(f"Stream status: {status}")

        with self.lock:
            data = np.empty(0, dtype=np.int16)
            while len(data) < frames and len(self.queue) > 0:
                item = self.queue.popleft()
                frames_needed = frames - len(data)
                data = np.concatenate((data, item[:frames_needed]))
                if len(item) > frames_needed:
                    self.queue.appendleft(item[frames_needed:])
            if len(data) < frames:
                data = np.concatenate((data, np.zeros(frames - len(data), dtype=np.int16)))

        outdata[:] = data.reshape(-1, 1)

    def add_data(self, data: bytes):
        with self.lock:
            np_data = np.frombuffer(data, dtype=np.int16)
            self.queue.append(np_data)
            if not self.playing and len(self.queue) > 0:
                self.start()

    def start(self):
        if not self.playing:
            self.playing = True
            self.stream.start()

    def stop(self):
        with self.lock:
            self.queue.clear()
        self.playing = False
        self.stream.stop()

    def terminate(self):
        with self.lock:
            self.queue.clear()
        self.stream.stop()
        self.stream.close()


# =============================================================================
# CLASE: VoiceLiveSession
# =============================================================================

class VoiceLiveSession:
    """
    Sesion de voz individual con Azure Voice Live (SDK nuevo, fully async).

    Reemplaza VoiceManager + VoiceLiveConnection + AzureVoiceLive del viejo
    voice_manager.py con una sola clase async que usa el SDK oficial.

    Uso:
        session = VoiceLiveSession(enable_local_audio=False)
        session.on_user_transcript = my_callback
        session.on_agent_audio = my_audio_callback
        await session.start()
        await session.send_audio(pcm_bytes)
        await session.stop()
    """

    def __init__(self, enable_local_audio: bool = False):
        """
        Args:
            enable_local_audio: Si True, reproduce audio en altavoces locales (testing).
                                Si False, solo envia audio via callbacks (servidor).
        """
        self.enable_local_audio = enable_local_audio
        self._connection = None
        self._connection_cm = None
        self._credential = None
        self._receive_task: Optional[asyncio.Task] = None
        self._audio_player: Optional[AudioPlayerAsync] = None
        self._stop_event = asyncio.Event()
        self.is_running = False

        # Callbacks para eventos (todos async)
        self.on_session_created: Optional[Callable[[str], Any]] = None
        self.on_user_transcript: Optional[Callable[[str], Any]] = None
        self.on_agent_response: Optional[Callable[[str], Any]] = None
        self.on_agent_audio_transcript: Optional[Callable[[str], Any]] = None
        self.on_agent_audio: Optional[Callable[[bytes], Any]] = None
        self.on_user_speech_started: Optional[Callable[[], Any]] = None

    async def start(self) -> str:
        """
        Inicia la sesion de voz: conecta a Voice Live, configura la sesion,
        y lanza la tarea de recepcion de eventos.

        Returns:
            "voice_session_started"

        Raises:
            ValueError: Si falta configuracion en .env o ya esta corriendo
        """
        if self.is_running:
            raise ValueError("Voice session already running")

        # --- Leer configuracion desde .env ---
        endpoint = os.environ.get("VOICELIVE_ENDPOINT") or os.environ.get("AZURE_VOICELIVE_ENDPOINT")
        if not endpoint:
            raise ValueError("VOICELIVE_ENDPOINT not configured in .env")

        agent_name = os.environ.get("AZURE_AGENT_NAME", "axxon-agent")

        project_name = os.environ.get("PROJECT_NAME") or os.environ.get("AI_FOUNDRY_PROJECT_NAME")
        if not project_name:
            raise ValueError("PROJECT_NAME not configured in .env")

        logger.info(f"Connecting to Voice Live - Endpoint: {endpoint}, Agent: {agent_name}, Project: {project_name}")

        # --- Configuracion del agente (SDK nuevo: por nombre, no por ID) ---
        agent_config: AgentSessionConfig = {
            "agent_name": agent_name,
            "project_name": project_name,
        }

        # --- Credenciales ---
        self._credential = DefaultAzureCredential()

        # --- Conectar con Voice Live ---
        self._connection_cm = connect(
            endpoint=endpoint,
            credential=self._credential,
            api_version="2026-01-01-preview",
            agent_config=agent_config,
        )
        self._connection = await self._connection_cm.__aenter__()

        logger.info("Connection established with Voice Live")

        # --- Configurar sesion de voz ---
        session_config = {
            "turn_detection": {
                "type": "azure_semantic_vad",
                "threshold": 0.7,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "remove_filler_words": True,
                "end_of_utterance_detection": {
                    "model": "semantic_detection_v1",
                    "threshold": 0.5,
                    "timeout": 3,
                },
            },
            "input_audio_noise_reduction": {
                "type": "azure_deep_noise_suppression"
            },
            "input_audio_echo_cancellation": {
                "type": "server_echo_cancellation"
            },
            "voice": {
                "name": "es-AR-ElenaNeural",
                "type": "azure-standard",
                "temperature": 0.8,
                "speaking-rate": 1
            },
        }

        try:
            await self._connection.session.update(session=session_config)
            logger.info("Session configured via session.update()")
        except Exception as e:
            logger.warning(f"session.update() failed: {e}, trying raw send()...")
            session_update = {"type": "session.update", "session": session_config, "event_id": ""}
            await self._connection.send(json.dumps(session_update))
            logger.info("Session configured via raw send()")

        # --- Audio player local (solo para testing) ---
        if self.enable_local_audio:
            self._audio_player = AudioPlayerAsync()
            logger.info("Local audio player initialized")

        # --- Lanzar tarea de recepcion ---
        self._stop_event.clear()
        self.is_running = True
        self._receive_task = asyncio.create_task(self._receive_loop())

        return "voice_session_started"

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Envia audio PCM al servidor Voice Live.

        Args:
            audio_data: Bytes de audio PCM 16-bit, mono, 24kHz
        """
        if not self.is_running or not self._connection:
            raise ValueError("Voice session not running")

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        await self._connection.input_audio_buffer.append(audio=audio_b64)

    async def cancel_response(self) -> None:
        """Cancela la respuesta actual del agente (cuando el usuario interrumpe)."""
        if not self.is_running or not self._connection:
            logger.warning("Cannot cancel response: session not running")
            return

        try:
            # Intentar el metodo del SDK primero
            if hasattr(self._connection, 'response') and hasattr(self._connection.response, 'cancel'):
                await self._connection.response.cancel()
            else:
                # Fallback: enviar JSON crudo
                cancel_msg = {"type": "response.cancel", "event_id": ""}
                await self._connection.send(json.dumps(cancel_msg))
            logger.info("Agent response cancelled")
        except Exception as e:
            logger.error(f"Error cancelling response: {e}")

    async def _call_callback(self, callback: Optional[Callable], *args) -> None:
        """Llama a un callback async de forma segura."""
        if callback is None:
            return
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Error in callback: {e}")

    async def _receive_loop(self) -> None:
        """Tarea async que recibe eventos del servidor y los procesa."""
        last_audio_item_id = None

        try:
            while not self._stop_event.is_set():
                try:
                    raw_event = await asyncio.wait_for(self._connection.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    if self._stop_event.is_set():
                        break
                    logger.error(f"Error receiving event: {e}")
                    continue

                if raw_event is None:
                    continue

                try:
                    event = _sdk_event_to_dict(raw_event)
                    event_type = event.get("type", "unknown")

                    if event_type == "session.created":
                        session_id = event.get("session", {}).get("id", "unknown")
                        logger.info(f"Session created: {session_id}")
                        await self._call_callback(self.on_session_created, session_id)

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = event.get("transcript", "")
                        logger.info(f"User transcript: {transcript}")
                        await self._call_callback(self.on_user_transcript, transcript)

                    elif event_type == "response.text.done":
                        text = event.get("text", "")
                        logger.info(f"Agent text: {text}")
                        await self._call_callback(self.on_agent_response, text)

                    elif event_type == "response.audio_transcript.done":
                        transcript = event.get("transcript", "")
                        logger.info(f"Agent audio transcript: {transcript}")
                        await self._call_callback(self.on_agent_audio_transcript, transcript)

                    elif event_type == "response.audio.delta":
                        if event.get("item_id") != last_audio_item_id:
                            last_audio_item_id = event.get("item_id")
                        audio_bytes = base64.b64decode(event.get("delta", ""))
                        if audio_bytes:
                            if self._audio_player:
                                self._audio_player.add_data(audio_bytes)
                            elif self.on_agent_audio:
                                await self._call_callback(self.on_agent_audio, audio_bytes)

                    elif event_type == "input_audio_buffer.speech_started":
                        logger.info("User started speaking")
                        if self._audio_player:
                            self._audio_player.stop()
                        await self._call_callback(self.on_user_speech_started)

                    elif event_type == "error":
                        error_details = event.get("error", {})
                        if isinstance(error_details, dict):
                            logger.error(f"Voice Live error: type={error_details.get('type')}, "
                                         f"code={error_details.get('code')}, "
                                         f"message={error_details.get('message')}")
                        else:
                            logger.error(f"Voice Live error: {error_details}")

                    elif event_type == "warning":
                        warn_msg = event.get("message", "") or event.get("warning", "")
                        logger.warning(f"Voice Live warning: {warn_msg}")

                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                    continue

        except asyncio.CancelledError:
            logger.info("Receive task cancelled")
        except Exception as e:
            logger.error(f"Fatal error in receive loop: {e}")
        finally:
            if self._audio_player:
                self._audio_player.terminate()
                self._audio_player = None
            logger.info("Receive loop stopped")

    async def stop(self) -> None:
        """Detiene la sesion de voz y libera todos los recursos."""
        if not self.is_running:
            return

        self._stop_event.set()
        self.is_running = False

        # Cancelar tarea de recepcion
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Cerrar conexion Voice Live
        if self._connection_cm:
            try:
                await self._connection_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing connection: {e}")
            self._connection = None
            self._connection_cm = None

        # Cerrar credenciales async
        if self._credential:
            try:
                await self._credential.close()
            except Exception:
                pass
            self._credential = None

        logger.info("Voice session stopped")
