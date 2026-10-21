import { describe, expect, it, vi } from 'vitest';
// The independent container serves these browser modules without a build step.
// @ts-expect-error Standalone JavaScript intentionally lives outside the app's TS project.
import { PcmQueue } from '../../sameboy/web/audio-buffer.js';
// @ts-expect-error Standalone JavaScript intentionally lives outside the app's TS project.
import { GameKeyboard } from '../../sameboy/web/keyboard.js';

function pcm(frames: Array<[number, number]>): ArrayBuffer {
  const buffer = new ArrayBuffer(frames.length * 4);
  const view = new DataView(buffer);
  frames.forEach(([left, right], i) => {
    view.setInt16(i * 4, left, true);
    view.setInt16(i * 4 + 2, right, true);
  });
  return buffer;
}

function key(code: string) {
  return { code, preventDefault: vi.fn(), stopImmediatePropagation: vi.fn() };
}

describe('SameBoy browser keyboard', () => {
  it('sends exact SDL keysyms, suppresses repeats and releases every held key on blur', () => {
    const send = vi.fn();
    const keyboard = new GameKeyboard(send);
    const event = key('KeyX');
    keyboard.handle(event, true);
    keyboard.handle(event, true);
    keyboard.handle(key('Space'), true);
    keyboard.release();
    keyboard.release();
    expect(send.mock.calls).toEqual([
      [0x78, 'KeyX', true], [0x20, 'Space', true],
      [0x78, 'KeyX', false], [0x20, 'Space', false],
    ]);
    expect(event.preventDefault).toHaveBeenCalledTimes(2);
  });

  it('leaves unrelated browser keys alone and ignores unheld releases', () => {
    const send = vi.fn();
    const keyboard = new GameKeyboard(send);
    const event = key('Tab');
    expect(keyboard.handle(event, true)).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
    keyboard.handle(key('ArrowLeft'), false);
    expect(send).not.toHaveBeenCalled();
  });

  it('maps all documented controls and removes released keys from blur cleanup', () => {
    const send = vi.fn();
    const keyboard = new GameKeyboard(send);
    const keys = [
      ['ArrowUp', 0xff52], ['ArrowDown', 0xff54], ['ArrowLeft', 0xff51],
      ['ArrowRight', 0xff53], ['KeyZ', 0x7a], ['Enter', 0xff0d],
      ['Backspace', 0xff08], ['Escape', 0xff1b],
    ] as const;
    for (const [code, keysym] of keys) {
      keyboard.handle(key(code), true);
      keyboard.handle(key(code), false);
      expect(send).toHaveBeenLastCalledWith(keysym, code, false);
    }
    keyboard.release();
    expect(send).toHaveBeenCalledTimes(keys.length * 2);
  });
});

describe('SameBoy audio worklet queue', () => {
  it('decodes signed little endian stereo and emits silence on underrun', () => {
    const queue = new PcmQueue(48000);
    queue.push(pcm([[16384, -16384], [-32768, 32767], [0, 0]]));
    const left = new Float32Array(5).fill(1);
    const right = new Float32Array(5).fill(1);
    queue.render(left, right);
    expect([...left]).toEqual([0.5, -1, 0, 0, 0]);
    expect(right[0]).toBe(-0.5);
    expect(right[1]).toBeCloseTo(32767 / 32768);
    expect([...right.slice(2)]).toEqual([0, 0, 0]);
  });

  it('resamples to the actual audio context rate with interpolation', () => {
    const queue = new PcmQueue(96000);
    queue.push(pcm([[0, 0], [16384, -16384], [0, 0]]));
    const left = new Float32Array(4);
    const right = new Float32Array(4);
    queue.render(left, right);
    expect([...left]).toEqual([0, 0.25, 0.5, 0.25]);
    expect([...right]).toEqual([0, -0.25, -0.5, -0.25]);
  });

  it('drops oldest audio when full and ignores malformed frames', () => {
    const queue = new PcmQueue(48000, 3);
    queue.push(pcm([[1000, 0], [2000, 0]]));
    queue.push(pcm([[3000, 0], [4000, 0], [5000, 0], [6000, 0]]));
    queue.push(new ArrayBuffer(3));
    expect(queue.length).toBe(3);
    const left = new Float32Array(2);
    queue.render(left, new Float32Array(2));
    expect([...left]).toEqual([4000 / 32768, 5000 / 32768]);
  });

  it('clears pending samples on disconnect', () => {
    const queue = new PcmQueue(44100);
    queue.push(pcm([[1000, 2000], [3000, 4000]]));
    queue.clear();
    const left = new Float32Array(4).fill(1);
    const right = new Float32Array(4).fill(1);
    queue.render(left, right);
    expect([...left, ...right]).toEqual(Array(8).fill(0));
  });
});
