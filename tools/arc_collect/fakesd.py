"""An in-memory stand-in for `sounddevice` (the --dry-run mode and the tests). Nothing touches a real device.

The duplex Stream "plays" each output block into a delay line and hands the callback, as `indata`, what a mic would
hear: the played signal delayed by `delay_s`, attenuated, a little low-passed (a laptop speaker), plus a noise floor.
It runs as fast as the CPU allows (no real-time pacing), so a 25-minute session dry-runs in well under a minute.
"""
from __future__ import annotations

import threading
import types

import numpy as np


class CallbackStop(Exception):
    pass


class CallbackAbort(Exception):
    pass


class PortAudioError(Exception):
    pass


DEVICES = [
    {"name": "MacBook Pro Microphone", "index": 0, "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0,
     "default_samplerate": 48000.0, "default_low_input_latency": 0.03, "default_high_input_latency": 0.04,
     "default_low_output_latency": 0.01, "default_high_output_latency": 0.02},
    {"name": "MacBook Pro Speakers", "index": 1, "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2,
     "default_samplerate": 48000.0, "default_low_input_latency": 0.01, "default_high_input_latency": 0.02,
     "default_low_output_latency": 0.015, "default_high_output_latency": 0.025},
    {"name": "Owner's AirPods Pro", "index": 2, "hostapi": 0, "max_input_channels": 1, "max_output_channels": 2,
     "default_samplerate": 24000.0, "default_low_input_latency": 0.1, "default_high_input_latency": 0.12,
     "default_low_output_latency": 0.15, "default_high_output_latency": 0.2},
]


class _Default:
    def __init__(self):
        self.device = [0, 1]
        self.samplerate = None


class FakeSoundDevice:
    """The subset of the sounddevice API the kit uses."""
    CallbackStop = CallbackStop
    CallbackAbort = CallbackAbort
    PortAudioError = PortAudioError

    def __init__(self, delay_s: float = 0.0237, atten: float = 0.3, noise_db: float = -60.0, rates=(48000, 44100),
                 devices=None, default=(0, 1), silent_mic: bool = False, seed: int = 0):
        self.delay_s, self.atten, self.noise = delay_s, atten, 10 ** (noise_db / 20)
        self.rates = set(int(r) for r in rates)
        self.devices = [dict(d) for d in (devices or DEVICES)]
        self.default = _Default()
        self.default.device = list(default)
        self.silent_mic = silent_mic
        self.rng = np.random.default_rng(seed)
        self.streams_opened = 0
        self.__version__ = "fake"

    # ---- queries ----
    def query_devices(self, device=None, kind=None):
        if kind is not None:
            idx = self.default.device[0 if kind == "input" else 1]
            return dict(self.devices[idx])
        if device is not None:
            return dict(self.devices[self._idx(device)])
        return [dict(d) for d in self.devices]

    def query_hostapis(self, index=None):
        h = {"name": "Fake Loopback", "devices": list(range(len(self.devices))), "default_input_device": 0,
             "default_output_device": 1}
        return h if index is not None else [h]

    def _idx(self, device):
        if isinstance(device, int):
            return device
        for d in self.devices:
            if d["name"] == device:
                return d["index"]
        raise PortAudioError(f"no device {device!r}")

    def check_input_settings(self, device=None, channels=None, dtype=None, samplerate=None, **_):
        d = self.devices[self._idx(device if device is not None else self.default.device[0])]
        if d["max_input_channels"] < (channels or 1):
            raise PortAudioError("Invalid number of channels")
        if samplerate and int(samplerate) not in self.rates | {int(d["default_samplerate"])}:
            raise PortAudioError("Invalid sample rate")

    def check_output_settings(self, device=None, channels=None, dtype=None, samplerate=None, **_):
        d = self.devices[self._idx(device if device is not None else self.default.device[1])]
        if d["max_output_channels"] < (channels or 1):
            raise PortAudioError("Invalid number of channels")
        if samplerate and int(samplerate) not in self.rates | {int(d["default_samplerate"])}:
            raise PortAudioError("Invalid sample rate")

    # ---- streams ----
    def Stream(self, **kw):
        self.streams_opened += 1
        return FakeStream(self, **kw)

    def InputStream(self, **kw):
        self.streams_opened += 1
        return FakeInputStream(self, **kw)


