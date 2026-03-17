# ======================================================================================
# ARCHIVO: agent_voice_live.py
# DESCRIPCION: Cliente de voz en tiempo real usando Azure Voice Live API + AI Foundry (SDK nuevo)
#
# Este archivo captura audio del microfono, lo envia al servicio Azure Voice Live,
# y reproduce la respuesta de voz del agente en los altavoces. Todo en tiempo real.
#
# MIGRACION DEL SDK VIEJO AL NUEVO:
#   VIEJO: WebSocket manual con URL construida a mano + agent-id (GUID)
#   NUEVO: SDK azure-ai-voicelive con connect() + agent por nombre
#
# ARQUITECTURA ASYNC:
#   El SDK nuevo es SOLO async. Se usan 3 tareas concurrentes con asyncio.gather():
#   1. Tarea async de envio: captura audio del microfono y lo envia al servidor
#   2. Tarea async de recepcion: recibe audio/eventos del servidor y los reproduce
#   3. Tarea async de teclado: monitorea el teclado para salir con 'q'
#
#   Las operaciones bloqueantes (leer microfono, leer teclado) se ejecutan con
#   asyncio.to_thread() para no bloquear el event loop.
#
# DEPENDENCIAS:
#   pip install "azure-ai-voicelive[aiohttp]>=1.2.0b4" azure-identity python-dotenv
#   pip install numpy sounddevice
# ======================================================================================

# ----------------------------------------------------------------------------------
# IMPORTACIONES
# ----------------------------------------------------------------------------------

# asyncio: motor principal del programa, maneja todas las tareas concurrentes
import asyncio

# os: para leer variables de entorno
import os

# json: para convertir mensajes a/desde formato JSON
import json

# base64: para codificar audio binario en texto base64 (requisito del protocolo)
import base64

# logging: para registrar eventos y errores en logs
import logging

# threading: solo para el Lock del AudioPlayerAsync (el callback de sounddevice corre en otro hilo)
import threading

# time: para pequenas esperas en el bucle de captura de audio
import time

# numpy: para procesar arrays de datos de audio (conversion de bytes a int16, etc.)
import numpy as np

# sounddevice: para capturar audio del microfono y reproducir en altavoces
import sounddevice as sd

# signal y sys: para manejar Ctrl+C y cierre limpio del programa
import signal
import sys

# deque: cola de doble extremo, usada como buffer eficiente de audio
from collections import deque

# datetime: para generar timestamps en los nombres de archivos de log
from datetime import datetime

# load_dotenv: carga variables de entorno desde el archivo .env
from dotenv import load_dotenv

# pathlib: para construir rutas de archivos de forma portable
from pathlib import Path

# DefaultAzureCredential: autenticacion automatica con Azure (az login, managed identity, etc.)
from azure.identity import DefaultAzureCredential

# connect: funcion del SDK nuevo que establece la conexion WebSocket con Voice Live
# AgentSessionConfig: tipo que define la configuracion del agente (nombre, proyecto, etc.)
from azure.ai.voicelive.aio import connect, AgentSessionConfig

# ----------------------------------------------------------------------------------
# VARIABLES GLOBALES
# ----------------------------------------------------------------------------------

# Evento para señalizar a todas las tareas que deben detenerse
stop_event = asyncio.Event()

# Frecuencia de muestreo del audio en Hz (24 kHz es el formato requerido por Voice Live)
AUDIO_SAMPLE_RATE = 24000

# Logger para este modulo
logger = logging.getLogger(__name__)

# Nombre del archivo de log de conversacion (se define en __main__)
logfilename = ""


# ======================================================================================
# HELPER: _sdk_event_to_dict
# ======================================================================================
# Convierte un evento del SDK (que puede ser string, dict, o un objeto tipado)
# a un diccionario plano para procesarlo de manera uniforme.
# ======================================================================================

