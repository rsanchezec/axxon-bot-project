import { useState, useCallback, useEffect, useMemo } from 'react';
import { Header } from './components/Header';
import { ChatWindow } from './components/ChatWindow';
import { InputBar } from './components/InputBar';
import { AvatarStage } from './components/AvatarStage';
import { useTextWebSocket } from './hooks/useTextWebSocket';
import { useVoiceWebSocket } from './hooks/useVoiceWebSocket';
import { useAvatarWebRTC } from './hooks/useAvatarWebRTC';
import { getUserId } from './utils/userId';
import './App.css';

function App() {
  const [messages, setMessages] = useState([]);
  const userId = useMemo(() => getUserId(), []);

  // Callback comun para agregar mensajes al chat
  const addMessage = useCallback((msg) => {
    setMessages((prev) => [...prev, { ...msg, timestamp: Date.now() }]);
  }, []);

  // Hook de texto
  const {
    connect: connectText,
    sendMessage,
    clearSession,
    isConnected,
    conversationId,
    isProcessing,
  } = useTextWebSocket({ onMessage: addMessage });

  // Hook de avatar WebRTC
  const {
    videoRef: avatarVideoRef,
    audioRef: avatarAudioRef,
    avatarState,
    setCallbacks: setAvatarCallbacks,
    initializeWithIceServers,
    handleAnswer,
    cleanup: cleanupAvatar,
  } = useAvatarWebRTC();

  // Memoizar avatarHooks para evitar re-renders infinitos
  const avatarHooks = useMemo(
    () => ({ initializeWithIceServers, handleAnswer, setCallbacks: setAvatarCallbacks, cleanup: cleanupAvatar }),
    [initializeWithIceServers, handleAnswer, setAvatarCallbacks, cleanupAvatar]
  );

  // Hook de voz (con avatar hooks integrados)
  const {
    startVoice,
    stopVoice,
    isVoiceActive,
    isVoiceConnecting,
    isAvatarActive,
  } = useVoiceWebSocket({
    onMessage: addMessage,
    avatarHooks,
  });

  // Conectar al montar
  useEffect(() => {
    connectText(userId);
  }, [connectText, userId]);

  // Enviar mensaje de texto
  const handleSend = useCallback((text) => {
    addMessage({ type: 'user', text });
    sendMessage(text);
  }, [addMessage, sendMessage]);

  // Toggle de microfono
  const handleMicToggle = useCallback(() => {
    if (isVoiceActive) {
      stopVoice();
    } else {
      startVoice(userId);
    }
  }, [isVoiceActive, startVoice, stopVoice, userId]);

  return (
    <div className="app">
      <Header
        conversationId={conversationId}
        isConnected={isConnected}
        isVoiceActive={isVoiceActive}
      />
      <ChatWindow
        messages={messages}
        isProcessing={isProcessing}
      />
      <InputBar
        onSend={handleSend}
        onMicToggle={handleMicToggle}
        isVoiceActive={isVoiceActive}
        isVoiceConnecting={isVoiceConnecting}
        isConnected={isConnected}
        isProcessing={isProcessing}
      />
      <AvatarStage
        videoRef={avatarVideoRef}
        audioRef={avatarAudioRef}
        avatarState={avatarState}
        isVisible={isVoiceActive && isAvatarActive}
      />
    </div>
  );
}

export default App;
