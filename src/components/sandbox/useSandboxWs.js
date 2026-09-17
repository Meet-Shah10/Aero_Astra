/**
 * useSandboxWs.js
 * ================
 * Custom hook for the /ws/sandbox WebSocket.
 *
 * startRun(config, 'A')  — start Run A (resets all frames)
 * startRun(config, 'B')  — start Run B (compare mode, keeps A frames)
 * stopRun()              — abort mid-run
 */
import { useRef, useState, useCallback, useEffect } from 'react';

const WS_URL = 'ws://localhost:8000/ws/sandbox';
const RENDER_THROTTLE_MS = 50;

export default function useSandboxWs() {
  const wsRef       = useRef(null);
  const framesARef  = useRef([]);
  const framesBRef  = useRef([]);
  const renderTimer = useRef(null);
  const lastRender  = useRef(0);

  const [status,   setStatus]   = useState('idle');
  const [framesA,  setFramesA]  = useState([]);
  const [framesB,  setFramesB]  = useState([]);
  const [latestA,  setLatestA]  = useState(null);
  const [latestB,  setLatestB]  = useState(null);
  const [progress, setProgress] = useState({ A: 0, B: 0 });

  const scheduleFlush = useCallback(() => {
    if (renderTimer.current) return;
    const now = Date.now();
    const delay = Math.max(0, RENDER_THROTTLE_MS - (now - lastRender.current));
    renderTimer.current = setTimeout(() => {
      renderTimer.current = null;
      lastRender.current = Date.now();
      setFramesA([...framesARef.current]);
      setFramesB([...framesBRef.current]);
    }, delay);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState < 2) return;
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'sandbox_frame') {
          const frame = {
            t: msg.t, progress: msg.progress,
            fault_active: msg.fault_active, fault_onset_t: msg.fault_onset_t,
            subsystems: msg.subsystems, vitals: msg.vitals,
          };
          if (msg.run_id === 'A') {
            framesARef.current.push(frame);
            setLatestA(frame);
            setProgress(p => ({ ...p, A: msg.progress }));
          } else {
            framesBRef.current.push(frame);
            setLatestB(frame);
            setProgress(p => ({ ...p, B: msg.progress }));
          }
          scheduleFlush();
        } else if (msg.type === 'sandbox_done') {
          scheduleFlush();
          setStatus('done');
        } else if (msg.type === 'sandbox_error') {
          setStatus('error');
          console.error('[sandbox]', msg.message);
        } else if (msg.type === 'sandbox_stopped') {
          setStatus('stopped');
        }
      } catch (err) {
        console.error('[sandbox ws] parse error', err);
      }
    };
    ws.onerror = () => setStatus('error');
  }, [scheduleFlush]);

  const startRun = useCallback((config, runId = 'A') => {
    if (runId === 'A') {
      framesARef.current = [];
      framesBRef.current = [];
      setFramesA([]); setFramesB([]);
      setLatestA(null); setLatestB(null);
      setProgress({ A: 0, B: 0 });
      setStatus('running');
    }
    connect();
    const doSend = () => {
      wsRef.current.send(JSON.stringify({ action: 'start', run_id: runId, ...config }));
    };
    if (wsRef.current?.readyState === 1) {
      doSend();
    } else {
      wsRef.current.addEventListener('open', doSend, { once: true });
    }
  }, [connect]);

  const stopRun = useCallback(() => {
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ action: 'stop' }));
    }
    setStatus('stopped');
  }, []);

  useEffect(() => () => {
    if (renderTimer.current) clearTimeout(renderTimer.current);
    if (wsRef.current) wsRef.current.close();
  }, []);

  return { status, framesA, framesB, latestA, latestB, progress, startRun, stopRun };
}
