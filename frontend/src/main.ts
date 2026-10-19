import "./style.css";

import { GameClient } from "./gameClient";
import { HeldInputController } from "./input";
import { RetroRenderer } from "./renderers/retro/RetroRenderer";
import { TransitionCoordinator } from "./transitionCoordinator";
import type { GameRenderer, StateMessage } from "./types";

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`Required element #${id} is missing`);
  return element as T;
}

async function createRenderer(canvas: HTMLCanvasElement): Promise<GameRenderer> {
  const requested = new URLSearchParams(window.location.search).get("renderer");
  if (requested === "3d") {
    const { WorldRenderer } = await import("./renderers/three_d/WorldRenderer");
    document.body.classList.add("three-d");
    return new WorldRenderer(canvas);
  }
  return new RetroRenderer(canvas);
}

async function main(): Promise<void> {
  const canvas = requireElement<HTMLCanvasElement>("world");
  const mapName = requireElement<HTMLElement>("map-name");
  const connectionStatus = requireElement<HTMLElement>("connection-status");
  const dialog = requireElement<HTMLElement>("dialog");
  const dialogLine = requireElement<HTMLElement>("dialog-line");
  const transitionOverlay = requireElement<HTMLElement>("transition-overlay");
  const renderer = await createRenderer(canvas);
  let input: HeldInputController | null = null;

  function applyInterface(message: StateMessage): void {
    mapName.textContent = message.state.map.source_name;
    const activeDialog = message.state.dialog;
    dialog.classList.toggle("hidden", activeDialog === null);
    if (activeDialog !== null) {
      dialogLine.textContent = activeDialog.pages[activeDialog.page_index] ?? "";
    }
    if (message.action === "unsupported_interaction") {
      connectionStatus.textContent = `Unsupported source script: ${message.reason ?? "unknown"}`;
    }
  }

  const transitionCoordinator = new TransitionCoordinator(
    renderer,
    transitionOverlay,
    (enabled) => input?.setEnabled(enabled),
    applyInterface,
    () => {
      connectionStatus.textContent = "Unable to render the latest game state";
    },
  );

  function showState(message: StateMessage): void {
    const presentation = input?.handleState(message) ?? { resetGait: true };
    void transitionCoordinator.present(message, presentation);
  }

  const client = new GameClient(
    showState,
    (status) => {
      connectionStatus.textContent = status;
    },
    () => input?.reset(),
  );
  input = new HeldInputController((message) => client.send(message), () => crypto.randomUUID());
  client.connect();

  window.addEventListener("keydown", (event) => {
    if (input?.keyDown(event.code, event.repeat)) event.preventDefault();
  });
  window.addEventListener("keyup", (event) => {
    if (input?.keyUp(event.code)) event.preventDefault();
  });
  window.addEventListener("blur", () => input?.reset());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) input?.reset();
  });
}

void main();
