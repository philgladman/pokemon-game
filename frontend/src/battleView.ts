import type { BattleDisplay, BattleSurface } from "./battlePresentation";
import type { BattleSnapshot } from "./types";

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

export class BattleView implements BattleSurface {
  private readonly loaded = new Map<string, Promise<void>>();
  private focusedCommand: string | undefined;
  onActivate: (slot?: number | null) => void = () => undefined;
  onRetry: () => void = () => undefined;

  constructor(private readonly root: HTMLElement) {
    // Keep focus inside the battle while a submitted button is disabled, so
    // the next enabled command can continue the native keyboard interaction.
    root.tabIndex = -1;
  }

  async loadAssets(battle: BattleSnapshot): Promise<void> {
    await Promise.all([battle.player.image_url, battle.rival.image_url].map((url) => {
      let pending = this.loaded.get(url);
      if (pending === undefined) {
        pending = new Promise<void>((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve();
          image.onerror = () => reject(new Error("Battle artwork unavailable"));
          image.src = url;
        });
        this.loaded.set(url, pending);
        void pending.catch(() => this.loaded.delete(url));
      }
      return pending;
    }));
  }

  painted(): Promise<void> {
    // Two animation frames put the updated DOM on screen before accepting advances.
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  }

  render(display: BattleDisplay): void {
    const { battle, frame } = display;
    this.root.hidden = false;
    const ownsFocus = this.root.contains(document.activeElement);
    if (ownsFocus && document.activeElement !== this.root) {
      this.focusedCommand = (document.activeElement as HTMLElement).dataset.command;
      this.root.focus();
    }
    const arena = element("div");
    arena.className = "battle-arena";
    for (const side of ["rival", "player"] as const) {
      const pokemon = battle[side];
      const level = frame === null ? pokemon.level : frame[`${side}_level`];
      const maxHp = frame === null ? pokemon.max_hp : frame[`${side}_max_hp`];
      const card = element("section");
      card.className = `battle-pokemon battle-${side}`;
      card.append(element("h2", `${pokemon.name} · Lv ${level}`));
      const hp = frame === null ? pokemon.hp : side === "player" ? frame.player_hp : frame.rival_hp;
      const meter = element("div");
      meter.className = "battle-hp";
      meter.setAttribute("role", "meter");
      meter.setAttribute("aria-label", `${pokemon.name} HP`);
      meter.setAttribute("aria-valuemin", "0");
      meter.setAttribute("aria-valuemax", String(maxHp));
      meter.setAttribute("aria-valuenow", String(hp));
      const fill = element("span");
      fill.className = "battle-hp-fill";
      fill.style.width = `${maxHp > 0 ? Math.max(0, Math.min(1, hp / maxHp)) * 100 : 0}%`;
      meter.append(fill);
      card.append(meter, element("p", `HP ${hp} / ${maxHp}`));
      const image = element("img");
      image.src = pokemon.image_url;
      image.alt = `${pokemon.name}, ${side === "player" ? "back" : "front"} view`;
      card.append(image);
      arena.append(card);
    }
    const text = element("p", display.disconnected
      ? "Disconnected. Reload the adventure to reconnect." : display.error ?? display.text);
    text.className = "battle-text";
    text.setAttribute("aria-live", "polite");
    const commands = element("div");
    commands.className = "battle-commands";
    const button = (label: string, command: string, action: () => void, disabled = false): HTMLButtonElement => {
      const node = element("button", label);
      node.type = "button";
      node.dataset.command = command;
      node.disabled = disabled;
      node.addEventListener("click", action);
      commands.append(node);
      return node;
    };
    if (display.error !== null && !display.disconnected) {
      button("Retry artwork", "retry", this.onRetry);
    } else if (display.disconnected) {
      button("Reload adventure", "reload", () => window.location.reload());
    } else if (battle.batch !== null) {
      button(display.ready ? "Continue · E / Space" : "Please wait…", "continue",
        () => this.onActivate(), !display.ready);
    } else if (battle.action_token !== null) {
      let availableIndex = 0;
      for (const [index, move] of battle.player.moves.entries()) {
        const pp = frame?.player_pp[index] ?? move.pp;
        const node = button(`${move.name} · PP ${pp}/${move.max_pp}`, `move-${move.slot}`,
          () => this.onActivate(move.slot), !display.ready || pp === 0);
        if (pp > 0) {
          node.classList.toggle("selected", availableIndex === display.selected);
          availableIndex += 1;
        }
      }
      if (availableIndex === 0) {
        button("STRUGGLE", "struggle", () => this.onActivate(null), !display.ready);
      }
    }
    const help = element("small", "Arrows / WASD select · E / Space confirm · Enter activates focused button");
    const stats = element("section");
    stats.className = "battle-stats";
    stats.hidden = !frame?.show_stats;
    if (frame?.show_stats) {
      stats.setAttribute("aria-label", `${battle.player.name} stats`);
      const values = frame.player_stats;
      for (const [label, value] of [
        ["HP", values.hp], ["ATTACK", values.attack], ["DEFENSE", values.defense],
        ["SPEED", values.speed], ["SPECIAL", values.special],
      ]) stats.append(element("p", `${label} ${value}`));
    }
    this.root.replaceChildren(arena, text, stats, commands, help);
    if (ownsFocus) {
      const enabled = [...commands.querySelectorAll("button")].filter((node) => !node.disabled);
      const target = enabled.find((node) => node.dataset.command === this.focusedCommand) ?? enabled[0];
      target?.focus();
    }
  }
}
