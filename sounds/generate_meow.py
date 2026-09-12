#!/usr/bin/env python3
"""
Generates sounds/meow.wav: a small, stdlib-only synthesized "meow"
placeholder (pitch sweep + light vibrato + noise-burst onset). Not a
real recording - swap in your own meow.wav/ogg via config.yaml's
sound_file whenever you like. Re-run this after editing the parameters
below if you want to tweak the placeholder itself.
"""
import math
import random
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DURATION = 0.55
OUT_PATH = Path(__file__).parent / "meow.wav"


def pitch_at(t: float) -> float:
    # Rises quickly then falls, like "mrEEow" - roughly the classic meow contour.
    rise_end = DURATION * 0.25
    if t < rise_end:
        frac = t / rise_end
        return 320 + frac * (950 - 320)
    frac = (t - rise_end) / (DURATION - rise_end)
    return 950 + frac * (260 - 950)


def amplitude_at(t: float) -> float:
    attack = 0.04
    if t < attack:
        return t / attack
    # exponential-ish decay after attack
    decay_t = t - attack
    return math.exp(-2.2 * decay_t / DURATION) * (1 - 0.15 * decay_t / DURATION)


def generate_samples():
    n = int(SAMPLE_RATE * DURATION)
    phase = 0.0
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        f = pitch_at(t)
        vibrato = 1 + 0.02 * math.sin(2 * math.pi * 7 * t)
        phase += 2 * math.pi * f * vibrato / SAMPLE_RATE
        fundamental = math.sin(phase)
        second_harmonic = 0.25 * math.sin(2 * phase)
        breathiness = random.uniform(-1, 1) * 0.05 * math.exp(-t * 12)
        value = amplitude_at(t) * (fundamental + second_harmonic + breathiness)
        samples.append(max(-1.0, min(1.0, value)))
    return samples


def write_wav(samples, path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        frames = bytearray()
        for s in samples:
            i16 = int(s * 32767)
            frames += i16.to_bytes(2, byteorder="little", signed=True)
        wav.writeframes(bytes(frames))


if __name__ == "__main__":
    write_wav(generate_samples(), OUT_PATH)
    print(f"wrote {OUT_PATH} ({DURATION:.2f}s @ {SAMPLE_RATE}Hz)")
