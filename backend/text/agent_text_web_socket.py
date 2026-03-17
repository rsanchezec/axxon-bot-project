# ======================================================================================
# ARCHIVO: agent_websocket.py
# DESCRIPCION: API WebSocket para integrar el agente de Azure AI Foundry con un frontend
#
# Este archivo crea un servidor web con WebSocket que permite a un frontend (React, HTML, etc.)
# comunicarse en tiempo real con un agente de Azure AI Foundry.
#
# SDK USADO: Azure AI Foundry (nuevo) - usa "conversations" y "responses" en vez del viejo
#            sistema de "threads", "runs" y "messages".
#
# FLUJO GENERAL:
#   1. El frontend se conecta por WebSocket y envia su user_id
#   2. El servidor crea una "conversation" (sesion de chat) en Azure AI Foundry
#   3. Cada mensaje del usuario se envia al agente con responses.create()
#   4. La respuesta del agente se devuelve al frontend por el mismo WebSocket
# ======================================================================================

# ----------------------------------------------------------------------------------
# IMPORTACIONES
# ----------------------------------------------------------------------------------

# FastAPI: framework web para crear la API y manejar WebSockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# CORSMiddleware: permite que el frontend (en otro puerto/dominio) se conecte al backend
from fastapi.middleware.cors import CORSMiddleware

# Dict y Optional: tipos de Python para tipar diccionarios y valores opcionales
from typing import Dict, Optional

# json: para convertir mensajes entre texto JSON y diccionarios de Python
import json

# uvicorn: servidor ASGI que ejecuta la aplicacion FastAPI
import uvicorn

# os: para leer variables de entorno (configuracion)
import os

# time: para obtener timestamps en el health check
import time

# logging: para imprimir logs estructurados en la consola
import logging

# asyncio: para ejecutar funciones sincronas (del SDK de Azure) sin bloquear el servidor
import asyncio

# AIProjectClient: cliente principal del SDK nuevo de Azure AI Foundry
from azure.ai.projects import AIProjectClient

# DefaultAzureCredential: autenticacion automatica con Azure (usa az login, managed identity, etc.)
from azure.identity import DefaultAzureCredential

# load_dotenv: carga las variables del archivo .env al entorno del proceso
from dotenv import load_dotenv

# pathlib: para construir rutas de archivos de forma portable
from pathlib import Path

# ----------------------------------------------------------------------------------
# CONFIGURACION INICIAL
# ----------------------------------------------------------------------------------

# Cargar las variables de entorno desde el archivo .env en la carpeta padre (backend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Configurar el sistema de logging para que imprima fecha, nombre del modulo y nivel
logging.basicConfig(
    level=logging.INFO,  # Nivel minimo: INFO (tambien muestra WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'  # Formato de cada linea de log
)

# Crear un logger especifico para este archivo
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------
# CREACION DE LA APLICACION FASTAPI
# ----------------------------------------------------------------------------------

# Crear la instancia de FastAPI que sera nuestro servidor web
app = FastAPI(
    title="Axxon AI Agent API",  # Nombre que aparece en la documentacion automatica (/docs)
    description="WebSocket API para agente AI con Azure AI Foundry",  # Descripcion en /docs
    version="2.0.0"  # Version de la API
)

# ----------------------------------------------------------------------------------
# CONFIGURACION DE CORS (Cross-Origin Resource Sharing)
# ----------------------------------------------------------------------------------

# CORS permite que un frontend en un dominio/puerto diferente se conecte a este backend.
# Sin CORS, el navegador bloquea las peticiones entre diferentes origenes por seguridad.

# Leer los origenes permitidos desde la variable de entorno ALLOWED_ORIGINS
# Si no existe, usar los puertos de desarrollo por defecto (Vite=5173, React=3000)
allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",  # Nombre de la variable de entorno
    "http://localhost:5173,http://localhost:3000"  # Valor por defecto si no existe
).split(",")  # Separar por comas para obtener una lista

# Registrar en los logs que origenes estan permitidos
logger.info(f"CORS configurado para origenes: {allowed_origins}")

