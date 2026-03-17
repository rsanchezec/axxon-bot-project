# Axxon AI Assistant

Asistente de inteligencia artificial para Axxon con soporte de chat por texto y conversacion por voz en tiempo real. Utiliza Azure AI Foundry como motor de IA y Azure Voice Live para el modo de voz.

## Descripcion General

Axxon AI Assistant es una aplicacion web que permite a los usuarios interactuar con un agente de IA de dos formas:

- **Modo Texto**: El usuario escribe mensajes y recibe respuestas del agente en formato texto a traves de WebSocket.
- **Modo Voz**: El usuario habla por microfono y recibe respuestas habladas del agente en tiempo real, con transcripciones visibles en el chat.

La aplicacion soporta multiples usuarios simultaneos, cada uno con su propia sesion independiente.

## Arquitectura

```
                          ┌─────────────────────────┐
                          │     Azure AI Foundry     │
                          │  (Agente + AI Search)    │
                          └────────┬────────┬────────┘
                                   │        │
                          SDK      │        │  SDK
                     (conversations│        │(voice live)
                      + responses) │        │
                                   │        │
┌──────────────┐    WebSocket    ┌─┴────┐ ┌─┴──────┐
│   Frontend   │◄──────────────►│ :8000 │ │ :8001  │
│  React.js    │    (texto)     │ Texto │ │  Voz   │
│  (Vite)      │◄──────────────►│Server │ │ Server │
│  :5173       │    (voz+audio) └───────┘ └────────┘
└──────────────┘
```

### Flujo de Texto

1. El frontend abre una conexion WebSocket al servidor de texto (puerto 8000)
2. Envia un mensaje `init` con el `user_id` para iniciar la sesion
3. El servidor crea una conversacion en Azure AI Foundry
4. El usuario envia mensajes de texto, el servidor los procesa con el agente y devuelve las respuestas

**Protocolo WebSocket (texto):**
```
Cliente → Servidor:  { "type": "init", "user_id": "uuid" }
Servidor → Cliente:  { "type": "session_ready", "conversation_id": "..." }
Cliente → Servidor:  { "type": "message", "message": "Hola" }
Servidor → Cliente:  { "type": "bot_message", "text": "Respuesta del agente" }
```

### Flujo de Voz

1. El frontend abre una conexion WebSocket al servidor de voz (puerto 8001)
2. Envia un mensaje `init_voice` con el `user_id`
3. El servidor establece una sesion con Azure Voice Live SDK
4. El audio del microfono se captura como PCM 16-bit mono 24kHz y se envia en binario
5. El servidor responde con audio binario (respuesta hablada) y eventos JSON (transcripciones)

**Protocolo WebSocket (voz):**
```
Cliente → Servidor:  { "type": "init_voice", "user_id": "uuid" }
Servidor → Cliente:  { "type": "voice_session_ready" }
Cliente → Servidor:  [ArrayBuffer - PCM audio del microfono]
Servidor → Cliente:  [ArrayBuffer - PCM audio de respuesta]
Servidor → Cliente:  { "type": "user_transcript", "text": "..." }
Servidor → Cliente:  { "type": "agent_text", "text": "..." }
Servidor → Cliente:  { "type": "agent_transcript", "text": "..." }
Servidor → Cliente:  { "type": "input_audio_buffer.speech_started" }
Cliente → Servidor:  { "type": "response.cancel" }  (interrumpir respuesta)
Cliente → Servidor:  { "type": "stop_voice" }  (finalizar sesion)
```

**Especificaciones de Audio:**
- Formato: PCM 16-bit signed, little-endian
- Canales: Mono (1 canal)
- Sample rate: 24,000 Hz
- Tamano de buffer: 4096 frames

## Estructura del Proyecto

