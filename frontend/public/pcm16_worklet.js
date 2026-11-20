// The mic's AudioWorklet (16 kHz PCM16, 80 ms frames), loaded as a same-origin file so the app's CSP
// (desktop/main/hardening.js: script-src 'self') allows it. Keep in sync with listen.js WORKLET (a test checks).
class Pcm16 extends AudioWorkletProcessor {
  constructor(){ super(); this.ratio = sampleRate / 16000; this.pos = 0; this.last = 0; this.buf = new Int16Array(1280); this.n = 0; }
  process(inputs){
    const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
    // linear-interpolation resample to 16 kHz; index -1 is the previous block's last sample
    const L = ch.length;
    while (this.pos < L - 1) {
      const i = Math.floor(this.pos), f = this.pos - i, a = i < 0 ? this.last : ch[i], s = a * (1 - f) + ch[i + 1] * f;
      const v = Math.max(-1, Math.min(1, s)); this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(1280); this.n = 0; }
      this.pos += this.ratio;
    }
    this.pos -= L; this.last = ch[L - 1];
    return true;
  }
}
registerProcessor("pcm16-80ms", Pcm16);
