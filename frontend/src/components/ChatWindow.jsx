import { useEffect, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import './ChatWindow.css';

export function ChatWindow({ messages, isProcessing }) {
  const bottomRef = useRef(null);

  // Auto-scroll al ultimo mensaje
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isProcessing]);

  return (
    <div className="chat-window">
      {messages.length === 0 && (
        <div className="chat-empty">
          <p>Pregunta lo que quieras</p>
        </div>
      )}
      {messages.map((msg, i) => (
        <MessageBubble key={i} message={msg} />
      ))}
      {isProcessing && (
        <div className="message-row row-left">
          <div className="message-bubble bubble-bot typing-indicator">
            <span /><span /><span />
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
