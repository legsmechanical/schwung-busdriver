#!/usr/bin/env python3
"""transients.py — what the Transients control actually does, from the hits probe.

The question the manual raises: it says positive Transients "adds attack AND
sustain". Our own module split that into two orthogonal controls because moving
both together was treated as a defect. This measures which is true.

Onset and tail are measured separately, per hit, with a causal envelope — a
centred one leaks across the onset and flatters the result.

Usage: tools/transients.py <renders> <project>
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db
from analyse import read_wav, resolve_probe

LAG, POL = 58, -1.0
BPM, PEAK = 120.0, 0.25


def causal_env(x, win=64):
    c = np.cumsum(np.abs(x))
    e = np.empty_like(c)
    e[:win] = c[:win] / np.arange(1, win + 1)
    e[win:] = (c[win:] - c[:-win]) / win
    return e


def hit_metrics(x, y):
    """Per hit: peak of the onset window, and RMS of the tail window."""
    step = int(SR * 60.0 / BPM / 2)          # matches probes.hits()
    n = min(len(x), len(y))
    rows = []
    for s in range(0, n - step, step):
        on_a, on_b = s, s + int(0.010 * SR)          # first 10 ms
        tl_a, tl_b = s + int(0.10 * SR), s + int(0.22 * SR)
        if tl_b > n:
            break
        rows.append((
            db(np.abs(x[on_a:on_b]).max()), db(np.abs(y[on_a:on_b]).max()),
            db(np.sqrt((x[tl_a:tl_b] ** 2).mean())),
            db(np.sqrt((y[tl_a:tl_b] ** 2).mean()))))
    return rows


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

    x = seg(probe, off, 'hits')
    want = [n for n in sorted(cells) if 'transient' in n or n.endswith('neutral')]

    base = None
    print('Per-hit ONSET and TAIL change vs the device at neutral (dB).')
    print('If the control moves both in the SAME direction it is a broadband gain;')
    print('opposing or independent movement is real transient shaping.\n')
    print(f'{"cell":<22s} {"onset":>8s} {"tail":>8s} {"onset-tail":>11s}')
    print('-' * 54)
    for n in want:
        w = read_wav(files[n])['l']
        y = POL * seg(w, off, 'hits', LAG)
        m = min(len(x), len(y))
        rows = hit_metrics(x[:m], y[:m])
        on = float(np.mean([r[1] - r[0] for r in rows]))
        tl = float(np.mean([r[3] - r[2] for r in rows]))
        if n.endswith('neutral'):
            base = (on, tl)
        d_on, d_tl = on - base[0], tl - base[1]
        print(f'{n[3:]:<22s} {d_on:>+8.2f} {d_tl:>+8.2f} {d_on-d_tl:>+11.2f}'
              + ('   <- reference' if n.endswith('neutral') else ''))


if __name__ == '__main__':
    main()
