#!/usr/bin/env python3
"""cells2.py — the SECOND export, aimed at exactly the three questions the first
one could not answer.

1. The compressor's attack and release. v1's steps probe used a 200 Hz carrier
   = 5.0 ms per cycle, a hard floor below which no envelope method can resolve
   anything, and the device's attack is under it. suite2 uses 2 kHz.
2. Where Transients sits in the chain. A steady sweep cannot place it — the
   stage is inert on steady tones — so it has to be measured on hits, against
   cells where a downstream clipper would or would not see its effect.
3. The `soft` fold law. At one carrier it showed a large phase-dependent spread,
   so the same amplitude sweep is repeated at 100 Hz / 300 Hz / 1 kHz / 3 kHz to
   say whether the fold itself is frequency dependent or only the filtering
   around it. The ladder is dense near 0.5-0.75 where folding sets in.

Usage: tools/cells2.py > rig/cells2.json
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

# --- 1. compressor time constants, on the 2 kHz steps
add('comp_on', EnableCompression=True)
add('comp_drive0.5', EnableCompression=True, DriveAmount=0.5)
add('comp_hard1', EnableCompression=True, DriveType=2, DriveAmount=1.0)

# --- 3. the fold law: dense where folding sets in (H3 overtakes between .5 and .75)
for v in (0.25, 0.5, 0.625, 0.75, 0.875, 1.0):
    add(f'soft_{v}', DriveType=0, DriveAmount=v)

# --- 2. where Transients sits.
# Alone, then with a downstream clipper hard against it. If Transients is
# UPSTREAM of the distortion, boosting a transient by +8 dB drives the clipper
# harder and must change the harmonic-to-linear ratio, exactly as the compressor
# did. If it is DOWNSTREAM, the ratio cannot move.
add('tr_-1', TransientShaping=-1.0)
add('tr_+1', TransientShaping=1.0)
add('tr_-1_hard1', TransientShaping=-1.0, DriveType=2, DriveAmount=1.0)
add('tr_+1_hard1', TransientShaping=1.0, DriveType=2, DriveAmount=1.0)
add('tr_+1_crunch1', TransientShaping=1.0, CrunchAmount=1.0)
add('tr_+1_boom075', TransientShaping=1.0, BoomAmount=0.75)

# --- Boom decay is a TEMPORAL control; steady-state barely moved it, so it
# needs hits.
for d in (0.0, 0.5, 1.0):
    add(f'boomdecay_{d}', BoomAmount=0.75, BoomDecay=d)

print(json.dumps(cells, indent=1))
