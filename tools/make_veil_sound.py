"""Bake UMBRAL VEIL's sound: SmokeGrenade.mp3 stretched to 14 s.

The source is 6.3 s: 0.5 s of silence (cut, `--start`, or the sound lags the
smoke), the grenade going off (to ~2 s, burst then decay) and a steady hiss
(2 s onward, about -36 dB RMS). The result keeps the burst,
then fresh noise shaped to the steady hiss's spectrum (2.0-5.6 s) until `--length`, so nothing repeats,
and fades the tail down from `--fade-from` so it gets quieter as the smoke
thins. Output: mono 16-bit 48 kHz PCM WAV (the game's sound slot is mono 48 kHz), committed as assets/umbral_veil.wav, so the
deploy never needs ffmpeg or numpy (this script does: ffmpeg decodes the mp3).

    python tools/make_veil_sound.py [--src SmokeGrenade.mp3] [--out assets/umbral_veil.wav]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def decode(path: str, rate: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
                          "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 1).astype(np.float64)


def hiss_spectrum(hiss: np.ndarray, n: int = 4096) -> np.ndarray:
    """Average magnitude spectrum of the steady hiss (Welch: Hann frames, 50 % overlap)."""
    win = np.hanning(n)
    frames = [hiss[i:i + n] * win for i in range(0, len(hiss) - n, n // 2)]
    return np.sqrt(np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in frames], axis=0))


def bake(src: np.ndarray, rate: int, length: float, fade_from: float, start: float = 0.5,
         head_end=2.0, hiss_start=2.0, hiss_end=5.6, xfade=0.8, seed=7) -> np.ndarray:
    """The burst (start..head_end), then a hiss that cannot repeat: fresh random
    noise shaped to the recorded hiss's spectrum (one long FFT, so no seams),
    with a slow, irregular swell of about +-1.5 dB so it does not sound static,
    level-matched to the hiss. (Reusing the 3.6 s of recorded hiss, as a loop or
    as grains, always left audible repetition.)"""
    s = lambda t: int(round(t * rate))
    mono = src[:, 0]
    head = mono[s(start):s(head_end)]
    hiss = mono[s(hiss_start):s(hiss_end)]
    rng = np.random.default_rng(seed)
    n = s(length) - len(head) + s(xfade)
    shape = hiss_spectrum(hiss)
    spec = np.fft.rfft(rng.standard_normal(n))
    spec *= np.interp(np.linspace(0, 1, len(spec)), np.linspace(0, 1, len(shape)), shape)
    tail = np.fft.irfft(spec, n)
    # slow swell: smoothed random walk, ~0.5-1 s features, +-1.5 dB
    knots = rng.standard_normal(int(length * 1.5) + 4)
    swell = np.interp(np.linspace(0, len(knots) - 1, n), np.arange(len(knots)), knots)
    k = np.hanning(s(0.6)); swell = np.convolve(swell, k / k.sum(), mode="same")
    tail *= 10 ** (1.5 * swell / max(np.abs(swell).max(), 1e-9) / 20)
    tail *= np.sqrt((hiss ** 2).mean() / (tail ** 2).mean())
    # equal-power crossfade from the burst's decay into the hiss
    x = s(xfade)
    ramp = np.linspace(0.0, np.pi / 2, x)
    out = np.concatenate([head[:-x], head[-x:] * np.cos(ramp) + tail[:x] * np.sin(ramp), tail[x:]])
    out = out[:s(length)]
    # quieter towards the end: smooth fade from fade_from to silence at length
    t = np.arange(len(out)) / rate
    k = np.clip((t - fade_from) / (length - fade_from), 0.0, 1.0)
    out = out * np.cos(k * np.pi / 2) ** 2
    peak = np.abs(out).max()
    if peak > 1.0:
        out /= peak
    return out[:, None]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=os.path.join(ROOT, "SmokeGrenade.mp3"))
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", "umbral_veil.wav"))
    ap.add_argument("--length", type=float, default=14.0)
    ap.add_argument("--fade-from", type=float, default=5.0, help="seconds in where the tail starts getting quieter")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--start", type=float, default=0.5, help="seconds of the mp3's leading silence to cut")
    args = ap.parse_args(argv[1:])

    pcm = bake(decode(args.src, args.rate), args.rate, args.length, args.fade_from, args.start)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(args.rate)
        w.writeframes((pcm * 32767).round().astype("<i2").tobytes())
    print(f"wrote {args.out} ({args.length} s at {args.rate} Hz, fades from {args.fade_from} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
