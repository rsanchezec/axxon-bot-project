import { useRef, useState, useCallback, useEffect } from 'react';

// En desarrollo usa localhost:8000, en produccion usa la variable VITE_TEXT_WS_URL
const WS_URL = import.meta.env.VITE_TEXT_WS_URL || 'ws://localhost:8000/ws/chat';
const RECONNECT_DELAY = 3000; // 3 segundos entre reintentos
const MAX_RECONNECT_DELAY = 15000; // maximo 15 segundos

/**
 * Hook para manejar la conexion WebSocket de texto con agent_text_web_socket.py (puerto 8000).
 * Incluye reconexion automatica con backoff.
 *
 * Protocolo:
 *   init -> session_ready -> message -> processing -> bot_message
 */
export function useTextWebSocket({ onMessage }) {
  const wsRef = useRef(null);
  const [isConnected, setIsConnected] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const userIdRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectDelayRef = useRef(RECONNECT_DELAY);
  const shouldReconnectRef = useRef(true);

  const connect = useCallback((userId) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    // Limpiar conexion anterior si existe
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    userIdRef.current = userId;
    shouldReconnectRef.current = true;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectDelayRef.current = RECONNECT_DELAY; // Reset backoff
      ws.send(JSON.stringify({ type: 'init', user_id: userId }));
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'session_ready':
          setIsConnected(true);
          setConversationId(data.conversation_id);
          onMessage({
            type: 'system',
            text: data.is_new_session
              ? 'Nueva sesion creada. Puedes empezar a chatear.'
              : 'Sesion recuperada. Tu historial esta disponible.',
          });
          break;

        case 'processing':
          setIsProcessing(true);
          break;

        case 'bot_message':
          setIsProcessing(false);
          onMessage({ type: 'bot', text: data.message });
          break;

        case 'session_cleared':
          setConversationId(data.conversation_id);
          onMessage({ type: 'system', text: 'Historial de conversacion eliminado.' });
          break;

        case 'error':
          setIsProcessing(false);
          onMessage({ type: 'error', text: data.message });
          break;

        default:
          break;
      }
    };

    ws.onerror = () => {
      // No mostrar error aqui, onclose se encarga del reconnect
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsProcessing(false);
      wsRef.current = null;

      // Reconectar automaticamente si no fue un disconnect manual
      if (shouldReconnectRef.current && userIdRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          connect(userIdRef.current);
          // Backoff: incrementar delay hasta el maximo
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * 1.5,
            MAX_RECONNECT_DELAY
          );
        }, reconnectDelayRef.current);
      }
    };
  }, [onMessage]);

  const sendMessage = useCallback((text) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'message', message: text }));
  }, []);

  const clearSession = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ type: 'clear_session' }));
  }, []);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // Cleanup al desmontar
  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    connect,
    sendMessage,
    clearSession,
    disconnect,
    isConnected,
    conversationId,
    isProcessing,
  };
}