def _sdk_event_to_dict(raw_event) -> dict:
    """Convierte cualquier tipo de evento del SDK a un diccionario."""
    # Si ya es un string JSON, parsearlo
    if isinstance(raw_event, str):
        return json.loads(raw_event)

    # Si ya es un dict, retornarlo tal cual
    if isinstance(raw_event, dict):
        return raw_event

    # Es un objeto tipado del SDK - intentar multiples formas de convertirlo

    # Opcion 1: model_dump() (Pydantic v2 - el mas comun en SDKs modernos de Azure)
    if hasattr(raw_event, 'model_dump'):
        try:
            return raw_event.model_dump()
        except Exception:
            pass

    # Opcion 2: as_dict() (patron comun en SDKs de Azure)
    if hasattr(raw_event, 'as_dict'):
        try:
            return raw_event.as_dict()
        except Exception:
            pass

    # Opcion 3: to_dict()
    if hasattr(raw_event, 'to_dict'):
        try:
            return raw_event.to_dict()
        except Exception:
            pass

    # Opcion 4: model_dump_json() -> json.loads()
    if hasattr(raw_event, 'model_dump_json'):
        try:
            return json.loads(raw_event.model_dump_json())
        except Exception:
            pass

    # Opcion 5: __dict__ del objeto (fallback generico)
    if hasattr(raw_event, '__dict__'):
        result = {}
        for key, value in raw_event.__dict__.items():
            if not key.startswith('_'):
                result[key] = value
        if result:
            return result

    # Opcion 6: extraer al menos el type
    event_type = getattr(raw_event, 'type', None)
    if event_type:
        return {"type": str(event_type), "_raw": str(raw_event)[:500]}

    # Ultimo recurso
    return {"type": "unknown", "_raw": str(raw_event)[:500]}


