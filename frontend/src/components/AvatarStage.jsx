import './AvatarStage.css';

/**
 * AvatarStage - Muestra el video del avatar de Azure durante el modo voz.
 *
 * El video se recibe via WebRTC y se reproduce en un <video> element.
 * El audio tambien llega por WebRTC en un <audio> element oculto.
 */
export function AvatarStage({ videoRef, audioRef, avatarState, isVisible }) {
  if (!isVisible) return null;

  const isLoading = avatarState !== 'connected' && avatarState !== 'error';
  const isError = avatarState === 'error';
  const isConnected = avatarState === 'connected';

  return (
    <div className="avatar-stage">
      {isLoading && (
        <div className="avatar-loading">
          <div className="avatar-spinner" />
          <p>Conectando avatar...</p>
        </div>
      )}

      {isError && (
        <div className="avatar-error">
          <p>Error al conectar el avatar</p>
        </div>
      )}

      <video
        ref={videoRef}
        className={`avatar-video${isConnected ? ' visible' : ''}`}
        autoPlay
        playsInline
      />

      <audio ref={audioRef} autoPlay />
    </div>
  );
}
