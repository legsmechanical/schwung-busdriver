#!/usr/bin/env python3
"""harmonics.py — harmonic-order structure from the Farina deconvolution.

The reason to sweep rather than ladder tones: after deconvolution, harmonic
order N lands L*ln(N) seconds AHEAD of the linear response, separated in time.
So each order can be windowed and measured on its own, from the same render that
gives the linear filter.

That makes it the right tool for two questions at once:
  * what shape of distortion each Drive type makes (even vs odd orders)
  * where the compressor sits relative to the clipper — a compressor UPSTREAM of
    a clipper reduces what the clipper sees, so it must REDUCE the harmonics

Usage: tools/harmonics.py <renders> <project> [--cells substr]
"""
import argparse, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db
from analyse import read_wav, resolve_probe
from filters import inverse_filter, deconvolve

F0, F1, SWEEP_S = 20.0, 20000.0, 10.0
L = SWEEP_S / math.log(F1 / F0)
LAG, POL = 55, 1.0
ORDERS = (2, 3, 4, 5)


def order_levels(full, peak, half=2048):
    """Energy in a window centred on each harmonic order's arrival."""
    out = {}
    lin = full[max(0, peak - half):peak + half]
    out[1] = db(np.sqrt((lin * lin).mean()))
    for n in ORDERS:
        d = int(L * math.log(n) * SR)
        c = peak - d
        if c - half < 0:
            out[n] = None
            continue
        w = full[c - half:c + half]
        out[n] = db(np.sqrt((w * w).mean()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('renders'); ap.add_argument('project')
    ap.add_argument('--cells', default='')
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
    x = seg(probe, off, 'sweep')
    names = [n for n in sorted(cells) if a.cells in n and not n.endswith('dry')]

    print(f'Harmonic orders relative to the linear response (dB). '
          f'L={L:.4f}s, so H2 arrives {L*math.log(2):.3f}s early.\n')
    print(f'{"cell":<24s} {"H2":>8s} {"H3":>8s} {"H4":>8s} {"H5":>8s}   '
          f'{"even-odd":>9s}')
    print('-' * 70)
    for n in names:
        w = read_wav(files[n])['l']
        y = POL * seg(w, off, 'sweep', LAG)
        m = min(len(x), len(y))
        full, peak = deconvolve(x[:m], y[:m])
        lv = order_levels(full, peak)
        rel = {k: (None if lv[k] is None else lv[k] - lv[1]) for k in lv}
        ev = [rel[k] for k in (2, 4) if rel.get(k) is not None]
        od = [rel[k] for k in (3, 5) if rel.get(k) is not None]
        bal = (np.mean(ev) - np.mean(od)) if ev and od else float('nan')
        print(f'{n[3:]:<24s} ' + ' '.join(
            f'{rel[k]:>8.1f}' if rel.get(k) is not None else f'{"—":>8s}'
            for k in ORDERS) + f'   {bal:>+9.1f}')


if __name__ == '__main__':
    main()
