# Axxon Bot Project

## Descripcion del Proyecto

Chatbot de IA para Axxon que usa Azure AI Foundry como backend. Soporta dos modos de comunicacion:
- **Modo Texto**: Chat por WebSocket con un agente de AI Foundry (conversations + responses API)
- **Modo Voz con Avatar**: Conversacion en tiempo real usando Azure Voice Live API con avatar visual (Azure Photo Avatar VASA-1) en popup flotante

El frontend es una app React.js (Vite) con dark theme que integra ambos modos en una sola interfaz. El avatar aparece en la esquina inferior derecha durante el modo voz.

## Estructura del Proyecto

```
axxon-bot-project/
├── CLAUDE.md                              # Este archivo
├── README.md                              # Documentacion del proyecto
├── .gitignore                             # Archivos excluidos de git
├── frontend/                              # App React.js (Vite, puerto 5173)
│   ├── src/
│   │   ├── App.jsx                        # Orquestador principal
│   │   ├── utils/userId.js                # Genera user_id unico por tab (sessionStorage)
│   │   ├── hooks/
│   │   │   ├── useTextWebSocket.js        # Hook WebSocket texto (puerto 8000)
│   │   │   ├── useVoiceWebSocket.js       # Hook WebSocket voz (puerto 8001) + signaling WebRTC
│   │   │   ├── useAvatarWebRTC.js         # Hook WebRTC para avatar (RTCPeerConnection, SDP)
│   │   │   └── useAudioPlayback.js        # Hook reproduccion audio PCM
│   │   └── components/
│   │       ├── Header.jsx                 # Titulo, thread ID, estado conexion
│   │       ├── ChatWindow.jsx             # Area de mensajes con scroll
│   │       ├── MessageBubble.jsx          # Burbuja individual
│   │       ├── InputBar.jsx               # Input texto + boton mic + boton enviar
│   │       └── AvatarStage.jsx            # Popup flotante con video del avatar (esquina inferior derecha)
│   └── package.json
├── backend/
│   ├── .env                               # Variables de entorno (credenciales Azure)
│   ├── .venv/                             # Virtual environment (Python 3.14, gestionado con uv)
│   ├── requirements.txt                   # Dependencias pip
│   ├── text/
│   │   └── agent_text_web_socket.py       # Servidor FastAPI WebSocket texto (puerto 8000)
│   ├── voice/
│   │   ├── voice_live_manager.py          # Clase VoiceLiveSession: conexion async Azure Voice Live
│   │   └── voice_live_server.py           # Servidor FastAPI WebSocket voz (puerto 8001)
│   ├── test/
│   │   ├── test_agent_text_web_socket.html  # Cliente de prueba HTML (texto)
│   │   └── test_agent_voice_web_socket.html # Cliente de prueba HTML (voz)
│   └── help/
│       ├── agent_voice_live.py            # Cliente standalone voz (mic + altavoces, referencia)
│       └── use_existing_agent.py          # Script CLI para chatear con el agente (standalone)
```

## Stack Tecnologico

- **Runtime**: Python 3.14 (gestionado con `uv`)
- **Framework Web**: FastAPI + uvicorn
- **SDK AI**: Azure AI Foundry (`azure-ai-projects==2.0.0b3`)
- **SDK Voz**: `azure-ai-voicelive[aiohttp]>=1.2.0b4` (SDK nuevo, fully async)
- **Auth**: `azure-identity` (DefaultAzureCredential)
- **Audio**: numpy + sounddevice (solo para testing local con microfono/altavoces)
- **Package Manager**: uv (backend), npm (frontend)
- **Frontend**: React.js + Vite (puerto 5173, dark theme, sin librerias UI externas)

## Variables de Entorno (.env)

```
FOUNDRY_PROJECT_ENDPOINT=   # Endpoint del proyecto AI Foundry (para modo texto)
MODEL_DEPLOYMENT_NAME=      # Modelo desplegado (gpt-5.2-chat)
AI_SEARCH_CONNECTION_NAME=  # Nombre de la conexion a AI Search
AI_SEARCH_INDEX_NAME=       # Indice RAG multi-modal
VOICELIVE_ENDPOINT=         # Endpoint del servicio Voice Live (para modo voz)
AVATAR_CHARACTER=           # Personaje del avatar (Camila, Lisa, etc.)
AVATAR_MODEL=               # Modelo de avatar (vasa-1)
AZURE_AGENT_NAME=           # Nombre del agente en AI Foundry (default: "axxon-agent")
PROJECT_NAME=               # Nombre del proyecto en AI Foundry
```