class FakeStream:
    def __init__(self, sd: FakeSoundDevice, samplerate=48000, blocksize=0, device=None, channels=(1, 2),
                 dtype="float32", callback=None, finished_callback=None, latency=None, **_):
        self.sd, self.samplerate = sd, float(samplerate)
        self.blocksize = blocksize or 512
        self.channels = channels if isinstance(channels, (tuple, list)) else (channels, channels)
        self.callback, self.finished_callback = callback, finished_callback
        self.latency = (0.01, 0.02)
        # the round trip is delay_s in total: one block (the mic hears a block after it is played) + the low-pass's
        # 1 sample + the delay line
        self.delay = max(0, int(round(sd.delay_s * self.samplerate)) - self.blocksize - 1)
        self.line = np.zeros(self.delay, np.float32)          # samples in flight speaker -> mic
        self.hist = np.zeros(2, np.float32)
        self.active = False
        self._stop = threading.Event()
        self._thread = None
        self.frames = 0

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *a):
        self.close()

    def start(self):
        self.active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _mic(self, played: np.ndarray) -> np.ndarray:
        """What the mic hears: the delay line, a one-pole low-pass, attenuation, noise."""
        sd = self.sd
        both = np.concatenate([self.line, played])
        out, self.line = both[: len(played)], both[len(played):]
        x = np.concatenate([self.hist, out])                  # 3-tap low-pass [.25 .5 .25] (1 sample of delay)
        y = (0.25 * x[:-2] + 0.5 * x[1:-1] + 0.25 * x[2:]).astype(np.float32)
        self.hist = x[-2:]
        if sd.silent_mic:
            return np.zeros_like(y)
        return (y * sd.atten + sd.rng.normal(0, sd.noise, len(y))).astype(np.float32)

    def _run(self):
        n_in, n_out = self.channels
        indata = np.zeros((self.blocksize, n_in), np.float32)
        try:
            while not self._stop.is_set():
                outdata = np.zeros((self.blocksize, n_out), np.float32)
                t = self.frames / self.samplerate
                tm = types.SimpleNamespace(inputBufferAdcTime=t - 0.01, outputBufferDacTime=t + 0.02, currentTime=t)
                try:
                    self.callback(indata.copy(), outdata, self.blocksize, tm, _Status())
                except CallbackStop:
                    break
                except CallbackAbort:
                    break
                indata = self._mic(outdata[:, 0].copy())[:, None].repeat(n_in, axis=1)
                self.frames += self.blocksize
        finally:
            self.active = False
            if self.finished_callback:
                self.finished_callback()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()

    abort = stop

    def close(self):
        self.stop()


class FakeInputStream(FakeStream):
    """A short read: the fake mic hears room noise (or digital silence when `silent_mic`, i.e. permission denied)."""

    def __init__(self, sd, samplerate=48000, device=None, channels=1, dtype="float32", **kw):
        super().__init__(sd, samplerate=samplerate, device=device, channels=(channels, 0), dtype=dtype, **kw)

    def start(self):
        self.active = True

    def read(self, frames):
        x = np.zeros((frames, self.channels[0]), np.float32) if self.sd.silent_mic else \
            self.sd.rng.normal(0, self.sd.noise, (frames, self.channels[0])).astype(np.float32)
        return x, False

    def stop(self):
        self.active = False

    def close(self):
        self.active = False


class _Status:
    input_overflow = output_underflow = False

    def __bool__(self):
        return False

    def __str__(self):
        return ""