# Agregar el middleware de CORS a la aplicacion FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Lista de origenes que pueden conectarse
    allow_credentials=True,  # Permitir envio de cookies/credenciales
    allow_methods=["*"],  # Permitir todos los metodos HTTP (GET, POST, etc.)
    allow_headers=["*"],  # Permitir todos los headers HTTP
)


# ======================================================================================
# CLASE: AgentChatManager
# ======================================================================================
# Esta clase se encarga de toda la logica de comunicacion con Azure AI Foundry.
# Gestiona las conexiones WebSocket y las conversaciones de cada usuario.
# ======================================================================================

class AgentChatManager:

    def __init__(self):
        """
        Constructor: se ejecuta una sola vez al iniciar el servidor.
        Configura la conexion con Azure AI Foundry y prepara los diccionarios
        para almacenar las sesiones de los usuarios.
        """

        # Leer el endpoint del proyecto de AI Foundry desde las variables de entorno
        # Ejemplo: "https://axxon-bot-services.services.ai.azure.com/api/projects/proj-axxon-bot"
        self.foundry_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")

        # Leer el nombre del agente desde las variables de entorno
        # Si no esta definido, usar "axxon-agent" como valor por defecto
        self.agent_name = os.getenv("AZURE_AGENT_NAME", "axxon-agent")

        # Validar que el endpoint este configurado (es obligatorio)
        if not self.foundry_endpoint:
            logger.error("FOUNDRY_PROJECT_ENDPOINT no esta configurado")
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT es requerido")

        # Crear el cliente de Azure AI Foundry usando el endpoint y credenciales de Azure
        # DefaultAzureCredential intenta autenticarse automaticamente usando:
        # 1. Variables de entorno, 2. Managed Identity, 3. Azure CLI (az login), etc.
        self.project_client = AIProjectClient(
            endpoint=self.foundry_endpoint,  # URL del proyecto en AI Foundry
            credential=DefaultAzureCredential(),  # Credenciales automaticas de Azure
        )

        # Obtener un cliente compatible con la API de OpenAI desde el cliente del proyecto
        # Este cliente nos da acceso a conversations.create() y responses.create()
        self.openai_client = self.project_client.get_openai_client()

        # Diccionario para guardar la conversacion de cada usuario
        # Clave: user_id (string), Valor: conversation_id (string)
        # Ejemplo: {"usuario_123": "conv_abc456", "usuario_789": "conv_def012"}
        self.user_conversations: Dict[str, str] = {}

        # Diccionario para guardar la conexion WebSocket activa de cada usuario
        # Clave: user_id (string), Valor: objeto WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

        # Log de confirmacion de que todo se inicializo correctamente
        logger.info(f"Agent Chat Manager inicializado | Agent: {self.agent_name}")

    async def connect(self, websocket: WebSocket, user_id: str) -> Optional[str]:
        """
        Conecta un usuario al sistema de chat.

        Si el usuario ya tiene una conversacion previa, la recupera (historial persistente).
        Si es un usuario nuevo, crea una nueva conversacion en Azure AI Foundry.

        Parametros:
            websocket: la conexion WebSocket del usuario
            user_id: identificador unico del usuario (viene del frontend)

        Retorna:
            El conversation_id (string) si fue exitoso, o None si hubo un error.
        """
        try:
            # Guardar la conexion WebSocket del usuario en el diccionario
            self.active_connections[user_id] = websocket

            # Verificar si este usuario ya tiene una conversacion activa
            if user_id in self.user_conversations:
                # Si ya existe, simplemente recuperar el ID de la conversacion
                conversation_id = self.user_conversations[user_id]
                logger.info(f"Sesion recuperada: {user_id}")
            else:
                # Si no existe, crear una nueva conversacion en Azure AI Foundry
                # asyncio.to_thread() ejecuta esta funcion sincrona en un hilo separado
                # para no bloquear el servidor mientras Azure responde
                conversation = await asyncio.to_thread(
                    self.openai_client.conversations.create  # Llamada al SDK de AI Foundry
                )
                # Extraer el ID de la conversacion recien creada
                conversation_id = conversation.id
                # Guardar la relacion usuario -> conversacion para futuras reconexiones
                self.user_conversations[user_id] = conversation_id
                logger.info(f"Nueva sesion: {user_id} | Conversation: {conversation_id}")

            # Retornar el ID de la conversacion (nueva o recuperada)
            return conversation_id

        except Exception as e:
            # Si algo falla (ej: error de red, credenciales invalidas), loguear y retornar None
            logger.error(f"Error en conexion para {user_id}: {e}")
            return None

    def disconnect(self, user_id: str):
        """
        Desconecta un usuario del WebSocket.

        IMPORTANTE: Solo elimina la conexion WebSocket, NO elimina la conversacion.
        Esto permite que el usuario se reconecte despues y recupere su historial.

        Parametros:
            user_id: identificador del usuario a desconectar
        """
        # Solo eliminar la conexion WebSocket activa, mantener la conversacion
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"Usuario {user_id} desconectado")

    async def send_to_agent(self, user_id: str, message: str) -> Optional[str]:
        """
        Envia un mensaje del usuario al agente de AI Foundry y retorna la respuesta.

        Esta es la funcion principal del chat. Usa responses.create() que en una sola
        llamada: envia el mensaje, ejecuta el agente, y retorna la respuesta.

        En el SDK viejo esto requeria 4 pasos:
          1. create_message() - crear el mensaje del usuario
          2. create_run() - ejecutar el asistente
          3. Polling en loop - esperar a que el asistente termine
          4. list_messages() - obtener la respuesta

        Ahora es UNA sola llamada: responses.create()

        Parametros:
            user_id: identificador del usuario que envia el mensaje
            message: texto del mensaje del usuario

        Retorna:
            El texto de respuesta del agente (string) o None si hubo un error.
        """
        try:
            # Verificar que el usuario tenga una conversacion activa
            if user_id not in self.user_conversations:
                logger.warning(f"No hay sesion para {user_id}")
                return None

            # Obtener el ID de la conversacion del usuario
            conversation_id = self.user_conversations[user_id]

            # Enviar el mensaje al agente y obtener la respuesta en UNA sola llamada
            # asyncio.to_thread() lo ejecuta en un hilo separado para no bloquear el servidor
            response = await asyncio.to_thread(
                self.openai_client.responses.create,  # Metodo del SDK de AI Foundry
                conversation=conversation_id,  # ID de la conversacion donde enviar el mensaje
                extra_body={
                    "agent": {
                        "name": self.agent_name,  # Nombre del agente (ej: "axxon-agent")
                        "type": "agent_reference"  # Indica que es una referencia a un agente existente
                    }
                },
                input=message  # El texto que escribio el usuario
            )

            logger.info(f"Respuesta generada para {user_id}")

            # response.output_text contiene el texto de respuesta del agente
            return response.output_text

        except Exception as e:
            # Si algo falla (ej: timeout, error del agente), loguear y retornar None
            logger.error(f"Error enviando mensaje para {user_id}: {e}")
            return None

    def cleanup_user_session(self, user_id: str) -> bool:
        """
        Elimina la conversacion de un usuario de la memoria del servidor.

        Esto hace que la proxima vez que el usuario se conecte, se cree una
        conversacion completamente nueva (sin historial previo).

        Parametros:
            user_id: identificador del usuario cuya sesion se va a limpiar

        Retorna:
            True si se elimino exitosamente, False si no existia o hubo error.
        """
        try:
            # Verificar que el usuario tenga una conversacion registrada
            if user_id not in self.user_conversations:
                return False

            # Eliminar la referencia a la conversacion del diccionario
            del self.user_conversations[user_id]
            logger.info(f"Sesion eliminada: {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error limpiando sesion {user_id}: {e}")
            return False

    def get_stats(self) -> dict:
        """
        Retorna estadisticas del estado actual del servidor.

        Util para monitorear cuantos usuarios estan conectados y
        cuantas conversaciones activas hay.

        Retorna:
            Diccionario con: nombre del agente, cantidad de conversaciones,
            cantidad de conexiones activas, y lista de user_ids.
        """
        return {
            "agent_name": self.agent_name,  # Nombre del agente configurado
            "active_conversations": len(self.user_conversations),  # Total de conversaciones en memoria
            "active_connections": len(self.active_connections),  # Total de WebSockets conectados ahora
            "users": list(self.user_conversations.keys())  # Lista de user_ids con sesion activa
        }


