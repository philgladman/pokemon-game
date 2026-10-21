import { PcmQueue } from './audio-buffer.js';

class SameBoyAudio extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = new PcmQueue(sampleRate);
    this.port.onmessage = ({ data }) => {
      if (data === 'clear') this.queue.clear();
      else this.queue.push(data);
    };
  }

  process(_inputs, outputs) {
    const [left, right] = outputs[0];
    if (left && right) this.queue.render(left, right);
    return true;
  }
}

registerProcessor('sameboy-audio', SameBoyAudio);
