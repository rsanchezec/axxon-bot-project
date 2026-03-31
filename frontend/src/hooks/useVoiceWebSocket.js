import { useRef, useState, useCallback, useEffect } from 'react';
import { useAudioPlayback } from './useAudioPlayback';

// En desarrollo usa localhost:8001, en produccion usa la variable VITE_VOICE_WS_URL
const WS_URL = import.meta.env.VITE_VOICE_WS_URL || 'ws://localhost:8001/ws/voice';
const SAMPLE_RATE = 24000;

/**
 * Hook para manejar la conexion WebSocket de voz con voice_live_server.py (puerto 8001).
 *
 * Protocolo:
 *   init_voice -> voice_session_ready -> audio binario bidireccional
 *   Eventos JSON: user_transcript, agent_text, agent_transcript, speech_started
 *   Avatar: avatar_ice_servers -> avatar_offer -> avatar_answer (WebRTC signaling)
 *
 * Audio: PCM 16-bit, mono, 24kHz (via WebSocket sin avatar, via WebRTC con avatar)
 *
 * Estados: idle -> connecting -> active
 *
 * @param {Object} options
 * @param {Function} options.onMessage - Callback para agregar mensajes al chat
 * @param {Object} [options.avatarHooks] - Hooks de useAvatarWebRTC
 */
