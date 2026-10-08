"""Bake UMBRAL VEIL's sound: SmokeGrenade.mp3 stretched to 14 s.

The source is 6.3 s: the grenade going off (first ~2 s, burst then decay) and
a steady hiss (2 s onward, about -36 dB RMS). The result keeps the first 2 s,
then tiles the hiss (2.0-6.2 s) with equal-power crossfades until `--length`,
and fades the tail down from `--fade-from` so it gets quieter as the smoke
thins. Output: 16-bit PCM WAV, committed as assets/umbral_veil.wav, so the
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
                          "-f", "f32le", "-ac", "2", "-ar", str(rate), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).astype(np.float64)


def bake(src: np.ndarray, rate: int, length: float, fade_from: float,
         head_end=2.0, loop_start=2.0, loop_end=6.2, xfade=0.6) -> np.ndarray:
    s = lambda t: int(round(t * rate))
    out = src[:s(head_end)].copy()
    loop = src[s(loop_start):s(loop_end)]
    x = s(xfade)
    ramp = np.linspace(0.0, np.pi / 2, x)[:, None]
    fade_in, fade_out = np.sin(ramp), np.cos(ramp)          # equal power
    first = True
    while len(out) < s(length):
        if first:                                            # head flows straight on
            out = np.concatenate([out, loop])
            first = False
        else:
            out[-x:] = out[-x:] * fade_out + loop[:x] * fade_in
            out = np.concatenate([out, loop[x:]])
    out = out[:s(length)]
    # quieter towards the end: smooth fade from fade_from to silence at length
    t = np.arange(len(out)) / rate
    k = np.clip((t - fade_from) / (length - fade_from), 0.0, 1.0)
    out *= (np.cos(k * np.pi / 2) ** 2)[:, None]
    peak = np.abs(out).max()
    if peak > 1.0:
        out /= peak
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=os.path.join(ROOT, "SmokeGrenade.mp3"))
    ap.add_argument("--out", default=os.path.join(ROOT, "assets", "umbral_veil.wav"))
    ap.add_argument("--length", type=float, default=14.0)
    ap.add_argument("--fade-from", type=float, default=5.0, help="seconds in where the tail starts getting quieter")
    ap.add_argument("--rate", type=int, default=48000)
    args = ap.parse_args(argv[1:])

    pcm = bake(decode(args.src, args.rate), args.rate, args.length, args.fade_from)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(args.rate)
        w.writeframes((pcm * 32767).round().astype("<i2").tobytes())
    print(f"wrote {args.out} ({args.length} s at {args.rate} Hz, fades from {args.fade_from} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