def _safe_print(text: str) -> None:
    """Print que maneja emojis y caracteres especiales en la consola de Windows.
    Windows usa encoding 'charmap' (cp1252) que no soporta emojis/unicode extendido."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Reemplazar caracteres que la consola de Windows no puede mostrar
        print(text.encode('ascii', errors='replace').decode('ascii'))


# ======================================================================================
# CLASE: AudioPlayerAsync
# ======================================================================================
# Reproduce audio usando un buffer en cola. El servidor envia fragmentos de audio
# (deltas) y esta clase los acumula y reproduce en orden sin cortes.
# Usa un Lock de threading porque el callback de sounddevice corre en un hilo del OS.
# ======================================================================================

class AudioPlayerAsync:

    def __init__(self):
        """Inicializa el reproductor con su buffer, stream de audio y estado."""
        # Cola de doble extremo para almacenar fragmentos de audio pendientes
        self.queue = deque()

        # Lock para sincronizacion (el callback de sounddevice corre en otro hilo del OS)
        self.lock = threading.Lock()

        # Stream de salida de audio (altavoces)
        self.stream = sd.OutputStream(
            callback=self.callback,       # Funcion que el stream llama cuando necesita datos
            samplerate=AUDIO_SAMPLE_RATE, # 24000 Hz
            channels=1,                   # Mono (1 canal)
            dtype=np.int16,               # Enteros de 16 bits con signo
            blocksize=2400,               # 2400 frames = 100ms de audio a 24kHz
        )

        # Flag que indica si el reproductor esta activo
        self.playing = False

    def callback(self, outdata, frames, time_info, status):
        """
        Callback llamado por sounddevice cuando el altavoz necesita mas datos.
        IMPORTANTE: este callback corre en un hilo del OS, por eso usa self.lock.
        """
        if status:
            logger.warning(f"Stream status: {status}")

        with self.lock:
            # Array vacio donde se acumularan los datos
            data = np.empty(0, dtype=np.int16)

            # Extraer datos de la cola hasta tener suficientes frames
            while len(data) < frames and len(self.queue) > 0:
                item = self.queue.popleft()
                frames_needed = frames - len(data)
                data = np.concatenate((data, item[:frames_needed]))
                if len(item) > frames_needed:
                    self.queue.appendleft(item[frames_needed:])

            # Rellenar con silencio si no hay suficientes datos
            if len(data) < frames:
                data = np.concatenate((data, np.zeros(frames - len(data), dtype=np.int16)))

        outdata[:] = data.reshape(-1, 1)

    def add_data(self, data: bytes):
        """Agrega un fragmento de audio al buffer. Inicia reproduccion si no esta activa."""
        with self.lock:
            np_data = np.frombuffer(data, dtype=np.int16)
            self.queue.append(np_data)
            if not self.playing and len(self.queue) > 0:
                self.start()

    def start(self):
        """Inicia la reproduccion."""
        if not self.playing:
            self.playing = True
            self.stream.start()

    def stop(self):
        """Detiene la reproduccion y limpia el buffer (ej: usuario empieza a hablar)."""
        with self.lock:
            self.queue.clear()
        self.playing = False
        self.stream.stop()

    def terminate(self):
        """Cierra el reproductor y libera recursos del sistema."""
        with self.lock:
            self.queue.clear()
        self.stream.stop()
        self.stream.close()


# ======================================================================================
# TAREA ASYNC: capture_and_send_audio
# ======================================================================================
# Captura audio del microfono y lo envia al servidor Voice Live.
# Usa asyncio.to_thread() para la lectura bloqueante del microfono,
# y await connection.send() para enviar (async nativo del SDK).
# ======================================================================================

async def capture_and_send_audio(connection) -> None:
    """Captura audio del microfono y lo envia al servidor en tiempo real."""
    logger.info("Iniciando captura de audio del microfono...")

    # Crear stream de entrada de audio (microfono)
    stream = sd.InputStream(
        channels=1,                   # Mono
        samplerate=AUDIO_SAMPLE_RATE, # 24000 Hz
        dtype="int16"                 # Enteros de 16 bits
    )

    try:
        stream.start()

        # 20ms de audio por ciclo (0.02 * 24000 = 480 frames)
        read_size = int(AUDIO_SAMPLE_RATE * 0.02)

        while not stop_event.is_set():
            # Verificar si hay datos de audio disponibles en el microfono
            if stream.read_available >= read_size:
                # Leer audio del microfono en un hilo separado para no bloquear el event loop
                # (stream.read puede bloquear brevemente)
                data, _ = await asyncio.to_thread(stream.read, read_size)

                # Codificar en base64 (el protocolo Voice Live transmite audio como texto)
                audio_b64 = base64.b64encode(data).decode("utf-8")

                # Enviar audio usando el recurso input_audio_buffer del SDK
                # En vez de send() con JSON crudo, usamos el metodo correcto del SDK
                await connection.input_audio_buffer.append(audio=audio_b64)
            else:
                # Si no hay datos del microfono, ceder el control al event loop brevemente
                await asyncio.sleep(0.001)

    except asyncio.CancelledError:
        logger.info("Tarea de envio de audio cancelada.")
    except Exception as e:
        print(f"[SEND ERROR] {type(e).__name__}: {e}")
        logger.error(f"Error en captura de audio: {e}")
    finally:
        stream.stop()
        stream.close()
        logger.info("Captura de audio cerrada.")


# ======================================================================================
# TAREA ASYNC: receive_and_playback
# ======================================================================================
# Recibe eventos del servidor y los procesa:
#   - Audio del agente -> lo reproduce en los altavoces
#   - Transcripciones -> las imprime en consola
#   - Errores -> los reporta
# Usa await connection.recv() directamente (async nativo del SDK).
# ======================================================================================

async def receive_and_playback(connection) -> None:
    """Recibe eventos del servidor Voice Live y los procesa."""
    last_audio_item_id = None
    audio_player = AudioPlayerAsync()

    logger.info("Iniciando recepcion y reproduccion de audio...")

    try:
        while not stop_event.is_set():
            try:
                # Recibir mensaje del servidor con timeout de 2 segundos
                # await directo: no bloquea el event loop, permite que otras tareas corran
                raw_event = await asyncio.wait_for(connection.recv(), timeout=2.0)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if stop_event.is_set():
                    break
                print(f"[RECV ERROR] {type(e).__name__}: {e}")
                logger.error(f"Error recibiendo mensaje: {e}")
                continue

            if raw_event is None:
                continue

            try:
                # --- Convertir el evento a diccionario ---
                # recv() retorna objetos tipados del SDK, no strings JSON.
                # Necesitamos convertirlos a dict para procesarlos uniformemente.
                event = _sdk_event_to_dict(raw_event)
                event_type = event.get("type", "unknown")

                # Solo imprimir eventos importantes (NO los deltas de alta frecuencia)
                # Los deltas de audio y transcripcion llegan docenas de veces por respuesta
                # e imprimir cada uno ralentiza el event loop y causa audio entrecortado
                if event_type not in ("response.audio.delta", "response.audio_transcript.delta"):
                    print(f"Evento recibido: {event_type}")

                # --- Procesar cada tipo de evento ---

                # Sesion creada exitosamente
                if event_type == "session.created":
                    session = event.get("session", {})
                    session_id = session.get("id", "desconocido") if isinstance(session, dict) else "desconocido"
                    print(f"  Session ID: {session_id}")
                    logger.info(f"Sesion creada: {session_id}")
                    write_conversation_log(f"SessionID: {session_id}")

                # Warning del servidor
                elif event_type == "warning":
                    warn_msg = event.get("message", "") or event.get("warning", "")
                    print(f"  [WARNING] {warn_msg}")

                # Transcripcion del audio del usuario (lo que dijo, como texto)
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    user_transcript = f'Usuario:\t{event.get("transcript", "")}'
                    _safe_print(f'\n\t{user_transcript}\n')
                    write_conversation_log(user_transcript)

                # Respuesta de texto del agente
                elif event_type == "response.text.done":
                    agent_text = f'Agente (texto):\t{event.get("text", "")}'
                    _safe_print(f'\n\t{agent_text}\n')
                    write_conversation_log(agent_text)

                # Transcripcion del audio del agente (lo que dijo, como texto)
                elif event_type == "response.audio_transcript.done":
                    agent_audio = f'Agente (audio):\t{event.get("transcript", "")}'
                    _safe_print(f'\n\t{agent_audio}\n')
                    write_conversation_log(agent_audio)

                # Fragmento de audio del agente (delta)
                elif event_type == "response.audio.delta":
                    if event.get("item_id") != last_audio_item_id:
                        last_audio_item_id = event.get("item_id")
                    bytes_data = base64.b64decode(event.get("delta", ""))
                    if bytes_data:
                        logger.debug(f"Audio recibido: {len(bytes_data)} bytes")
                    audio_player.add_data(bytes_data)

                # El usuario empezo a hablar (interrupcion)
                elif event_type == "input_audio_buffer.speech_started":
                    print("Usuario empezo a hablar")
                    audio_player.stop()

                # Error del servidor
                elif event_type == "error":
                    error_details = event.get("error", {})
                    if isinstance(error_details, dict):
                        error_type = error_details.get("type", "Desconocido")
                        error_code = error_details.get("code", "Desconocido")
                        error_message = error_details.get("message", "Sin mensaje")
                    else:
                        error_type = error_code = "Desconocido"
                        error_message = str(error_details)
                    print(f"ERROR del servidor: Type={error_type}, Code={error_code}, Message={error_message}")
                    logger.error(f"Server error: {error_type} {error_code} {error_message}")

            except Exception as e:
                print(f"[RECV PARSE ERROR] {type(e).__name__}: {e} | raw_type={type(raw_event).__name__}")
                logger.error(f"Error procesando evento: {e}")
                continue

    except asyncio.CancelledError:
        logger.info("Tarea de recepcion de audio cancelada.")
    except Exception as e:
        print(f"[RECV FATAL] {type(e).__name__}: {e}")
        logger.error(f"Error en reproduccion de audio: {e}")
    finally:
        audio_player.terminate()
        logger.info("Reproduccion de audio finalizada.")


# ======================================================================================
# TAREA ASYNC: wait_for_keyboard_quit
# ======================================================================================
# Monitorea el teclado esperando que el usuario presione 'q'.
# Usa asyncio.to_thread(input) para no bloquear el event loop.
# ======================================================================================

async def wait_for_keyboard_quit() -> None:
    """Espera a que el usuario presione 'q' + Enter para salir."""
    print("Presiona 'q' y Enter para salir del chat de voz.")

    while not stop_event.is_set():
        try:
            # input() es bloqueante, asi que lo ejecutamos en un hilo con to_thread
            # Esto permite que el event loop siga procesando las otras tareas
            user_input = await asyncio.to_thread(input)
            if user_input.strip().lower() == 'q':
                print("Saliendo del chat de voz...")
                stop_event.set()
                return
        except (EOFError, asyncio.CancelledError):
            return


# ======================================================================================
# FUNCION: write_conversation_log
# ======================================================================================

def write_conversation_log(message: str) -> None:
    """Escribe un mensaje en el archivo de log de conversacion."""
    with open(f'logs/{logfilename}', 'a') as conversation_log:
        conversation_log.write(message + "\n")


# ======================================================================================
# FUNCION PRINCIPAL ASYNC
# ======================================================================================
# Conecta a Voice Live, configura la sesion, y ejecuta 3 tareas concurrentes:
#   1. capture_and_send_audio: microfono -> servidor
#   2. receive_and_playback: servidor -> altavoces
#   3. wait_for_keyboard_quit: teclado -> señal de parada
#
# Las 3 tareas corren en PARALELO con asyncio.gather(), permitiendo que
# el event loop maneje todas sin bloquearse.
# ======================================================================================

async def main() -> None:
    """Funcion principal async que ejecuta el cliente de Voice Live."""

    # ----- Leer configuracion desde variables de entorno -----

    # Endpoint del servicio Voice Live
    endpoint = os.environ.get("VOICELIVE_ENDPOINT") or os.environ.get("AZURE_VOICELIVE_ENDPOINT")
    if not endpoint:
        print("ERROR: VOICELIVE_ENDPOINT no esta configurado en .env")
        return

    # Nombre del agente en AI Foundry (NUEVO: por nombre, no por ID)
    agent_name = os.environ.get("AZURE_AGENT_NAME", "axxon-agent")

    # Nombre del proyecto en AI Foundry
    project_name = os.environ.get("PROJECT_NAME") or os.environ.get("AI_FOUNDRY_PROJECT_NAME")
    if not project_name:
        print("ERROR: PROJECT_NAME no esta configurado en .env")
        return

    print(f"Conectando a Voice Live...")
    print(f"  Endpoint: {endpoint}")
    print(f"  Agente: {agent_name}")
    print(f"  Proyecto: {project_name}")

    # ----- Configuracion del agente (NUEVO: reemplaza query params manuales) -----
    agent_config: AgentSessionConfig = {
        "agent_name": agent_name,
        "project_name": project_name,
    }

    # ----- Credenciales de Azure -----
    credential = DefaultAzureCredential()

    # ----- Establecer conexion con Voice Live -----
    async with connect(
        endpoint=endpoint,
        credential=credential,
        api_version="2026-01-01-preview",
        agent_config=agent_config,
    ) as connection:

        print("Conexion establecida con Voice Live")

        # ----- Configurar la sesion de voz usando el recurso session del SDK -----
        # En vez de enviar JSON crudo con connection.send(), usamos connection.session.update()
        # que es el metodo correcto del SDK azure-ai-voicelive
        session_config = {
            "turn_detection": {
                "type": "azure_semantic_vad",
                "threshold": 0.3,
                "prefix_padding_ms": 200,
                "silence_duration_ms": 300,
                "remove_filler_words": False,
                "end_of_utterance_detection": {
                    "model": "semantic_detection_v1",
                    "threshold": 0.01,
                    "timeout": 2,
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
            await connection.session.update(session=session_config)
            print("Configuracion de sesion enviada (via session.update)")
        except Exception as e:
            print(f"[WARN] session.update() fallo: {e}, intentando con send() crudo...")
            # Fallback: enviar como JSON crudo
            session_update = {"type": "session.update", "session": session_config, "event_id": ""}
            await connection.send(json.dumps(session_update))
            print("Configuracion de sesion enviada (via send crudo)")

        write_conversation_log(f'Session Config: {json.dumps(session_config)}')

        print("\nIniciando chat de voz...\n")

        # ----- Ejecutar las 3 tareas en paralelo con asyncio.gather -----
        # ESTO ES EL CAMBIO CLAVE vs la version anterior:
        # Antes: 3 threads + keyboard_thread.join() que BLOQUEABA el event loop
        # Ahora: 3 tareas async que corren en paralelo SIN bloquear el event loop
        #
        # asyncio.gather() ejecuta todas las coroutines concurrentemente.
        # Cuando wait_for_keyboard_quit() termina (usuario presiona 'q'),
        # se activa stop_event y las otras 2 tareas terminan en su siguiente ciclo.

        send_task = asyncio.create_task(capture_and_send_audio(connection))
        recv_task = asyncio.create_task(receive_and_playback(connection))
        keyboard_task = asyncio.create_task(wait_for_keyboard_quit())

        # Esperar a que la tarea de teclado termine (usuario presiona 'q')
        await keyboard_task

        # Señalizar a las otras tareas que deben parar
        stop_event.set()

        # Dar un momento para que las tareas terminen limpiamente
        await asyncio.sleep(0.5)

        # Cancelar las tareas si aun estan corriendo
        send_task.cancel()
        recv_task.cancel()

        # Esperar a que se cancelen (suppress CancelledError)
        try:
            await send_task
        except asyncio.CancelledError:
            pass
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

    # Al salir del "async with", la conexion se cierra automaticamente
    print("Chat de voz finalizado.")


# ======================================================================================
# PUNTO DE ENTRADA DEL PROGRAMA
# ======================================================================================

if __name__ == "__main__":
    try:
        # Cambiar al directorio del script para que los paths relativos funcionen
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

        # Crear carpeta de logs si no existe
        if not os.path.exists('logs'):
            os.makedirs('logs')

        # Generar nombres de archivos de log con timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        logfilename = f"{timestamp}_conversation.log"

        # Configurar el sistema de logging
        logging.basicConfig(
            filename=f'logs/{timestamp}_voicelive.log',
            filemode="w",
            level=logging.DEBUG,
            format='%(asctime)s:%(name)s:%(levelname)s:%(message)s'
        )

        # Cargar variables de entorno desde la carpeta padre (backend/)
        load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

        # Manejador de señales para cierre limpio con Ctrl+C
        def signal_handler(signum, frame):
            print("\nSenal de interrupcion recibida, cerrando...")
            stop_event.set()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Ejecutar la funcion principal async
        asyncio.run(main())

    except Exception as e:
        print(f"Error: {e}")
        stop_event.set()
