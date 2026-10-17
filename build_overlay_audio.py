"""Build the fixed 10-second cue locally from the two supplied recordings.

Usage: python build_overlay_audio.py --ffmpeg PATH --first PATH --second PATH
The source recordings are never uploaded by this script.
"""
import argparse
from array import array
import math
from pathlib import Path
import random
import subprocess
import tempfile
import wave

RATE = 48000
DURATION = 10
IMPACT = 6.2


def read_clip(ffmpeg, source, destination):
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', source, '-ar', str(RATE),
                    '-ac', '1', '-c:a', 'pcm_s16le', str(destination)], check=True)
    with wave.open(str(destination)) as stream:
        pcm = array('h', stream.readframes(stream.getnframes()))
    peak = max(abs(v) for v in pcm) or 1
    return [v / peak for v in pcm]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--first', required=True)
    parser.add_argument('--second', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        first = read_clip(args.ffmpeg, args.first, folder / 'first.wav')
        second = read_clip(args.ffmpeg, args.second, folder / 'second.wav')
        cue1 = .25
        cue2 = IMPACT - len(second) / RATE - .055
        if cue1 + len(first) / RATE >= cue2 or cue2 < 0:
            raise ValueError('The clips do not fit the ten-second timeline without overlap.')
        rng = random.Random(73)
        result = array('h')
        phase = 0
        rumble = 0
        phase2 = 0
        for i in range(RATE * DURATION):
            t = i / RATE
            value = 0.0
            if t < IMPACT:
                # Mechanical civil-defence / nuclear siren: slow winding dual rotors.
                pitch = 245 + 235 * (.5 - .5 * math.cos(2 * math.pi * t / 3.5))
                phase += 2 * math.pi * pitch / RATE
                phase2 += 2 * math.pi * pitch * 1.205 / RATE
                duck = .16 if cue1 <= t < cue1 + len(first)/RATE or t >= cue2 else .29
                fade = min(1, t / .20, (IMPACT-t) / .09)
                rotor = math.sin(phase) + .48*math.sin(phase*2) + .23*math.sin(phase*3) + .10*math.sin(phase*5)
                rotor2 = math.sin(phase2) + .35*math.sin(phase2*2) + .18*math.sin(phase2*3)
                horn = math.tanh(1.4*(rotor + .6*rotor2))
                value += duck * fade * horn * (.90 + .10*math.sin(2*math.pi*t*19))
                # Retain the chaotic engine/radio layer, below the long warning horn.
                value += .045 * fade * math.tanh(3 * math.sin(2 * math.pi * (55*t + 9*t*t)))
                value += .018 * fade * rng.uniform(-1, 1) * (.3 + .7 * abs(math.sin(t*38)))
            for samples, begin, gain in ((first, cue1, .78), (second, cue2, .82)):
                index = i - round(begin * RATE)
                if 0 <= index < len(samples):
                    edge = min(1, index/240, (len(samples)-1-index)/240)
                    value += samples[index] * gain * edge
            # Short slapback echoes keep the voices chaotic without hiding the words.
            for samples, begin in ((first, cue1), (second, cue2)):
                for delay, gain in ((.105,.16),(.21,.075)):
                    index = i - round((begin + delay) * RATE)
                    if 0 <= index < len(samples) and t < IMPACT:
                        value += samples[index] * gain
            if t >= IMPACT:
                dt = t - IMPACT
                attack = min(1, dt / .008)
                rumble = .85 * rumble + .15 * rng.uniform(-1, 1)
                raw = (1.8 * rumble * math.exp(-dt * 1.7)
                       + .9 * math.sin(2 * math.pi * (66*dt - 5*dt*dt)) * math.exp(-dt*2.1)
                       + .65 * rng.uniform(-1, 1) * math.exp(-dt*5))
                # Deliberately crushed impact, with two quieter debris/echo bursts.
                value += attack * .83 * math.tanh(raw * 6) * math.exp(-dt*.5)
                for delay in (.19,.42):
                    echo = dt-delay
                    if echo >= 0:
                        value += .11 * math.tanh(rng.uniform(-1,1)*5) * math.exp(-echo*9)
            # Smooth limiter and a final fade; never exceed PCM headroom.
            value = .94 * math.tanh(value * 1.1) * min(1, (DURATION-t)/.08)
            result.append(round(value * 32767))
        wav = root / 'preview' / 'pepazo-10s.wav'
        wav.parent.mkdir(exist_ok=True)
        with wave.open(str(wav), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE)
            output.writeframes(result.tobytes())
        subprocess.run([args.ffmpeg, '-v', 'error', '-y', '-i', str(wav),
                        '-c:a', 'libmp3lame', '-b:a', '192k',
                        str(root / 'overlay-pepazo.mp3')], check=True)
        print(f'10.000 s: siren 0–{IMPACT:.3f}; first {cue1:.3f}–{cue1+len(first)/RATE:.3f}; '
              f'second {cue2:.3f}–{cue2+len(second)/RATE:.3f}; explosion {IMPACT:.3f}–10.000.')


if __name__ == '__main__':
    main()