No se usan API keys. La autenticacion es via `DefaultAzureCredential` (az login, managed identity, service principal).

## Comandos para Ejecutar

### Frontend (desde `frontend/`):
```bash
npm install          # Instalar dependencias
npm run dev          # Dev server en http://localhost:5173
npm run build        # Build de produccion
```

### Backend (desde `backend/`):

```bash
# Modo texto - servidor WebSocket en puerto 8000
uv run text\agent_text_web_socket.py

# Modo voz - servidor WebSocket en puerto 8001
uv run voice\voice_live_server.py

# Modo voz - cliente standalone con microfono y altavoces (testing/referencia)
uv run help\agent_voice_live.py

# Chat de texto por CLI (sin servidor)
uv run help\use_existing_agent.py

# Instalar dependencias
uv pip install -r requirements.txt
```

## Arquitectura Modo Texto

```
Frontend HTML  ──WebSocket──>  agent_text_web_socket.py  ──SDK──>  Azure AI Foundry
(puerto 8000, /ws/chat)          AgentChatManager                   (conversations + responses)
```

- Usa `AIProjectClient` + `openai_client.conversations.create()` + `openai_client.responses.create()`
- Cada usuario tiene su propia conversacion persistente (reconexion mantiene historial)
- Protocolo: `init` -> `session_ready` -> `message` -> `bot_message`

## Arquitectura Modo Voz con Avatar

```
Frontend React  ──WebSocket──>  voice_live_server.py  ──SDK──>  Azure Voice Live
(puerto 8001,      (signaling       VoiceLiveSession              + Avatar (VASA-1)
 /ws/voice)         WebRTC)         (voice_live_manager.py)
      │
      └──WebRTC──> Azure Media Relay ──> Avatar video/audio stream
         (ICE)
```

- Usa SDK `azure-ai-voicelive` con `connect()` + `RequestSession` con `Modality.AVATAR` (fully async)
- Audio: PCM 16-bit, mono, 24kHz (sin avatar) | WebRTC audio/video (con avatar)
- Protocolo:
  - `init_voice` (avatar: true) -> `voice_session_ready`
  - `avatar_ice_servers` -> `avatar_offer` (SDP base64) -> `avatar_answer` (SDP base64)
  - Audio binario bidireccional (o WebRTC cuando avatar conecta)
- Eventos del servidor: `user_transcript`, `agent_text`, `agent_transcript`, `input_audio_buffer.speech_started`
- El frontend puede enviar `response.cancel` para interrumpir al agente
- **Avatar**: Popup flotante en esquina inferior derecha con sincronización labial vía WebRTC

## Configuracion de Voz y Avatar

La sesion de Voice Live se configura con:
- VAD: `azure_semantic_vad` (deteccion de voz semantica)
- Reduccion de ruido: `azure_deep_noise_suppression`
- Cancelacion de eco: `server_echo_cancellation`
- Voz del agente: `es-AR-ElenaNeural` (espanol argentino)
- Avatar: Azure Photo Avatar con modelo VASA-1, personaje Camila
  - Video/audio vía WebRTC para latencia mínima
  - Sincronización labial (lip-sync) en tiempo real
  - Popup flotante en esquina inferior derecha (320x400px)
  - Fallback automático a audio si WebRTC falla

## Convenciones

- Todo el codigo esta comentado en espanol con alto nivel de detalle
- Los archivos de servidor siguen el patron: clase Manager + instancia global + endpoints FastAPI
- Los archivos de test HTML son clientes standalone que se abren directo en el navegador
- Logging a archivos en `logs/` para sesiones de voz, logging a consola para servidores
- Frontend React con Vite en puerto 5173, dark theme, sin librerias UI externas
- Concurrencia de usuarios: cada tab genera userId unico via sessionStorage + crypto.randomUUID()
