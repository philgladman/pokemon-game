import "./style.css";

import { GameClient } from "./gameClient";
import { BattlePresentation } from "./battlePresentation";
import { BattleView } from "./battleView";
import { CueAcknowledger } from "./cueAcknowledgement";
import { HeldInputController } from "./input";
import { RetroRenderer } from "./renderers/retro/RetroRenderer";
import { TransitionCoordinator } from "./transitionCoordinator";
import { TransitionAcknowledger } from "./transitionAcknowledgement";
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
  const choice = requireElement<HTMLElement>("choice");
  const choicePrompt = requireElement<HTMLElement>("choice-prompt");
  const choiceOptions = requireElement<HTMLOListElement>("choice-options");
  const battleRoot = requireElement<HTMLElement>("battle");
  const battleView = new BattleView(battleRoot);
  const renderer = await createRenderer(canvas);
  let input: HeldInputController | null = null;
  let cueAcknowledger: CueAcknowledger | null = null;
  let transitionAcknowledger: TransitionAcknowledger | null = null;
  let battle: BattlePresentation | null = null;
  let battleActive = false;
  let available = true;

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
    const activeChoice = message.state.choice;
    choice.classList.toggle("hidden", activeChoice === null);
    if (activeChoice !== null) {
      choicePrompt.textContent = activeChoice.prompt;
      choiceOptions.replaceChildren(
        ...activeChoice.options.map((option, index) => {
          const item = document.createElement("li");
          item.textContent = option.label;
          item.classList.toggle("selected", index === activeChoice.selected_index);
          return item;
        }),
      );
    }
  }

  const transitionCoordinator = new TransitionCoordinator(
    renderer,
    transitionOverlay,
    (enabled) => input?.setEnabled(enabled && !battleActive && available),
    applyInterface,
    () => {
      connectionStatus.textContent = "Unable to finish transition — press E or Space to retry";
    },
    undefined,
    {
      movementCue: (message) => cueAcknowledger?.rendered(message.state) ?? false,
      transition: (message) => transitionAcknowledger?.rendered(message.state) ?? false,
    },
  );

  function showState(message: StateMessage): void {
    if (message.state.battle != null) {
      battleActive = true;
      input?.setEnabled(false);
      input?.reset();
      dialog.classList.add("hidden");
      choice.classList.add("hidden");
      transitionOverlay.hidden = true;
      mapName.textContent = "Rival battle";
      void battle?.present(message.state.battle, message);
      return;
    }
    const leavingBattle = battleActive;
    if (leavingBattle) {
      battleActive = false;
      battle?.close();
      battleRoot.hidden = true;
      input?.reset();
    }
    const presentation = input?.handleState(message) ?? { resetGait: true };
    void transitionCoordinator.present(message, presentation).then(() => {
      if (leavingBattle && !battleActive && available) input?.setEnabled(true);
    });
  }

  const client = new GameClient(
    showState,
    (status) => {
      connectionStatus.textContent = status;
    },
    () => {
      available = false;
      battle?.unavailable();
      input?.setEnabled(false);
      input?.reset();
      cueAcknowledger?.reset();
      transitionAcknowledger?.reset();
    },
  );
  input = new HeldInputController((message) => client.send(message), () => crypto.randomUUID());
  battle = new BattlePresentation(battleView, (message) => client.send(message), () => crypto.randomUUID());
  battleView.onActivate = (slot) => { void battle?.activate(slot); };
  battleView.onRetry = () => { void battle?.retry(); };
  cueAcknowledger = new CueAcknowledger(
    (message) => client.send(message),
    () => crypto.randomUUID(),
  );
  transitionAcknowledger = new TransitionAcknowledger(
    (message) => client.send(message),
    () => crypto.randomUUID(),
  );
  client.connect();

  window.addEventListener("keydown", (event) => {
    if (battleActive) {
      if (battle?.keyDown(event.code, event.repeat)) event.preventDefault();
      return;
    }
    if (
      transitionCoordinator.hasPendingRetry()
      && (event.code === "KeyE" || event.code === "Space")
    ) {
      if (!event.repeat) void transitionCoordinator.retryPending();
      event.preventDefault();
      return;
    }
    if (input?.keyDown(event.code, event.repeat)) event.preventDefault();
  });
  window.addEventListener("keyup", (event) => {
    if (battleActive) return;
    if (input?.keyUp(event.code)) event.preventDefault();
  });
  window.addEventListener("blur", () => input?.reset());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) input?.reset();
  });
}

void main();
