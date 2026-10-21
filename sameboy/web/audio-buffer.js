// Audio arrives as interleaved, signed little-endian 16-bit stereo at 48 kHz.
export class PcmQueue {
  constructor(outputRate, capacityFrames = 12000) {
    this.samples = new Float32Array(capacityFrames * 2);
    this.capacity = capacityFrames;
    this.read = 0;
    this.length = 0;
    this.phase = 0;
    this.step = 48000 / outputRate;
  }

  clear() {
    this.read = 0;
    this.length = 0;
    this.phase = 0;
  }

  push(buffer) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength % 4 !== 0) return;
    const pcm = new DataView(buffer);
    const frames = buffer.byteLength / 4;
    for (let i = Math.max(0, frames - this.capacity); i < frames; i++) {
      if (this.length === this.capacity) {
        this.read = (this.read + 1) % this.capacity;
        this.length--;
        this.phase = 0;
      }
      const target = ((this.read + this.length) % this.capacity) * 2;
      this.samples[target] = pcm.getInt16(i * 4, true) / 32768;
      this.samples[target + 1] = pcm.getInt16(i * 4 + 2, true) / 32768;
      this.length++;
    }
  }

  render(left, right) {
    left.fill(0);
    right.fill(0);
    for (let i = 0; i < left.length; i++) {
      if (this.length < 2) break;
      const current = this.read * 2;
      const next = ((this.read + 1) % this.capacity) * 2;
      left[i] = this.samples[current] + (this.samples[next] - this.samples[current]) * this.phase;
      right[i] = this.samples[current + 1] + (this.samples[next + 1] - this.samples[current + 1]) * this.phase;
      this.phase += this.step;
      const advance = Math.min(Math.floor(this.phase), this.length);
      this.phase -= Math.floor(this.phase);
      this.read = (this.read + advance) % this.capacity;
      this.length -= advance;
      if (!this.length) this.phase = 0;
    }
  }
}
