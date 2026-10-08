import "./style.css";

import { GameClient } from "./gameClient";
import { messageForKey } from "./input";
import type { StateMessage } from "./types";
import { WorldRenderer } from "./worldRenderer";

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`Required element #${id} is missing`);
  }
  return element as T;
}

const canvas = requireElement<HTMLCanvasElement>("world");
const mapName = requireElement<HTMLElement>("map-name");
const connectionStatus = requireElement<HTMLElement>("connection-status");
const dialog = requireElement<HTMLElement>("dialog");
const dialogSpeaker = requireElement<HTMLElement>("dialog-speaker");
const dialogLine = requireElement<HTMLElement>("dialog-line");
const renderer = new WorldRenderer(canvas);

function showState(message: StateMessage): void {
  renderer.update(message.state);
  mapName.textContent = message.state.map.name;
  const activeDialog = message.state.dialog;
  dialog.classList.toggle("hidden", activeDialog === null);
  if (activeDialog !== null) {
    dialogSpeaker.textContent = activeDialog.speaker;
    dialogLine.textContent = activeDialog.lines[activeDialog.line_index] ?? "";
  }
}

const client = new GameClient(showState, (status) => {
  connectionStatus.textContent = status;
});
client.connect();

window.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }
  const message = messageForKey(event.key, crypto.randomUUID());
  if (message === null) {
    return;
  }
  event.preventDefault();
  client.send(message);
});

