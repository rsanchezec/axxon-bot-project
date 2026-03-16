import { useRef, useCallback } from 'react';

const SAMPLE_RATE = 24000;

/**
 * Hook para reproducir audio PCM 16-bit mono 24kHz del agente.
 * Usa Web Audio API con scheduling secuencial para reproduccion sin cortes.
 *
 * Para manejar interrupciones (usuario empieza a hablar), se trackean
 * todos los BufferSource activos y se detienen en reset().
 */
export function useAudioPlayback() {
  const contextRef = useRef(null);
  const nextStartTimeRef = useRef(0);
  const activeSourcesRef = useRef([]);

  const getContext = useCallback(() => {
    if (!contextRef.current || contextRef.current.state === 'closed') {
      contextRef.current = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: SAMPLE_RATE,
      });
      nextStartTimeRef.current = contextRef.current.currentTime;
    }
    return contextRef.current;
  }, []);

  const playChunk = useCallback((arrayBuffer) => {
    const ctx = getContext();
    if (!ctx) return;

    // Convertir PCM Int16 a Float32 para Web Audio API
    const pcmData = new Int16Array(arrayBuffer);
    const audioData = new Float32Array(pcmData.length);
    for (let i = 0; i < pcmData.length; i++) {
      audioData[i] = pcmData[i] / (pcmData[i] < 0 ? 0x8000 : 0x7fff);
    }

    // Crear AudioBuffer y programar reproduccion
    const audioBuffer = ctx.createBuffer(1, audioData.length, SAMPLE_RATE);
    audioBuffer.getChannelData(0).set(audioData);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    // Trackear este source para poder detenerlo en interrupciones
    activeSourcesRef.current.push(source);
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source);
    };

    const now = ctx.currentTime;
    if (nextStartTimeRef.current < now) {
      nextStartTimeRef.current = now;
    }

    source.start(nextStartTimeRef.current);
    nextStartTimeRef.current += audioBuffer.duration;
  }, [getContext]);

  const reset = useCallback(() => {
    // Detener TODOS los sources que estan sonando o programados
    for (const source of activeSourcesRef.current) {
      try {
        source.stop();
        source.disconnect();
      } catch {
        // Puede fallar si ya termino, ignorar
      }
    }
    activeSourcesRef.current = [];

    if (contextRef.current) {
      nextStartTimeRef.current = contextRef.current.currentTime;
    }
  }, []);

  const cleanup = useCallback(() => {
    // Detener sources activos antes de cerrar
    for (const source of activeSourcesRef.current) {
      try {
        source.stop();
        source.disconnect();
      } catch {
        // ignorar
      }
    }
    activeSourcesRef.current = [];

    if (contextRef.current && contextRef.current.state !== 'closed') {
      contextRef.current.close();
      contextRef.current = null;
    }
    nextStartTimeRef.current = 0;
  }, []);

  return { playChunk, reset, cleanup, getContext };
}