export function useVoiceWebSocket({ onMessage, avatarHooks }) {
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const audioStreamRef = useRef(null);
  const processorRef = useRef(null);
  const sourceNodeRef = useRef(null);
  const avatarActiveRef = useRef(false);
  const avatarHooksRef = useRef(avatarHooks);
  avatarHooksRef.current = avatarHooks;
  const [isVoiceActive, setIsVoiceActive] = useState(false);
  const [isVoiceConnecting, setIsVoiceConnecting] = useState(false);
  const [isAvatarActive, setIsAvatarActive] = useState(false);
  const { playChunk, reset: resetPlayback, cleanup: cleanupPlayback, getContext } = useAudioPlayback();

  const stopCapture = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (sourceNodeRef.current) {
      sourceNodeRef.current.disconnect();
      sourceNodeRef.current = null;
    }
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach((track) => track.stop());
      audioStreamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
  }, []);

  const startCapture = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    audioStreamRef.current = stream;

    const ctx = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: SAMPLE_RATE,
    });
    audioContextRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);
    sourceNodeRef.current = source;

    const processor = ctx.createScriptProcessor(4096, 1, 1);
    processorRef.current = processor;

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

      const inputData = e.inputBuffer.getChannelData(0);
      const pcmData = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      wsRef.current.send(pcmData.buffer);
    };

    source.connect(processor);
    processor.connect(ctx.destination);
  }, []);

  const startVoice = useCallback(async (userId) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;
    if (isVoiceConnecting) return;

    // Feedback visual inmediato
    setIsVoiceConnecting(true);
    onMessage({ type: 'system', text: 'Conectando modo voz...' });

    // Pedir acceso al microfono EN PARALELO con la conexion WebSocket
    // Asi el permiso del navegador se resuelve mientras Azure conecta
    const micPromise = startCapture().catch((err) => {
      onMessage({ type: 'error', text: 'Error al acceder al microfono: ' + err.message });
      return null;
    });

    // Inicializar playback context
    getContext();

    const ws = new WebSocket(WS_URL);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = () => {
      const enableAvatar = !!avatarHooksRef.current;
      ws.send(JSON.stringify({
        type: 'init_voice',
        user_id: userId,
        avatar: enableAvatar,
      }));
    };

    ws.onmessage = async (event) => {
      // Discriminar binario (audio) vs texto (JSON)
      if (event.data instanceof ArrayBuffer) {
        // Cuando avatar esta activo y WebRTC CONECTADO, el audio llega por WebRTC
        // No reproducir PCM duplicado
        if (!avatarActiveRef.current) {
          playChunk(event.data);
        }
        return;
      }

      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'voice_session_ready':
          // Esperar a que el microfono este listo (ya deberia estarlo)
          await micPromise;
          setIsVoiceConnecting(false);
          setIsVoiceActive(true);
          onMessage({ type: 'system', text: 'Modo voz activado. Puedes hablar.' });
          break;

        case 'user_transcript':
          onMessage({ type: 'user', text: data.text, isVoice: true });
          break;

        case 'agent_text':
          onMessage({ type: 'bot', text: data.text });
          break;

        case 'agent_transcript':
          onMessage({ type: 'transcript', text: data.text });
          break;

        case 'input_audio_buffer.speech_started':
          // El usuario empezo a hablar - interrumpir todo:
          // 1. Detener audio que esta sonando en el frontend (solo si no hay avatar)
          if (!avatarActiveRef.current) {
            resetPlayback();
          }
          // 2. Cancelar la respuesta del agente en el servidor
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'response.cancel' }));
          }
          break;

        case 'voice_session_stopped':
          onMessage({ type: 'system', text: 'Modo voz desactivado.' });
          break;

        // --- Avatar WebRTC signaling ---
        case 'avatar_ice_servers':
          if (avatarHooksRef.current) {
            setIsAvatarActive(true);

            // Registrar callbacks ANTES de inicializar
            avatarHooksRef.current.setCallbacks(
              // onConnected: WebRTC conectado -> suprimir audio WebSocket
              () => {
                console.log('[VoiceWS] Avatar WebRTC connected - suppressing WebSocket audio');
                avatarActiveRef.current = true;
              },
              // onError: WebRTC fallo -> fallback a audio WebSocket
              (errorMsg) => {
                console.warn('[VoiceWS] Avatar WebRTC failed:', errorMsg);
                avatarActiveRef.current = false;
                setIsAvatarActive(false);
                // Notificar al backend que vuelva a enviar audio por WebSocket
                if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                  wsRef.current.send(JSON.stringify({ type: 'avatar_failed' }));
                }
                onMessage({ type: 'system', text: 'Avatar no disponible, continuando con audio.' });
              }
            );

            const sdpOffer = await avatarHooksRef.current.initializeWithIceServers(data.ice_servers);
            if (sdpOffer && wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({
                type: 'avatar_offer',
                sdp: sdpOffer,
              }));
            }
          }
          break;

        case 'avatar_answer':
          if (avatarHooksRef.current) {
            await avatarHooksRef.current.handleAnswer(data.sdp);
          }
          break;

        case 'avatar_unavailable':
          avatarActiveRef.current = false;
          setIsAvatarActive(false);
          onMessage({ type: 'system', text: data.message || 'Avatar no disponible.' });
          break;

        case 'error':
          onMessage({ type: 'error', text: data.message });
          break;

        default:
          break;
      }
    };

    ws.onerror = () => {
      setIsVoiceConnecting(false);
      onMessage({ type: 'error', text: 'Error de conexion con el servidor de voz.' });
    };

    ws.onclose = () => {
      setIsVoiceConnecting(false);
      setIsVoiceActive(false);
      stopCapture();
    };
  }, [onMessage, startCapture, playChunk, resetPlayback, getContext, isVoiceConnecting]);

  const stopVoice = useCallback(() => {
    stopCapture();

    // Limpiar avatar WebRTC
    if (avatarHooksRef.current) {
      avatarHooksRef.current.cleanup();
    }
    avatarActiveRef.current = false;
    setIsAvatarActive(false);

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop_voice' }));
      setTimeout(() => {
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }
      }, 500);
    }

    cleanupPlayback();
    setIsVoiceConnecting(false);
    setIsVoiceActive(false);
  }, [stopCapture, cleanupPlayback]);

  const cancelResponse = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'response.cancel' }));
    }
    if (!avatarActiveRef.current) {
      resetPlayback();
    }
  }, [resetPlayback]);

  // Cleanup al desmontar
  useEffect(() => {
    return () => {
      stopCapture();
      if (avatarHooksRef.current) {
        avatarHooksRef.current.cleanup();
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
      cleanupPlayback();
    };
  }, [stopCapture, cleanupPlayback]);

  return {
    startVoice,
    stopVoice,
    cancelResponse,
    isVoiceActive,
    isVoiceConnecting,
    isAvatarActive,
  };
}
