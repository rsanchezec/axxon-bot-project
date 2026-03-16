import './MessageBubble.css';

export function MessageBubble({ message }) {
  const { type, text, isVoice } = message;

  return (
    <div className={`message-row ${type === 'user' ? 'row-right' : 'row-left'}`}>
      <div className={`message-bubble bubble-${type} ${isVoice && type === 'user' ? 'bubble-voice-user' : ''}`}>
        {type === 'bot' && <span className="message-label">Axxon</span>}
        {type === 'transcript' && <span className="message-label">Transcripcion</span>}
        <p className="message-text">{text}</p>
        {isVoice && <span className="voice-indicator">voz</span>}
      </div>
    </div>
  );
}
