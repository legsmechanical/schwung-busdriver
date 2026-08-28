#!/usr/bin/env python3
"""cells.py — the parameter cells for the one-export campaign sweep.

Each cell becomes one track carrying the whole probe suite, so a single Live
export covers phases 1-5. Track 0 is the dry reference (device off) and track 1
is the device at neutral — the two anchors every other cell is read against.

Ranges are Live's own (from the stock .adv presets), so nothing here is a guess
about what a control's endpoints are.

Usage: tools/cells.py > rig/cells.json
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

# --- Drive: three types, and the device SATURATES at Drive 0, so 0 is a cell too
for t, tname in enumerate(['soft', 'med', 'hard']):
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        add(f'drive_{tname}_{v}', DriveType=t, DriveAmount=v)

# --- Crunch: band-limited per the manual, so twotone/sweep locate the corner
for v in (0.25, 0.5, 0.75, 1.0):
    add(f'crunch_{v}', CrunchAmount=v)

# --- Damp: a low-pass. Ladder LOGARITHMICALLY across its 500..20000 Hz range.
for hz in (500, 1000, 2000, 4000, 8000, 16000):
    add(f'damp_{hz}', DampingFrequency=float(hz))
# and one with Crunch up, since Damp exists to tame what Crunch adds
add('damp_2000_crunch_1', DampingFrequency=2000.0, CrunchAmount=1.0)

# --- Transients: bipolar. Measured on hits; symmetry is the question.
for v in (-1.0, -0.5, -0.25, 0.25, 0.5, 1.0):
    add(f'transient_{v}', TransientShaping=v)

# --- Boom: a resonant sub generator. Amount, then frequency and decay at a
# fixed useful amount so the three are separable.
for v in (0.25, 0.5, 0.75, 1.0):
    add(f'boom_{v}', BoomAmount=v)
for hz in (30.0, 50.0, 70.0, 90.0):
    add(f'boomfreq_{hz}', BoomAmount=0.75, BoomFrequency=hz)
for d in (0.0, 0.25, 0.5, 0.75):
    add(f'boomdecay_{d}', BoomAmount=0.75, BoomDecay=d)

# --- Compressor: a BOOL. bursts gives the static curve, steps the times.
add('comp_on', EnableCompression=True)
add('comp_on_drive_0.5', EnableCompression=True, DriveAmount=0.5)

# --- Static gains: these should be exact, so confirm and move on.
add('trim_-12dB', InputTrim=0.251188643)
add('trim_-6dB', InputTrim=0.501187234)
add('out_+3dB', OutputGain=1.41253757)
add('out_-6dB', OutputGain=0.501187234)
add('drywet_0', DryWet=0.0)          # must null against dry
add('drywet_0.5', DryWet=0.5, DriveAmount=1.0, DriveType=2)

# --- TOPOLOGY (spec §4.1): measured, not taken from the manual.
# Comp before or after Drive? If Comp is upstream, it changes what the clipper
# sees and the flat-top width moves; downstream, only the level after it moves.
add('topo_hard_nocomp', DriveType=2, DriveAmount=1.0)
add('topo_hard_comp', DriveType=2, DriveAmount=1.0, EnableCompression=True)
# Crunch before or after Damp? If Crunch is upstream, Damp attenuates its
# harmonics; downstream, they land above the corner untouched.
add('topo_crunch1_damp500', CrunchAmount=1.0, DampingFrequency=500.0)
add('topo_crunch1_damp20k', CrunchAmount=1.0, DampingFrequency=20000.0)
# Where does Transients sit relative to the clipper? A gate before a clipper
# behaves very differently from one after it.
add('topo_tr-1_hard1', TransientShaping=-1.0, DriveType=2, DriveAmount=1.0)

print(json.dumps(cells, indent=1))
