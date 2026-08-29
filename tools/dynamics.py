#!/usr/bin/env python3
"""dynamics.py — the compressor's static curve and time constants.

Usage: tools/dynamics.py <renders> <project>
"""
import os, sys, math, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db, align_envelope, envelope
from analyse import read_wav, resolve_probe

LEVELS = (-60, -48, -36, -30, -24, -18, -12, -6, -3, 0)
ON, OFF = 0.5, 0.5


def burst_curve(x, y):
    """Level in vs level out over the STEADY part of each burst.

    Skips the first 150 ms so the detector has settled, and stops 20 ms before
    the edge. The silence between bursts lets it fully release, so each level is
    independent instead of riding the previous one's gain reduction."""
    rows = []
    step = int((ON + OFF) * SR)
    for i, lvl in enumerate(LEVELS):
        s = i * step + int(0.15 * SR)
        e = i * step + int(ON * SR) - int(0.02 * SR)
        if e > min(len(x), len(y)):
            break
        xi, yi = x[s:e], y[s:e]
        rows.append((lvl,
                     db(np.sqrt((xi * xi).mean())),
                     db(np.sqrt((yi * yi).mean()))))
    return rows


def step_times(x, y):
    """Attack and release from the level steps.

    The probe is a steady 200 Hz tone stepping -40 -> -6 -> -40 dB, three times.
    ATTACK is read from how fast the OUTPUT level falls after a step up (gain
    reduction engaging); RELEASE from how fast it recovers after a step down.
    Reported as the time to reach 63% (one time constant) of the total move."""
    hold = int(1.0 * SR)
    env_y = envelope(y, win=256)
    env_x = envelope(x, win=256)
    out = {'attack_ms': [], 'release_ms': []}
    # step boundaries: lo,hi,lo repeated -> transitions at 1s, 2s, 3s, 4s...
    for rep in range(3):
        base = rep * 3 * hold
        for kind, t0 in (('attack_ms', base + hold), ('release_ms', base + 2 * hold)):
            a, b = t0, t0 + int(0.6 * SR)
            if b > len(env_y):
                continue
            # gain = out/in, so the input step itself divides out
            g = env_y[a:b] / (env_x[a:b] + 1e-12)
            g0 = float(np.median(g[:64]))
            g1 = float(np.median(g[-2000:]))
            if abs(db(abs(g1)) - db(abs(g0))) < 0.5:
                continue
            target = g0 + 0.632 * (g1 - g0)
            idx = np.flatnonzero((g - target) * np.sign(g1 - g0) >= 0)
            if len(idx):
                out[kind].append(idx[0] / SR * 1000.0)
    return out


def main():
    renders, project = sys.argv[1], sys.argv[2]
    probe_path, man = resolve_probe(renders, project)
    probe = read_wav(probe_path)['l']
    off = man['suite']['offsets']
    cells = {t['name']: t for t in man['tracks']}
    files = {}
    for f in sorted(os.listdir(renders)):
        if f.endswith('.wav'):
            for n in cells:
                if f.endswith(n + '.wav'):
                    files[n] = os.path.join(renders, f)
    dryname = [n for n in cells if n.endswith('dry')][0]
    dry = read_wav(files[dryname])['l']
    LAG, POL = 58, -1.0

    want = [n for n in sorted(cells) if any(k in n for k in
            ('neutral', 'comp_on', 'topo_hard'))]

    print('STATIC CURVE — level in vs level out, per burst (dB)\n')
    hdr = 'nominal  ' + ''.join(f'{n[3:][:14]:>16s}' for n in want)
    print(hdr); print('-' * len(hdr))
    curves = {}
    for n in want:
        w = read_wav(files[n])['l']
        curves[n] = burst_curve(seg(probe, off, 'bursts'),
                                POL * seg(w, off, 'bursts', LAG))
    ref = curves[want[0]]
    for i in range(len(ref)):
        line = f'{ref[i][0]:>6d}   '
        for n in want:
            line += f'{curves[n][i][2] - curves[n][i][1]:>+15.2f} '
        print(line)

    print('\nGAIN REDUCTION relative to the same cell at -60 dBFS')
    print('(a compressor shows increasing GR with level; a fixed gain shows none)\n')
    for n in want:
        c = curves[n]
        base = c[0][2] - c[0][1]
        gr = [f'{(r[2]-r[1])-base:+6.2f}' for r in c]
        print(f'  {n[3:]:<20s} ' + ' '.join(gr))

    print('\nTIME CONSTANTS from the level steps (63% of the move)\n')
    for n in want:
        w = read_wav(files[n])['l']
        t = step_times(seg(probe, off, 'steps'), POL * seg(w, off, 'steps', LAG))
        a = f"{np.mean(t['attack_ms']):.1f}" if t['attack_ms'] else '—'
        r = f"{np.mean(t['release_ms']):.1f}" if t['release_ms'] else '—'
        print(f'  {n[3:]:<20s} attack {a:>7s} ms   release {r:>7s} ms   '
              f'(n={len(t["attack_ms"])}/{len(t["release_ms"])})')


if __name__ == '__main__':
    main()
