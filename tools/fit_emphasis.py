#!/usr/bin/env python3
"""fit_emphasis.py — fit the pre-emphasis against the FOUR-CARRIER data.

§35 measured the same amplitude sweep at 100 / 300 / 1k / 3k Hz and found the
fold law is the same shape offset by ~5 dB, with the high carriers hotter. That
is the data the shelf has to reproduce, and it is training data — campaign2, not
the validation presets.

Objective: H3 - H1 versus input amplitude, at all four carriers at once. A shelf
that gets the frequency spread right will track all four; one that is merely
tuned to a single number will not.

Usage: tools/fit_emphasis.py
"""
import os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import read_wav, resolve_probe
from segments import seg, db

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, '..', 'build', 'render')
R = os.path.join(HERE, '..', 'rig', 'renders', 'campaign2')
P = os.path.join(HERE, '..', 'rig', 'sets', 'campaign2 Project')
CARRIERS = [('sw100', 100.0), ('sw300', 300.0), ('sw1k', 1000.0), ('sw3k', 3000.0)]
CELLS = [('08_soft_0.75', 0.75, 0), ('10_soft_1.0', 1.0, 0)]
SR = 44100

probe_path, man = resolve_probe(R, P)
off = man['suite']['offsets']
tmp = tempfile.mkdtemp()


def track(y, x, carrier, win=8192, hop=4096):
    rows = []
    hann = np.hanning(win)
    m = min(len(x), len(y))
    for s in range(0, m - win, hop):
        if s > m // 2:
            break
        amp = float(np.abs(x[s:s+win]).max())
        if amp < 0.15:
            continue
        Y = np.fft.rfft(y[s:s+win] * hann)
        k1 = int(round(carrier * win / SR)); k3 = int(round(3 * carrier * win / SR))
        f1 = float(np.abs(Y[k1-3:k1+4]).max()); f3 = float(np.abs(Y[k3-3:k3+4]).max())
        rows.append((amp, db(f3 / (f1 + 1e-30))))
    return rows


live = {}
for cell, drv, typ in CELLS:
    w = read_wav(os.path.join(R, f'campaign2 {cell}.wav'))['l']
    for segn, hz in CARRIERS:
        live[(cell, segn)] = track(seg(w, off, segn, 192), seg(probe_path and read_wav(probe_path)['l'], off, segn), hz)

probe = read_wav(probe_path)['l']


def err(fc, gdb):
    tot, n = 0.0, 0
    for cell, drv, typ in CELLS:
        out = os.path.join(tmp, f'{cell}_{fc:.0f}_{gdb:.2f}.wav')
        a = [RENDER, probe_path, out, f'drive={drv}', f'drive_type={typ}',
             f'_pe_fc={fc}', f'_pe_db={gdb}']
        if subprocess.run(a, capture_output=True).returncode != 0:
            return 1e6
        y = read_wav(out)['l']
        for segn, hz in CARRIERS:
            mine = track(seg(y, off, segn, 0), seg(probe, off, segn), hz)
            L = live[(cell, segn)]
            k = min(len(mine), len(L))
            if k < 3:
                continue
            d = np.array([mine[i][1] - L[i][1] for i in range(k)])
            tot += float((d * d).sum()); n += k
    return float(np.sqrt(tot / max(n, 1)))


print('Coarse grid over the shelf, fitted to all four carriers at once.\n')
print(f'{"fc Hz":>8s}' + ''.join(f'{g:>9.1f}dB' for g in (0.0, 1.5, 2.5, 3.5, 5.0)))
best = None
for fc in (200, 400, 600, 1000, 1600):
    row = []
    for gdb in (0.0, 1.5, 2.5, 3.5, 5.0):
        e = err(fc, gdb)
        row.append(e)
        if best is None or e < best[0]:
            best = (e, fc, gdb)
    print(f'{fc:>8d}' + ''.join(f'{v:>11.3f}' for v in row))
print(f'\nbest: fc {best[1]} Hz, boost {best[2]} dB, error {best[0]:.3f} dB')
print(f'(no emphasis at all = {err(600, 0.0):.3f} dB)')
