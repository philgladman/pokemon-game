import RFB from '/novnc/core/rfb.js';
import { GAME_KEYS, GameKeyboard } from './keyboard.js';

function main() {
  const screen = document.querySelector('#screen');
  const status = document.querySelector('#status');
  const audioStatus = document.querySelector('#audio-status');
  const audioButton = document.querySelector('#audio');
  const socketUrl = (path) => `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}`;
  let rfb;
  let connected = false;
  let audioContext;
  let audioNode;
  let audioSocket;
  let audioGeneration = 0;
  const keyboard = new GameKeyboard((...args) => { if (connected) rfb.sendKey(...args); });

  function stopAudio(message = 'Audio off') {
    audioGeneration++;
    const socket = audioSocket;
    audioSocket = undefined;
    if (socket) socket.close();
    audioNode?.port.postMessage('clear');
    audioNode?.disconnect();
    audioNode = undefined;
    if (audioContext) void audioContext.close().catch(() => {});
    audioContext = undefined;
    audioButton.disabled = false;
    audioButton.textContent = 'Enable audio';
    audioStatus.textContent = message;
  }

  async function enableAudio() {
    if (audioContext) { stopAudio(); return; }
    const generation = ++audioGeneration;
    audioButton.disabled = true;
    audioStatus.textContent = 'Connecting audio…';
    try {
      audioContext = new AudioContext({ sampleRate: 48000, latencyHint: 'interactive' });
      // Resume inside the click gesture, before loading the worklet asynchronously.
      const context = audioContext;
      await context.resume();
      await context.audioWorklet.addModule('/audio-worklet.js');
      if (generation !== audioGeneration) return;
      audioNode = new AudioWorkletNode(context, 'sameboy-audio', { outputChannelCount: [2] });
      audioNode.connect(context.destination);
      const socket = new WebSocket(socketUrl('/audio'));
      audioSocket = socket;
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        if (generation !== audioGeneration) return;
        audioStatus.textContent = 'Audio on';
        audioButton.disabled = false;
        audioButton.textContent = 'Disable audio';
      };
      socket.onmessage = ({ data }) => {
        if (generation === audioGeneration && context.state === 'running' && !document.hidden && data instanceof ArrayBuffer) {
          audioNode.port.postMessage(data, [data]);
        }
      };
      socket.onerror = () => { if (generation === audioGeneration) stopAudio('Audio connection failed. Enable audio to retry.'); };
      socket.onclose = () => { if (generation === audioGeneration) stopAudio('Audio disconnected. Enable audio to reconnect.'); };
      audioNode.onprocessorerror = () => stopAudio('Audio processing failed. Enable audio to retry.');
    } catch {
      if (generation === audioGeneration) stopAudio('Audio unavailable. Use a browser with AudioWorklet on localhost or HTTPS.');
    }
  }

  function connectDisplay() {
    keyboard.release();
    connected = false;
    if (rfb) rfb.disconnect();
    screen.replaceChildren();
    status.textContent = 'Connecting display…';
    try {
      const client = new RFB(screen, socketUrl('/websockify'));
      rfb = client;
      client.scaleViewport = true;
      client.resizeSession = false;
      client.focusOnClick = false;
      client.addEventListener('connect', () => {
        if (rfb !== client) return;
        connected = true;
        // A transport loss can prevent key-up delivery on the previous session.
        for (const [code, keysym] of Object.entries(GAME_KEYS)) client.sendKey(keysym, code, false);
        status.textContent = 'Display connected';
      });
      client.addEventListener('disconnect', () => {
        if (rfb !== client) return;
        keyboard.release();
        connected = false;
        stopAudio('Audio off');
        status.textContent = 'Display disconnected. Reconnect to continue.';
      });
      client.addEventListener('securityfailure', () => {
        if (rfb === client) status.textContent = 'Display authentication failed. Check the container configuration.';
      });
      client.addEventListener('credentialsrequired', () => {
        if (rfb === client) status.textContent = 'Display requires credentials. Check the container configuration.';
      });
    } catch {
      status.textContent = 'Unable to connect display. Reconnect to retry.';
    }
  }

  // The emulator is keyboard controlled. Keep noVNC pointer state neutral while
  // allowing a click to focus the game; no private pointer-release APIs are needed.
  for (const type of ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'mousemove', 'touchstart', 'touchmove', 'touchend', 'wheel', 'contextmenu']) {
    screen.addEventListener(type, (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (type === 'pointerdown' || type === 'mousedown' || type === 'touchstart') screen.focus();
    }, { capture: true, passive: false });
  }
  screen.addEventListener('keydown', (event) => keyboard.handle(event, true), true);
  screen.addEventListener('keyup', (event) => keyboard.handle(event, false), true);
  screen.addEventListener('focusout', () => keyboard.release());
  window.addEventListener('blur', () => keyboard.release());
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { keyboard.release(); audioNode?.port.postMessage('clear'); }
  });
  window.addEventListener('pagehide', () => {
    keyboard.release();
    stopAudio();
    rfb?.disconnect();
  });
  document.querySelector('#reconnect').addEventListener('click', connectDisplay);
  audioButton.addEventListener('click', enableAudio);
  connectDisplay();
}

main();
