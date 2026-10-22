import assert from 'node:assert/strict';
import { describe, it, mock } from 'node:test';
import { PcmQueue } from '../audio-buffer.js';
import { GameKeyboard } from '../keyboard.js';

function pcm(frames) {
  const buffer = new ArrayBuffer(frames.length * 4);
  const view = new DataView(buffer);
  frames.forEach(([left, right], i) => {
    view.setInt16(i * 4, left, true);
    view.setInt16(i * 4 + 2, right, true);
  });
  return buffer;
}

function key(code) {
  return { code, preventDefault: mock.fn(), stopImmediatePropagation: mock.fn() };
}

describe('SameBoy browser keyboard', () => {
  it('sends exact SDL keysyms, suppresses repeats and releases every held key on blur', () => {
    const send = mock.fn();
    const keyboard = new GameKeyboard(send);
    const event = key('KeyX');
    keyboard.handle(event, true);
    keyboard.handle(event, true);
    keyboard.handle(key('Space'), true);
    keyboard.release();
    keyboard.release();
    assert.deepEqual(send.mock.calls.map(call => call.arguments), [
      [0x78, 'KeyX', true], [0x20, 'Space', true],
      [0x78, 'KeyX', false], [0x20, 'Space', false],
    ]);
    assert.equal(event.preventDefault.mock.callCount(), 2);
  });

  it('leaves unrelated browser keys alone and ignores unheld releases', () => {
    const send = mock.fn();
    const keyboard = new GameKeyboard(send);
    const event = key('Tab');
    assert.equal(keyboard.handle(event, true), false);
    assert.equal(event.preventDefault.mock.callCount(), 0);
    keyboard.handle(key('ArrowLeft'), false);
    assert.equal(send.mock.callCount(), 0);
  });

  it('maps all documented controls and removes released keys from blur cleanup', () => {
    const send = mock.fn();
    const keyboard = new GameKeyboard(send);
    const keys = [
      ['ArrowUp', 0xff52], ['ArrowDown', 0xff54], ['ArrowLeft', 0xff51],
      ['ArrowRight', 0xff53], ['KeyZ', 0x7a], ['Enter', 0xff0d],
      ['Backspace', 0xff08], ['Escape', 0xff1b],
    ];
    for (const [code, keysym] of keys) {
      keyboard.handle(key(code), true);
      keyboard.handle(key(code), false);
      assert.deepEqual(send.mock.calls.at(-1).arguments, [keysym, code, false]);
    }
    keyboard.release();
    assert.equal(send.mock.callCount(), keys.length * 2);
  });
});

describe('SameBoy audio worklet queue', () => {
  it('decodes signed little endian stereo and emits silence on underrun', () => {
    const queue = new PcmQueue(48000);
    queue.push(pcm([[16384, -16384], [-32768, 32767], [0, 0]]));
    const left = new Float32Array(5).fill(1);
    const right = new Float32Array(5).fill(1);
    queue.render(left, right);
    assert.deepEqual([...left], [0.5, -1, 0, 0, 0]);
    assert.equal(right[0], -0.5);
    assert.ok(Math.abs(right[1] - 32767 / 32768) < 1e-7);
    assert.deepEqual([...right.slice(2)], [0, 0, 0]);
  });

  it('resamples to the actual audio context rate with interpolation', () => {
    const queue = new PcmQueue(96000);
    queue.push(pcm([[0, 0], [16384, -16384], [0, 0]]));
    const left = new Float32Array(4);
    const right = new Float32Array(4);
    queue.render(left, right);
    assert.deepEqual([...left], [0, 0.25, 0.5, 0.25]);
    assert.deepEqual([...right], [0, -0.25, -0.5, -0.25]);
  });

  it('drops oldest audio when full and ignores malformed frames', () => {
    const queue = new PcmQueue(48000, 3);
    queue.push(pcm([[1000, 0], [2000, 0]]));
    queue.push(pcm([[3000, 0], [4000, 0], [5000, 0], [6000, 0]]));
    queue.push(new ArrayBuffer(3));
    assert.equal(queue.length, 3);
    const left = new Float32Array(2);
    queue.render(left, new Float32Array(2));
    assert.deepEqual([...left], [4000 / 32768, 5000 / 32768]);
  });

  it('clears pending samples on disconnect', () => {
    const queue = new PcmQueue(44100);
    queue.push(pcm([[1000, 2000], [3000, 4000]]));
    queue.clear();
    const left = new Float32Array(4).fill(1);
    const right = new Float32Array(4).fill(1);
    queue.render(left, right);
    assert.deepEqual([...left, ...right], Array(8).fill(0));
  });
});