```
axxon-bot-project/
├── README.md                              # Este archivo
├── CLAUDE.md                              # Documentacion tecnica para desarrollo con IA
│
├── frontend/                              # Aplicacion React.js (Vite, puerto 5173)
│   ├── index.html                         # HTML principal
│   ├── package.json                       # Dependencias npm
│   ├── vite.config.js                     # Configuracion de Vite
│   ├── public/                            # Assets estaticos
│   │   └── axxon-icon.svg                 # Icono de la aplicacion
│   └── src/
│       ├── main.jsx                       # Entry point de React
│       ├── App.jsx                        # Componente principal (orquestador)
│       ├── App.css                        # Estilos globales
│       ├── index.css                      # Reset CSS y estilos base
│       ├── utils/
│       │   └── userId.js                  # Genera user_id unico por tab
│       ├── hooks/
│       │   ├── useTextWebSocket.js        # Hook para WebSocket de texto
│       │   ├── useVoiceWebSocket.js       # Hook para WebSocket de voz
│       │   └── useAudioPlayback.js        # Hook para reproduccion de audio PCM
│       └── components/
│           ├── Header.jsx / Header.css    # Barra superior (titulo, estado)
│           ├── ChatWindow.jsx / .css      # Area de mensajes con scroll
│           ├── MessageBubble.jsx / .css   # Burbuja individual de mensaje
│           └── InputBar.jsx / InputBar.css# Input de texto + microfono + enviar
│
├── backend/                               # Servidores Python (FastAPI + uvicorn)
│   ├── .env                               # Variables de entorno (credenciales Azure)
│   ├── .venv/                             # Virtual environment (Python 3.14, uv)
│   ├── requirements.txt                   # Dependencias pip
│   ├── text/
│   │   └── agent_text_web_socket.py       # Servidor WebSocket texto (puerto 8000)
│   ├── voice/
│   │   ├── voice_live_manager.py          # Clase VoiceLiveSession (conexion Azure Voice Live)
│   │   └── voice_live_server.py           # Servidor WebSocket voz (puerto 8001)
│   ├── test/
│   │   ├── test_agent_text_web_socket.html  # Cliente de prueba HTML (texto)
│   │   └── test_agent_voice_web_socket.html # Cliente de prueba HTML (voz)
│   └── help/
│       ├── agent_voice_live.py            # Cliente standalone voz (mic + altavoces, referencia)
│       └── use_existing_agent.py          # Script CLI para chat (standalone)
```

## Stack Tecnologico

### Backend
| Tecnologia | Uso |
|---|---|
| Python 3.14 | Runtime del backend |
| uv | Gestor de paquetes y entorno virtual |
| FastAPI | Framework web para endpoints y WebSockets |
| uvicorn | Servidor ASGI |
| azure-ai-projects 2.0.0b3 | SDK de Azure AI Foundry (agentes, conversaciones) |
| azure-ai-voicelive >= 1.2.0b4 | SDK de Azure Voice Live (voz en tiempo real) |
| azure-identity | Autenticacion con Azure (DefaultAzureCredential) |
| openai 2.15.0 | Cliente OpenAI para API de conversaciones |
| numpy + sounddevice | Solo para testing local con microfono/altavoces |

### Frontend
| Tecnologia | Uso |
|---|---|
| React 19 | Framework de UI |
| Vite 8 | Build tool y dev server |
| Web Audio API | Captura de microfono y reproduccion de audio |
| WebSocket API | Comunicacion en tiempo real con los backends |
| CSS puro | Estilos (dark theme, sin librerias externas) |

## Requisitos Previos

### Servicios de Azure
- **Azure AI Foundry**: Proyecto con un agente configurado
- **Azure AI Search**: Indice RAG multi-modal (para busqueda de conocimiento)
- **Azure Voice Live**: Endpoint de servicio de voz en tiempo real
- **Autenticacion**: `az login` configurado o managed identity / service principal

