import './Header.css';

export function Header({ conversationId, isConnected, isVoiceActive }) {
  const threadLabel = conversationId
    ? `#${conversationId.slice(-6)}`
    : '';

  return (
    <header className="header">
      <div className="header-left">
        <h1 className="header-title">Axxon AI Assistant</h1>
        {threadLabel && <span className="header-thread">{threadLabel}</span>}
      </div>
      <div className="header-right">
        {isVoiceActive && <span className="header-voice-badge">VOZ</span>}
        <span className={`header-status ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className="status-dot" />
          {isConnected ? 'Conectado' : 'Desconectado'}
        </span>
      </div>
    </header>
  );
}
