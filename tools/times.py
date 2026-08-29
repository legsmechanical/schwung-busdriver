#!/usr/bin/env python3
"""times.py — compressor attack/release from the 2 kHz step probe.

Two disciplines are built in because both already produced wrong answers here:

1. CAUSAL envelope. `np.convolve(..., 'same')` is centred and leaks post-step
   samples backward across the step, which makes a slow release read as
   instantaneous.
2. WINDOW SWEEP. Every result is reported across several smoothing windows. If
   the answer moves with the window, the window IS the answer — a memoryless
   saturator once read 3.9 ms this way, which was purely the window.

Usage: tools/times.py <renders> <project>
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db
from analyse import read_wav, resolve_probe

POL = 1.0


def causal_env(x, win):
    c = np.cumsum(np.abs(x))
    e = np.empty_like(c)
    e[:win] = c[:win] / np.arange(1, win + 1)
    e[win:] = (c[win:] - c[:-win]) / win
    return e


def t63(x, y, which, win, hold=1.0):
    """Time to 63% of the gain move after a level step."""
    ex, ey = causal_env(x, win), causal_env(y, win)
    h = int(hold * SR)
    out = []
    for rep in range(3):
        t0 = rep * 3 * h + (h if which == 'attack' else 2 * h)
        a, b = t0 + win, t0 + int(0.9 * SR)
        if b > len(ey):
            continue
        g = ey[a:b] / (ex[a:b] + 1e-12)
        g0, g1 = float(g[0]), float(np.median(g[-3000:]))
        if abs(db(abs(g1)) - db(abs(g0))) < 0.3:
            continue
        tgt = g0 + 0.632 * (g1 - g0)
        idx = np.flatnonzero((g - tgt) * np.sign(g1 - g0) >= 0)
        if len(idx):
            out.append(idx[0] / SR * 1000.0)
    return (float(np.mean(out)), len(out)) if out else (float('nan'), 0)


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

    # lag from the broadband chirp: no carrier, so no period ambiguity
    a = seg(dry, off, 'align2'); s0, n = off['align2']['start'], len(a)
    def lag_of(w):
        best = None
        for L in range(-100, 400):
            if s0 + L < 0 or s0 + L + n > len(w):
                continue
            b = w[s0 + L:s0 + L + n]
            d = float(a @ a)
            g = float(a @ b) / d
            r = g * a - b
            res = float(np.sqrt((r * r).mean()) / (np.sqrt((b * b).mean()) + 1e-30))
            if best is None or res < best[1]:
                best = (L, res, g)
        return best

    x = seg(probe, off, 'steps2k')
    want = [n for n in sorted(cells) if 'comp' in n or n.endswith('neutral')]
    print('Carrier 2 kHz = 0.50 ms/cycle (v1 used 200 Hz = 5.0 ms, above the answer).\n')
    print(f'{"cell":<18s} {"lag":>5s} {"pol":>4s}' +
          ''.join(f'{"w"+str(w):>9s}' for w in (16, 32, 64, 128)) + '   (attack ms)')
    for cell in want:
        w = read_wav(files[cell])['l']
        L, res, g = lag_of(w)
        y = POL * seg(w, off, 'steps2k', L)
        m = min(len(x), len(y))
        row = [t63(x[:m], y[:m], 'attack', ww)[0] for ww in (16, 32, 64, 128)]
        print(f'{cell[3:]:<18s} {L:>5d} {"INV" if g<0 else "+":>4s}' +
              ''.join(f'{v:>9.2f}' for v in row))
    print()
    print(f'{"cell":<18s} {"lag":>5s} {"pol":>4s}' +
          ''.join(f'{"w"+str(w):>9s}' for w in (16, 32, 64, 128)) + '   (release ms)')
    for cell in want:
        w = read_wav(files[cell])['l']
        L, res, g = lag_of(w)
        y = POL * seg(w, off, 'steps2k', L)
        m = min(len(x), len(y))
        row = [t63(x[:m], y[:m], 'release', ww)[0] for ww in (16, 32, 64, 128)]
        print(f'{cell[3:]:<18s} {L:>5d} {"INV" if g<0 else "+":>4s}' +
              ''.join(f'{v:>9.2f}' for v in row))


if __name__ == '__main__':
    main()
