#!/usr/bin/env python3
"""fit_tr_spectral.py — fit the Transients law against Live's own renders of the
transient cells, spectrally.

⚠ NOT against the 22-preset score. Those are the VALIDATION set; fitting to them
would destroy the only independent measure the campaign has. Training data here
is campaign3's transient ladder, which was always training.

⚠ And not against the onset/tail summary either. Fitting that hit both numbers to
0.368 dB rms and made the end-to-end preset score WORSE (5.55 -> 6.40 dB) — two
summary statistics can be matched by a mechanism that is wrong everywhere else.
A spectral objective on the actual rendered audio is much harder to satisfy the
wrong way.

Usage: tools/fit_tr_spectral.py
"""
import os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import read_wav, resolve_probe
from segments import seg, db
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, '..', 'build', 'render')
R = os.path.join(HERE, '..', 'rig', 'renders', 'campaign3')
P = os.path.join(HERE, '..', 'rig', 'sets', 'campaign3 Project')
CELLS = [('27_tr_-0.75', -0.75), ('28_tr_-0.5', -0.5), ('29_tr_-0.25', -0.25),
         ('30_tr_0.25', 0.25), ('31_tr_0.5', 0.5), ('32_tr_0.75', 0.75)]

probe_path, man = resolve_probe(R, P)
off = man['suite']['offsets']
tmp = tempfile.mkdtemp()
CENT = 40.0 * 2 ** (np.arange(0, 27) / 3.0)
CENT = CENT[CENT < 16000]


def thirds(x, n=1 << 14):
    w = np.hanning(min(n, len(x)))
    X = np.abs(np.fft.rfft(x[:len(w)] * w, n))
    f = np.fft.rfftfreq(n, 1 / 44100)
    e = []
    for fc in CENT:
        k = (f >= fc / 2**(1/6)) & (f < fc * 2**(1/6))
        if k.sum() >= 2:
            e.append(np.sqrt((X[k] ** 2).mean()))
    e = np.array(e)
    return 20 * np.log10(np.maximum(e / (e.max() + 1e-30), 1e-12))


live = {}
for name, tr in CELLS:
    w = read_wav(os.path.join(R, f'campaign3 {name}.wav'))['l']
    live[name] = thirds(seg(w, off, 'hits', 190))


def err(p):
    if p[0] <= 0 or p[1] <= 0.5 or p[2] < 0 or p[3] <= 0.2: return 1e6
    if not (0.02 < p[4] < 5.0) or not (50 < p[5] < 2000) or not (0 <= p[6] < 4): return 1e6
    tot = 0.0
    for name, tr in CELLS:
        out = os.path.join(tmp, name + '.wav')
        a = [RENDER, probe_path, out, f'transients={tr}',
             f'_tr_up={p[0]}', f'_tr_upexp={p[1]}', f'_tr_dn={p[2]}',
             f'_tr_dnexp={p[3]}', f'_tr_fast={p[4]}', f'_tr_slow={p[5]}',
             f'_tr_us={p[6]}']
        if subprocess.run(a, capture_output=True).returncode != 0: return 1e6
        mine = thirds(seg(read_wav(out)['l'], off, 'hits', 0))
        tot += float(np.mean((mine - live[name]) ** 2))
    return float(np.sqrt(tot / len(CELLS)))


HAND = [2.75, 3.2, 0.62, 1.0, 0.5, 400.0, 0.5]
ONSET_FIT = [4.320, 2.940, 1.137, 0.942, 0.058, 142.1, 1.244]
print(f'hand-picked          : {err(HAND):.3f} dB')
print(f'onset/tail-fitted    : {err(ONSET_FIT):.3f} dB')
best = None
for p0 in (HAND, ONSET_FIT):
    r = minimize(err, p0, method='Nelder-Mead',
                 options={'maxiter': 400, 'xatol': 1e-3, 'fatol': 1e-3})
    if best is None or r.fun < best.fun: best = r
print(f'spectrally fitted    : {best.fun:.3f} dB')
print('  upScale %.3f  upExp %.3f  dnScale %.3f  dnExp %.3f  fast %.3f  slow %.1f  upSus %.3f'
      % tuple(best.x))