### Software Local
- **Python 3.14+** con [uv](https://docs.astral.sh/uv/) instalado
- **Node.js 18+** con npm
- **Azure CLI** (`az login` ejecutado para autenticacion)

## Configuracion

### 1. Variables de Entorno

Crear un archivo `backend/.env` con las siguientes variables:

```env
# Azure AI Foundry - Modo Texto
FOUNDRY_PROJECT_ENDPOINT=https://tu-proyecto.services.ai.azure.com
MODEL_DEPLOYMENT_NAME=gpt-5.2-chat
AI_SEARCH_CONNECTION_NAME=nombre-conexion-search
AI_SEARCH_INDEX_NAME=nombre-indice-rag

# Azure Voice Live - Modo Voz
VOICELIVE_ENDPOINT=wss://tu-endpoint-voice.azure.com

# Agente
AZURE_AGENT_NAME=axxon-agent
PROJECT_NAME=nombre-proyecto-foundry
```

> **Nota:** No se utilizan API keys. La autenticacion se realiza a traves de `DefaultAzureCredential` (az login, managed identity o service principal).

### 2. Instalacion del Backend

```bash
cd backend
uv pip install -r .\requirements.txt
```

### 3. Instalacion del Frontend

```bash
cd frontend
npm install
```

## Ejecucion

Se necesitan tres terminales para ejecutar la aplicacion completa:

### Terminal 1 - Servidor de Texto (puerto 8000)
```bash
cd backend
uv run text\agent_text_web_socket.py
```

### Terminal 2 - Servidor de Voz (puerto 8001)
```bash
cd backend
uv run voice\voice_live_server.py
```

### Terminal 3 - Frontend (puerto 5173)
```bash
cd frontend
npm run dev
```

Abrir http://localhost:5173 en el navegador.

## Uso

### Chat por Texto
1. Abrir la aplicacion en el navegador
2. Escribir un mensaje en el campo de texto
3. Presionar Enter o el boton de enviar (flecha)
4. La respuesta del agente aparecera en el chat

### Conversacion por Voz
1. Hacer clic en el boton del microfono (se pondra naranja mientras conecta)
2. Cuando se ponga rojo, el modo voz esta activo
3. Hablar normalmente - el agente escuchara, transcribira y respondera con voz
4. Para interrumpir al agente, simplemente empezar a hablar
5. Hacer clic en el microfono de nuevo para desactivar el modo voz

### Multiples Usuarios
- Cada tab del navegador genera un `user_id` unico automaticamente
- Cada tab mantiene su propia sesion independiente
- Se pueden abrir multiples tabs para simular concurrencia

## Configuracion de Voz

La sesion de voz se configura con las siguientes caracteristicas:

- **VAD (Voice Activity Detection)**: `azure_semantic_vad` con umbral de 0.7 para filtrar ruido ambiental
- **Reduccion de ruido**: `azure_deep_noise_suppression`
- **Cancelacion de eco**: `server_echo_cancellation` (evita que el agente se escuche a si mismo)
- **Voz del agente**: `es-AR-ElenaNeural` (espanol argentino)
- **Deteccion de fin de frase**: Modelo semantico con umbral de 0.5 y timeout de 3 segundos

## Descripcion de los Archivos Principales

### Backend

| Archivo | Carpeta | Descripcion |
|---|---|---|
| `agent_text_web_socket.py` | `text/` | Servidor FastAPI que expone el endpoint WebSocket `/ws/chat` en el puerto 8000. Clase `AgentChatManager` que gestiona sesiones de texto por usuario, creando conversaciones en Azure AI Foundry y procesando mensajes con el agente. |
| `voice_live_manager.py` | `voice/` | Clase `VoiceLiveSession` que encapsula toda la logica de conexion con Azure Voice Live SDK. Fully async, maneja la configuracion de la sesion, envio/recepcion de audio y eventos. |
| `voice_live_server.py` | `voice/` | Servidor FastAPI que expone el endpoint WebSocket `/ws/voice` en el puerto 8001. Clase `VoiceLiveConnectionManager` que gestiona sesiones de voz por usuario, actuando como puente entre el navegador y Azure Voice Live. |
| `agent_voice_live.py` | `help/` | Cliente standalone de voz para testing local. Usa microfono y altavoces directamente (sin navegador). |
| `use_existing_agent.py` | `help/` | Script CLI para chatear con el agente desde la terminal (sin servidor web). |

### Frontend

| Archivo | Descripcion |
|---|---|
| `App.jsx` | Componente raiz que orquesta toda la aplicacion. Gestiona el estado de mensajes, conecta los hooks de texto y voz, y renderiza los componentes. |
| `useTextWebSocket.js` | Hook personalizado para la conexion WebSocket de texto. Implementa reconexion automatica con backoff exponencial (3s a 15s). |
| `useVoiceWebSocket.js` | Hook personalizado para la conexion WebSocket de voz. Maneja captura de audio del microfono (ScriptProcessor), envio de PCM binario, recepcion de audio y eventos, e interrupciones. |
| `useAudioPlayback.js` | Hook para reproducir audio PCM del agente usando Web Audio API. Implementa scheduling secuencial de AudioBufferSource y permite detener la reproduccion en caso de interrupcion del usuario. |
| `Header.jsx` | Barra superior con el titulo "Axxon AI Assistant", ID de conversacion y estado de conexion. |
| `ChatWindow.jsx` | Area de mensajes con scroll automatico al ultimo mensaje. |
| `MessageBubble.jsx` | Componente de burbuja individual. Soporta tipos: usuario, bot, sistema, transcripcion y error. |
| `InputBar.jsx` | Barra inferior con campo de texto, boton de microfono (con estados: inactivo, conectando, activo) y boton de enviar. |

## Herramientas de Testing

El proyecto incluye clientes HTML standalone en la carpeta `backend/test/` para probar los backends sin necesidad del frontend React:

- **`test/test_agent_text_web_socket.html`**: Abrir directamente en el navegador para probar el modo texto
- **`test/test_agent_voice_web_socket.html`**: Abrir directamente en el navegador para probar el modo voz

## Build de Produccion

Para generar el build optimizado del frontend:

```bash
cd frontend
npm run build
```

Los archivos de produccion se generan en `frontend/dist/`.
