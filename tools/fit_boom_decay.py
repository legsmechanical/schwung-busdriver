#!/usr/bin/env python3
"""fit_boom_decay.py — fit Boom's ring-time law against the measured decay
table, measurements.md §40.

§40's table is a RATIO to a Boom-off render at 20/50/100/150 ms post-hit, so
whatever excited the resonator in Ableton's own measurement had mostly died
away by then — otherwise the ratio would just track the excitation, not the
resonance's own memory. `rig/probes/hits.wav` (shared with fit_transients.py)
cannot stand in for that here: its shortest body decay is 80 ms, so at 100-150
ms the resonator is still being actively re-driven rather than ringing on its
own, and a leak-time fit against it is fitting noise (checked: BoomDecay 0 vs
1 render nearly identical on that probe, even though the mechanism itself
proves out cleanly on a short click — see the impulse check this file's
history records). So this probe is FIT-SPECIFIC: a single short (~15 ms body
decay) kick-like hit, repeated every 250 ms — the shape needed to let Boom's
own memory, not the excitation, dominate by the 100-150 ms checkpoints.

Fitted through the real module via `render`. Four parameters: qLo/qHi (the
resonator's own Q at decay 0/1) and tauLoMs/tauHiMs (an additional leak-time
multiplier at decay 0/1). MEASURED here, not assumed: a low fixed Q (the
first attempt) damps the ring so hard through the filter's own recursion that
leak alone cannot put ring back into it — a resonator only rings less than
its Q allows, never more. So Q has to move too.

The probe is HOT (peak 0.95, not the usual ~0.25) because the real device
contract round-trips through int16 (see render.cpp's own note on this), and
at the probe's usual level Boom's tail quantizes to exact digital silence by
~150 ms regardless of the law underneath it — measured directly by sample
inspection, not assumed either.

⚠ RESULT: inconclusive, and the shipped Boom defaults are NOT this script's
output. Every probe tried here (this one included) gives a got-vs-decay curve
that barely separates — best found rms ~11-14 dB against §40, and pushing
harder only walked Q down toward its floor (0.2-0.5), which is barely
resonant at all and not what "Boom" should sound like. Meanwhile an isolated
single click (no repeated-hit probe, no ratio-to-baseline) shows the SAME
qLo/qHi/tauLoMs/tauHiMs mechanism working exactly as intended — clean,
monotonic, audible. So this script's own metric doesn't discriminate
parameters the mechanism demonstrably does discriminate; the fault is here,
not in dsp/drumbuss.h. Left in place as a documented dead end and a starting
point, not as the source of the shipped numbers (those were set from the
impulse check — see the note at Boom's definition in dsp/drumbuss.h).

Usage: tools/fit_boom_decay.py
"""
import os, subprocess, sys, tempfile
import numpy as np
from scipy.optimize import minimize
from scipy.signal import butter, sosfiltfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyse import read_wav, db
from probes import write_wav

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, '..', 'build', 'render')
SR, BPM = 44100, 120.0
STEP = int(SR * 60.0 / BPM / 2)          # 11025 samples = 250 ms between hits
CHECKPOINTS_MS = (20, 50, 100, 150)
BODY_TAU_S = 0.015                       # short/punchy — see module docstring

# measurements.md §40 — dB relative to Boom off, at each checkpoint
TARGETS = {
    0.00: (+5.03, -12.26, -15.62, -17.24),
    0.25: (+5.60, -11.85, -14.85, -16.18),
    0.50: (+6.18, -11.20, -11.78, -7.74),
    0.75: (+6.77, -10.33, -7.33, -0.73),
    1.00: (+7.35, -9.23, -2.74, +4.89),
}

tmp = tempfile.mkdtemp()


def make_probe(seconds=4.0, peak=0.95):
    n = int(seconds * SR)
    out = [0.0] * n
    for start in range(0, n - STEP, STEP):
        for i in range(STEP):
            t = i / SR
            env = np.exp(-t / BODY_TAU_S)
            out[start + i] += peak * env * np.sin(2 * np.pi * 50.0 * t)
    return out