# ======================================================================================
# INSTANCIA GLOBAL DEL GESTOR DE CHAT
# ======================================================================================
# Se crea una sola vez al iniciar el servidor. Todos los endpoints comparten esta instancia.
# Esto permite que las conversaciones persistan mientras el servidor este corriendo.
# ======================================================================================

chat_manager = AgentChatManager()


# ======================================================================================
# ENDPOINTS HTTP (rutas REST normales)
# ======================================================================================

@app.get("/")
async def root():
    """
    Endpoint raiz: al visitar http://localhost:8000/ en el navegador,
    retorna informacion general de la API en formato JSON.
    Util para verificar que el servidor esta corriendo.
    """
    # Leer el entorno actual (development, production, etc.)
    environment = os.getenv("ENVIRONMENT", "development")

    # Retornar informacion de la API como JSON
    return {
        "service": "Axxon AI Agent API",
        "version": "2.0.0",
        "sdk": "Azure AI Foundry (conversations + responses)",
        "status": "online",
        "environment": environment,
        "endpoints": {
            "websocket": "/ws/chat",
            "health": "/health",
            "stats": "/api/stats",
            "docs": "/docs"
        },
        "active_connections": len(chat_manager.active_connections),
        "persistent_conversations": len(chat_manager.user_conversations)
    }


