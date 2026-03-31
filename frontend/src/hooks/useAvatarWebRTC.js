import { useRef, useState, useCallback } from 'react';

/**
 * Hook para manejar la conexion WebRTC del avatar de Azure Voice Live.
 *
 * Gestiona la creacion de RTCPeerConnection, transceivers de video/audio,
 * y el intercambio de SDP offer/answer con el backend.
 */
export function useAvatarWebRTC() {
  const pcRef = useRef(null);
  const videoRef = useRef(null);
  const audioRef = useRef(null);
  const onConnectedCallbackRef = useRef(null);
  const onErrorCallbackRef = useRef(null);
  const [avatarState, setAvatarState] = useState('idle');

  /**
   * Registra callbacks para eventos de conexion del avatar.
   */
  const setCallbacks = useCallback((onConnected, onError) => {
    onConnectedCallbackRef.current = onConnected;
    onErrorCallbackRef.current = onError;
  }, []);

  /**
   * Paso 1: Recibe ICE servers del backend, crea PeerConnection,
   * genera SDP offer y lo retorna.
   */
  const initializeWithIceServers = useCallback(async (iceServers) => {
    try {
      setAvatarState('connecting');

      const rtcIceServers = iceServers.map((server) => ({
        urls: server.urls,
        username: server.username || undefined,
        credential: server.credential || undefined,
      }));

      const pc = new RTCPeerConnection({
        iceServers: rtcIceServers,
        bundlePolicy: 'max-bundle',
      });
      pcRef.current = pc;

      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.addTransceiver('audio', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (event.track.kind === 'video' && videoRef.current) {
          videoRef.current.srcObject = event.streams[0] || new MediaStream([event.track]);
        } else if (event.track.kind === 'audio' && audioRef.current) {
          audioRef.current.srcObject = event.streams[0] || new MediaStream([event.track]);
        }
      };

      pc.oniceconnectionstatechange = () => {
        const state = pc.iceConnectionState;
        console.log(`[Avatar] ICE state: ${state}`);

        if (state === 'connected' || state === 'completed') {
          setAvatarState('connected');
          if (onConnectedCallbackRef.current) {
            onConnectedCallbackRef.current();
          }
        } else if (state === 'failed') {
          console.error('[Avatar] ICE connection failed');
          setAvatarState('error');
          if (onErrorCallbackRef.current) {
            onErrorCallbackRef.current('ICE connection failed');
          }
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Esperar a que termine ICE gathering
      await new Promise((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
          return;
        }
        const onGatheringChange = () => {
          if (pc.iceGatheringState === 'complete') {
            pc.removeEventListener('icegatheringstatechange', onGatheringChange);
            resolve();
          }
        };
        pc.addEventListener('icegatheringstatechange', onGatheringChange);
        setTimeout(() => {
          pc.removeEventListener('icegatheringstatechange', onGatheringChange);
          resolve();
        }, 5000);
      });

      const localSdp = pc.localDescription?.sdp ?? '';
      const sdpOffer = btoa(JSON.stringify({ type: 'offer', sdp: localSdp }));
      return sdpOffer;
    } catch (err) {
      console.error('Error initializing WebRTC:', err);
      setAvatarState('error');
      if (onErrorCallbackRef.current) {
        onErrorCallbackRef.current(err.message);
      }
      return null;
    }
  }, []);

  /**
   * Paso 2: Recibe SDP answer del backend y completa el handshake WebRTC.
   */
  const handleAnswer = useCallback(async (sdpAnswerB64) => {
    const pc = pcRef.current;
    if (!pc) return;

    try {
      const payload = JSON.parse(atob(sdpAnswerB64));
      await pc.setRemoteDescription(new RTCSessionDescription(payload));
    } catch (err) {
      console.error('Error setting remote description:', err);
      setAvatarState('error');
      if (onErrorCallbackRef.current) {
        onErrorCallbackRef.current(err.message);
      }
    }
  }, []);

  /**
   * Limpieza: Cierra peer connection y libera recursos.
   */
  const cleanup = useCallback(() => {
    if (pcRef.current) {
      pcRef.current.oniceconnectionstatechange = null;
      pcRef.current.ontrack = null;
      pcRef.current.getSenders().forEach((sender) => sender.track?.stop());
      pcRef.current.getReceivers().forEach((receiver) => receiver.track?.stop());
      pcRef.current.close();
      pcRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    if (audioRef.current) {
      audioRef.current.srcObject = null;
    }
    onConnectedCallbackRef.current = null;
    onErrorCallbackRef.current = null;
    setAvatarState('idle');
  }, []);

  return {
    videoRef,
    audioRef,
    avatarState,
    setCallbacks,
    initializeWithIceServers,
    handleAnswer,
    cleanup,
  };
}
