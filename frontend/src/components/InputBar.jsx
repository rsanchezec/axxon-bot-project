import { useState } from 'react';
import './InputBar.css';

export function InputBar({
  onSend,
  onMicToggle,
  isVoiceActive,
  isVoiceConnecting,
  isConnected,
  isProcessing,
}) {
  const [text, setText] = useState('');

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || isProcessing) return;
    onSend(trimmed);
    setText('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="input-bar">
      <div className="input-container">
        <input
          className="input-text"
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Pregunta lo que quieras"
          disabled={!isConnected || isVoiceActive}
        />
        <div className="input-actions">
          <button
            className={`btn-mic ${isVoiceActive ? 'active' : ''} ${isVoiceConnecting ? 'connecting' : ''}`}
            onClick={onMicToggle}
            disabled={!isConnected || isVoiceConnecting}
            title={isVoiceConnecting ? 'Conectando...' : isVoiceActive ? 'Detener voz' : 'Activar voz'}
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5z"/>
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
          </button>
          <button
            className="btn-send"
            onClick={handleSend}
            disabled={!isConnected || !text.trim() || isProcessing || isVoiceActive}
            title="Enviar"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