@app.get("/health")
async def health():
    """
    Health check: Azure Container Apps llama a este endpoint periodicamente
    para verificar que el servidor esta funcionando correctamente.
    Si retorna "healthy", Azure sabe que el container esta bien.
    Si retorna "unhealthy", Azure puede reiniciar el container.
    """
    try:
        # Obtener estadisticas del sistema
        stats = chat_manager.get_stats()
        return {
            "status": "healthy",  # Indicar que el servidor esta sano
            "timestamp": time.time(),  # Timestamp actual en segundos (epoch)
            "stats": stats  # Estadisticas del gestor de chat
        }
    except Exception as e:
        # Si algo falla al obtener stats, reportar como no saludable
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.get("/api/stats")
async def get_stats():
    """
    Endpoint de estadisticas: retorna informacion detallada del estado del servidor.
    Accesible desde http://localhost:8000/api/stats
    """
    return chat_manager.get_stats()


# ======================================================================================
# ENDPOINT WEBSOCKET (comunicacion en tiempo real)
# ======================================================================================

@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket):
    """
    Endpoint principal de WebSocket para el chat en tiempo real.

    PROTOCOLO DE COMUNICACION (como habla el frontend con el backend):

    PASO 1 - Inicializacion:
      El frontend envia:    {"type": "init", "user_id": "usuario_123"}
      El servidor responde: {"type": "session_ready", "conversation_id": "...", "is_new_session": true}

    PASO 2 - Enviar mensajes:
      El frontend envia:    {"type": "message", "message": "Hola agente"}
      El servidor responde: {"type": "processing", "message": "Procesando..."}  (inmediato)
      El servidor responde: {"type": "bot_message", "message": "Respuesta...", "status": "success"}

    PASO 3 - Limpiar sesion (opcional):
      El frontend envia:    {"type": "clear_session"}
      El servidor responde: {"type": "session_cleared", "message": "Historial eliminado"}

    PASO 4 - Ver estadisticas (opcional):
      El frontend envia:    {"type": "get_stats"}
      El servidor responde: {"type": "stats", "data": {...}}
    """

    # Variable para rastrear que usuario esta conectado en este WebSocket
    # Se usa para desconectarlo correctamente si hay un error
    current_user_id = None

    try:
        # Aceptar la conexion WebSocket entrante del frontend
        await websocket.accept()

        # ---------------------------------------------------------------
        # FASE 1: INICIALIZACION DE LA SESION
        # ---------------------------------------------------------------
        # El primer mensaje DEBE ser de tipo "init" con el user_id

        # Esperar a que el frontend envie el primer mensaje (debe ser "init")
        data = await websocket.receive_text()

        try:
            # Convertir el texto JSON recibido a un diccionario de Python
            init_data = json.loads(data)

            # Verificar que el primer mensaje sea de tipo "init"
            if init_data.get("type") != "init":
                # Si no es "init", enviar error y cerrar la conexion
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Debes enviar un mensaje 'init' primero con tu user_id"
                }))
                await websocket.close()
                return  # Salir de la funcion (termina la conexion)

            # Extraer el user_id del mensaje, usar "anonymous_user" si no viene
            user_id = init_data.get("user_id", "anonymous_user")

            # Guardar el user_id para usarlo en el manejo de desconexion
            current_user_id = user_id

            # Verificar si este usuario ya tenia una conversacion previa
            is_new_session = user_id not in chat_manager.user_conversations

            # Conectar al usuario y crear/recuperar su conversacion en AI Foundry
            conversation_id = await chat_manager.connect(websocket, user_id)

            # Si la conexion fue exitosa, enviar confirmacion al frontend
            if conversation_id:
                await websocket.send_text(json.dumps({
                    "type": "session_ready",  # Tipo de mensaje para que el frontend sepa que esta listo
                    "message": "Sesion recuperada. Tu historial esta disponible." if not is_new_session else "Nueva sesion creada.",
                    "conversation_id": conversation_id,  # ID de la conversacion en AI Foundry
                    "is_new_session": is_new_session,  # True si es nueva, False si se recupero
                    "status": "success"
                }))
            else:
                # Si fallo la conexion con AI Foundry, enviar error y cerrar
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "No se pudo inicializar la sesion",
                    "status": "error"
                }))
                await websocket.close()
                return  # Salir de la funcion

        except json.JSONDecodeError:
            # Si el mensaje no es JSON valido, enviar error y cerrar
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Formato JSON invalido"
            }))
            await websocket.close()
            return  # Salir de la funcion

        # ---------------------------------------------------------------
        # FASE 2: LOOP PRINCIPAL DE MENSAJES
        # ---------------------------------------------------------------
        # Despues de la inicializacion, el servidor queda escuchando mensajes
        # en un bucle infinito hasta que el usuario se desconecte.

        while True:
            # Esperar el siguiente mensaje del frontend
            data = await websocket.receive_text()

            try:
                # Convertir el texto JSON a diccionario
                message_data = json.loads(data)

                # Obtener el tipo de mensaje (message, clear_session, get_stats)
                message_type = message_data.get("type", "")

                # ----- TIPO: "message" (el usuario envia un mensaje al agente) -----
                if message_type == "message":

                    # Extraer el texto del mensaje del usuario
                    user_message = message_data.get("message", "")

                    # Validar que el mensaje no este vacio
                    if not user_message:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "Mensaje vacio"
                        }))
                        continue  # Volver al inicio del while para esperar otro mensaje

                    # Enviar indicador de "procesando" al frontend inmediatamente
                    # Esto permite mostrar un spinner o texto de "escribiendo..." en la UI
                    await websocket.send_text(json.dumps({
                        "type": "processing",
                        "message": "Procesando tu mensaje..."
                    }))

                    # Enviar el mensaje al agente de AI Foundry y esperar su respuesta
                    bot_response = await chat_manager.send_to_agent(current_user_id, user_message)

                    # Si el agente respondio exitosamente, enviar la respuesta al frontend
                    if bot_response:
                        await websocket.send_text(json.dumps({
                            "type": "bot_message",  # Tipo para que el frontend muestre como mensaje del bot
                            "message": bot_response,  # El texto de respuesta del agente
                            "status": "success"
                        }))
                    else:
                        # Si el agente no pudo responder, enviar error
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "No se pudo obtener respuesta del agente",
                            "status": "error"
                        }))

                # ----- TIPO: "clear_session" (el usuario quiere borrar su historial) -----
                elif message_type == "clear_session":

                    # Eliminar la conversacion actual del usuario de la memoria
                    success = chat_manager.cleanup_user_session(current_user_id)

                    if success:
                        # Crear una nueva conversacion limpia para el usuario
                        conversation_id = await chat_manager.connect(websocket, current_user_id)

                        # Confirmar al frontend que la sesion fue limpiada
                        await websocket.send_text(json.dumps({
                            "type": "session_cleared",
                            "message": "Tu historial de conversacion ha sido eliminado.",
                            "conversation_id": conversation_id  # ID de la nueva conversacion
                        }))
                    else:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "No se pudo limpiar la sesion"
                        }))

                # ----- TIPO: "get_stats" (el usuario pide estadisticas del servidor) -----
                elif message_type == "get_stats":

                    # Obtener las estadisticas actuales del servidor
                    stats = chat_manager.get_stats()

                    # Enviar las estadisticas al frontend
                    await websocket.send_text(json.dumps({
                        "type": "stats",
                        "data": stats  # Diccionario con agent_name, active_conversations, etc.
                    }))

                # ----- TIPO DESCONOCIDO (el frontend envio un tipo que no reconocemos) -----
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Tipo de mensaje desconocido: {message_type}"
                    }))

            except json.JSONDecodeError:
                # Si el mensaje no es JSON valido, informar al frontend
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Formato JSON invalido"
                }))

            except Exception as e:
                # Cualquier otro error inesperado, informar al frontend
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Error procesando mensaje: {str(e)}"
                }))

    except WebSocketDisconnect:
        # El frontend cerro la conexion (cerro la pestaña, navego a otra pagina, etc.)
        logger.info(f"Cliente desconectado: {current_user_id}")
        if current_user_id:
            # Limpiar la conexion WebSocket pero mantener la conversacion
            chat_manager.disconnect(current_user_id)

    except Exception as e:
        # Error inesperado en el WebSocket (error de red, etc.)
        logger.error(f"Error en WebSocket para {current_user_id}: {e}")
        if current_user_id:
            chat_manager.disconnect(current_user_id)


