export const GAME_KEYS = {
  ArrowUp: 0xff52, ArrowDown: 0xff54, ArrowLeft: 0xff51, ArrowRight: 0xff53,
  KeyX: 0x78, KeyZ: 0x7a, Enter: 0xff0d, Backspace: 0xff08,
  Escape: 0xff1b, Space: 0x20,
};

export class GameKeyboard {
  constructor(sendKey) {
    this.sendKey = sendKey;
    this.held = new Set();
  }

  handle(event, down) {
    const keysym = GAME_KEYS[event.code];
    if (keysym === undefined) return false;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (down && !this.held.has(event.code)) {
      this.held.add(event.code);
      this.sendKey(keysym, event.code, true);
    } else if (!down && this.held.delete(event.code)) {
      this.sendKey(keysym, event.code, false);
    }
    return true;
  }

  release() {
    for (const code of this.held) this.sendKey(GAME_KEYS[code], code, false);
    this.held.clear();
  }
}
