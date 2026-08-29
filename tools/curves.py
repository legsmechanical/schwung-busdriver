#!/usr/bin/env python3
"""curves.py — transfer curves for the shaping stages, with hysteresis reported.

The swept probe visits every input level twice (amplitude ramps up, then down).
A memoryless stage gives the same output both times, so the per-bin spread is
near zero; a stage with memory gives a BAND, and the width is the finding — it
says a static curve is the wrong model, rather than returning a curve that is
quietly an average of two behaviours.

⚠ The device is AC-coupled and saturates even at Drive 0, so the curve here is
the WHOLE device at that setting, not one isolated stage. Subtracting the neutral
curve is not valid for a nonlinearity; the neutral curve is reported alongside so
the extra contribution is visible.

Usage: tools/curves.py <renders> <project> [--cells substr] [--dump name]
"""
import argparse, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db
from analyse import read_wav, resolve_probe

LAG, POL = 58, -1.0
NB = 201


def curve(x, y):
    edges = np.linspace(-1.0, 1.0, NB + 1)
    idx = np.clip(np.digitize(x, edges) - 1, 0, NB - 1)
    cnt = np.bincount(idx, minlength=NB)
    sm = np.bincount(idx, weights=y, minlength=NB)
    sq = np.bincount(idx, weights=y * y, minlength=NB)
    ok = cnt > 50
    c = 0.5 * (edges[:-1] + edges[1:])
    mean = np.zeros(NB); mean[ok] = sm[ok] / cnt[ok]
    sd = np.zeros(NB)
    sd[ok] = np.sqrt(np.maximum(sq[ok] / cnt[ok] - mean[ok] ** 2, 0))
    return c, mean, sd, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('renders'); ap.add_argument('project')
    ap.add_argument('--cells', default='drive')
    ap.add_argument('--dump', default=None)
    a = ap.parse_args()
    probe_path, man = resolve_probe(a.renders, a.project)
    probe = read_wav(probe_path)['l']
    off = man['suite']['offsets']
    cells = {t['name']: t for t in man['tracks']}
    files = {}
    for f in sorted(os.listdir(a.renders)):
        if f.endswith('.wav'):
            for n in cells:
                if f.endswith(n + '.wav'):
                    files[n] = os.path.join(a.renders, f)

    x = seg(probe, off, 'swept')
    names = [n for n in sorted(cells) if (a.cells in n or n.endswith('neutral'))
             and not n.endswith('dry')]
    LEVELS = [0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0]
    print('Transfer curve: output at each input level (input positive half).')
    print('"hyst" is the mean per-bin spread relative to the curve — a memoryless')
    print('stage is near zero; a large value means a static curve is the wrong model.\n')
    print(f'{"cell":<22s}' + ''.join(f'{v:>8.2f}' for v in LEVELS) + f'{"hyst":>9s}')
    print('-' * (22 + 8 * len(LEVELS) + 9))
    for n in names:
        w = read_wav(files[n])['l']
        y = POL * seg(w, off, 'swept', LAG)
        m = min(len(x), len(y))
        c, mean, sd, ok = curve(x[:m], y[:m])
        vals = []
        for v in LEVELS:
            k = int(np.argmin(np.abs(c - v)))
            vals.append(mean[k] if ok[k] else float('nan'))
        h = float(np.mean(sd[ok] / (np.abs(mean[ok]) + 1e-3)))
        print(f'{n[3:]:<22s}' + ''.join(f'{v:>8.4f}' for v in vals) + f'{h:>9.3f}')
        if a.dump and a.dump in n:
            out = os.path.join(a.renders, n + '.curve.tsv')
            with open(out, 'w') as fh:
                fh.write(f'# {n}  probe sha256 {man["probe"]["sha256"]}\\n')
                fh.write('# in\\tout\\tsd\\n')
                for k in np.flatnonzero(ok):
                    fh.write(f'{c[k]:.5f}\\t{mean[k]:.7f}\\t{sd[k]:.7f}\\n')
            print(f'   -> {out}')


if __name__ == '__main__':
    main()