# ======================================================================================
# PUNTO DE ENTRADA: se ejecuta cuando corres "python agent_websocket.py"
# ======================================================================================

if __name__ == "__main__":
    # Leer configuracion del servidor desde variables de entorno
    host = os.getenv("HOST", "0.0.0.0")  # Host donde escuchar (0.0.0.0 = todas las interfaces)
    port = int(os.getenv("PORT", "8000"))  # Puerto donde escuchar (default: 8000)
    environment = os.getenv("ENVIRONMENT", "development")  # Entorno actual
    reload = environment == "development"  # Auto-reload solo en desarrollo (reinicia al guardar cambios)

    # Imprimir informacion de inicio en los logs
    logger.info("\n" + "="*60)
    logger.info("Axxon AI Agent - WebSocket API v2.0")
    logger.info("="*60)
    logger.info(f"SDK: Azure AI Foundry (conversations + responses)")
    logger.info(f"Agent: {chat_manager.agent_name}")
    logger.info(f"Environment: {environment}")
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"WebSocket: ws://{host}:{port}/ws/chat")
    logger.info(f"Health: http://{host}:{port}/health")
    logger.info(f"Stats: http://{host}:{port}/api/stats")
    logger.info(f"Docs: http://{host}:{port}/docs")
    logger.info("="*60 + "\n")

    # Iniciar el servidor uvicorn
    uvicorn.run(
        "agent_text_web_socket:app",  # Modulo:variable donde esta la app FastAPI
        host=host,  # Host donde escuchar
        port=port,  # Puerto donde escuchar
        reload=reload,  # Auto-reload cuando cambias el codigo (solo en development)
        log_level="info"  # Nivel de logs de uvicorn
    )
