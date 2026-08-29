#!/usr/bin/env python3
"""cells3.py — THIRD export: the transfer curves still missing, at a low carrier.

Everything here exists because of the method rule in measurements.md §32:
transfer curves must be extracted at a LOW carrier with the lag search under one
period. The med and hard ladders, and the Crunch ladder, were only ever measured
on the 300 Hz sweep, whose curves turned out phase-contaminated.

Also: Boom's decay is a TEMPORAL control that barely moved in steady state, so
it needs hits.

Usage: tools/cells3.py > rig/cells3.json
"""
import json

N = {'EnableCompression': False, 'DriveAmount': 0.0, 'DriveType': 0,
     'CrunchAmount': 0.0, 'DampingFrequency': 20000.0, 'TransientShaping': 0.0,
     'BoomAmount': 0.0, 'BoomFrequency': 50.0, 'BoomDecay': 1.0,
     'BoomAudition': False, 'InputTrim': 1.0, 'OutputGain': 1.0, 'DryWet': 1.0}
cells = []


def add(label, on=True, **kw):
    p = dict(N); p.update(kw)
    cells.append({'label': label, 'device_on': on, 'params': p})


add('dry', on=False)
add('neutral')

# --- med and hard curves at 100 Hz. Dense, because these are the two types a
# static curve genuinely fits (hard's per-bin sd was 0.005) and the curve IS the
# model for them.
for t, name in ((1, 'med'), (2, 'hard')):
    for v in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0):
        add(f'{name}_{v}', DriveType=t, DriveAmount=v)

# --- Crunch: its linear response is a mid boost and its character is harmonic,
# so the shaper needs its own curve rather than being inferred from two tones.
for v in (0.25, 0.5, 0.75, 1.0):
    add(f'crunch_{v}', CrunchAmount=v)

# --- Boom decay, on hits. Steady state moved it only ~1 dB at 125 Hz.
for d in (0.0, 0.25, 0.5, 0.75, 1.0):
    add(f'boomdecay_{d}', BoomAmount=0.75, BoomDecay=d)

# --- Transients law: onset/tail vs control, denser than campaign1's six points.
for v in (-0.75, -0.5, -0.25, 0.25, 0.5, 0.75):
    add(f'tr_{v}', TransientShaping=v)

print(json.dumps(cells, indent=1))