PROBE = os.path.join(tmp, 'boom_probe.wav')
p = make_probe()
write_wav(PROBE, p, p, SR)

_sos = butter(4, 150.0, btype='low', fs=SR, output='sos')


def sub_env_db(y):
    """Sub-band (<150 Hz) envelope in dB. An 8 ms half-window (~1.5 cycles at
    50 Hz) RMS-averages across the ripple the resonance itself puts in the
    envelope — a narrower window catches a peak or trough of that ripple
    depending on phase, which is noise, not signal."""
    lo = sosfiltfilt(_sos, y)
    out = []
    for ms in CHECKPOINTS_MS:
        c = int(SR * ms / 1000.0)
        w = max(1, int(SR * 0.008))
        seg = lo[max(0, c - w):c + w]
        out.append(db(float(np.sqrt((seg ** 2).mean()))))
    return out


def hit_checkpoints(y):
    n = len(y)
    rows = [sub_env_db(y[s:s + STEP]) for s in range(0, n - STEP, STEP)]
    return np.mean(np.array(rows), axis=0)


def render(decay, params=None):
    tag = '_'.join(f'{p:.3f}' for p in params) if params is not None else 'base'
    out = os.path.join(tmp, f'b{decay:.2f}_{tag}.wav')
    args = [RENDER, PROBE, out, 'boom=1', 'boom_freq=50', f'boom_decay={decay}']
    if params is not None:
        q_lo, q_hi, tau_lo, tau_hi = params
        args += [f'_boom_q_lo={q_lo}', f'_boom_q_hi={q_hi}',
                 f'_boom_tau_lo={tau_lo}', f'_boom_tau_hi={tau_hi}']
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(r.stderr.decode()[:400])
    return hit_checkpoints(read_wav(out)['l'])


print('rendering baseline (boom off)...')
out0 = os.path.join(tmp, 'off.wav')
subprocess.run([RENDER, PROBE, out0, 'boom=0'], capture_output=True, check=True)
BASE = hit_checkpoints(read_wav(out0)['l'])
print('baseline (boom off) sub-band envelope dB:', np.round(BASE, 2))


def err(p):
    q_lo, q_hi, tau_lo, tau_hi = p
    if not (0.5 < q_lo < 5.0) or not (q_lo < q_hi < 150.0):
        return 1e6
    if not (5.0 < tau_lo < 200.0) or not (tau_lo < tau_hi < 3000.0):
        return 1e6
    e = 0.0
    for decay, targets in TARGETS.items():
        got = render(decay, p) - BASE
        e += float(np.sum((got - np.array(targets)) ** 2))
    return float(np.sqrt(e / (4 * len(TARGETS))))


p0 = [1.5, 2.0, 190.0, 210.0]   # a valid, nearly-inert starting point (both laws need strict lo<hi)
print(f'\nplaceholder rms error: {err(p0):.2f} dB')
r = minimize(err, p0, method='Nelder-Mead',
             options={'maxiter': 400, 'xatol': 1e-3, 'fatol': 1e-3})
print(f'fitted: qLo {r.x[0]:.3f}  qHi {r.x[1]:.3f}  tauLoMs {r.x[2]:.2f}  tauHiMs {r.x[3]:.2f}')
print(f'rms error: {r.fun:.2f} dB (was {err(p0):.2f})\n')

print(f'{"decay":>7s}' + ''.join(f'{ms:>7d}ms tgt{ms:>5d}ms got' for ms in CHECKPOINTS_MS))
for decay, targets in TARGETS.items():
    got = render(decay, r.x) - BASE
    row = f'{decay:>7.2f}'
    for t, g in zip(targets, got):
        row += f'{t:>+11.2f}{g:>+11.2f}'
    print(row)
