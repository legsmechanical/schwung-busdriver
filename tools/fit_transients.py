#!/usr/bin/env python3
"""fit_transients.py — fit the Transients law END TO END against the measured
onset/tail table.

Fitted through the whole device, not on the isolated stage: the measurement is
of the whole device, and the saturation downstream of Transients changes what
any boost turns into. Fitting the stage alone would land the right number by the
wrong mechanism.

Targets are the measured onset and tail changes from measurements.md §25 (±1.0,
campaign1) and §41 (the denser ±0.25..±0.75 ladder, campaign3). Both were
measured on the same `hits` probe, and both are envelope magnitudes, which the
§30 polarity retraction left untouched.

Usage: tools/fit_transients.py
"""
import os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import read_wav
from segments import db
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, '..', 'build', 'render')
PROBE = os.path.join(HERE, '..', 'rig', 'probes', 'hits.wav')
SR, BPM = 44100, 120.0

# transients -> (onset dB, tail dB), measured on Ableton's device
TARGETS = [(-1.00, -0.43, -2.46), (-0.75, +0.22, -1.99), (-0.50, +0.26, -1.39),
           (-0.25, +0.20, -0.62), (+0.25, +0.83, +0.62), (+0.50, +1.81, +1.32),
           (+0.75, +2.93, +2.10), (+1.00, +8.02, +3.38)]

tmp = tempfile.mkdtemp()
probe = read_wav(PROBE)['l']
step = int(SR * 60.0 / BPM / 2)


def metrics(path):
    y = read_wav(path)['l']
    n = min(len(probe), len(y))
    on, tl = [], []
    for s in range(0, n - step, step):
        oa, ob = s, s + int(0.010 * SR)
        ta, tb = s + int(0.10 * SR), s + int(0.22 * SR)
        if tb > n:
            break
        on.append(db(np.abs(y[oa:ob]).max()) - db(np.abs(probe[oa:ob]).max()))
        tl.append(db(np.sqrt((y[ta:tb] ** 2).mean())) -
                  db(np.sqrt((probe[ta:tb] ** 2).mean())))
    return float(np.mean(on)), float(np.mean(tl))


def run(tr, p):
    out = os.path.join(tmp, f't{tr:+.2f}.wav')
    args = [RENDER, PROBE, out, f'transients={tr}',
            f'_tr_up={p[0]}', f'_tr_upexp={p[1]}', f'_tr_dn={p[2]}',
            f'_tr_dnexp={p[3]}', f'_tr_fast={p[4]}', f'_tr_slow={p[5]}',
            f'_tr_us={p[6]}']
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr.decode()[:300])
    return metrics(out)


def base():
    out = os.path.join(tmp, 'base.wav')
    subprocess.run([RENDER, PROBE, out, 'transients=0'], capture_output=True, check=True)
    return metrics(out)


B = base()


def err(p):
    if p[0] <= 0 or p[1] <= 0.5 or p[2] < 0 or p[3] <= 0.2: return 1e6
    if not (0.05 < p[4] < 5.0) or not (50 < p[5] < 2000): return 1e6
    if not (0.0 <= p[6] < 4.0): return 1e6
    e = 0.0
    for tr, ton, ttl in TARGETS:
        on, tl = run(tr, p)
        e += (on - B[0] - ton) ** 2 + (tl - B[1] - ttl) ** 2
    return float(np.sqrt(e / (2 * len(TARGETS))))


p0 = [4.34, 2.95, 0.963, 0.809, 0.5, 152.7, 0.5]
print(f'shipped params rms error: {err(p0):.3f} dB\n')
r = minimize(err, p0, method='Nelder-Mead',
             options={'maxiter': 320, 'xatol': 1e-3, 'fatol': 1e-3})
print(f'fitted: upScale {r.x[0]:.3f}  upExp {r.x[1]:.3f}  dnScale {r.x[2]:.3f}  '
      f'dnExp {r.x[3]:.3f}  fast {r.x[4]:.3f} ms  slow {r.x[5]:.1f} ms  upSus {r.x[6]:.3f}')
print(f'rms error: {r.fun:.3f} dB  (was {err(p0):.3f})\n')
print(f'{"tr":>6s}{"onset tgt":>11s}{"got":>8s}{"tail tgt":>11s}{"got":>8s}')
for tr, ton, ttl in TARGETS:
    on, tl = run(tr, r.x)
    print(f'{tr:>+6.2f}{ton:>+11.2f}{on-B[0]:>+8.2f}{ttl:>+11.2f}{tl-B[1]:>+8.2f}')
