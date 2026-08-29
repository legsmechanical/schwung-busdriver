#!/usr/bin/env python3
"""cells4.py — VALIDATION. Live's own 22 stock Drum Buss presets.

These have never been used for fitting and must not be. Their exact parameter
values came out of Live's shipped .adv files (docs/reference/stock-presets.tsv),
so they are real settings a person would actually dial, not points chosen to
flatter the model.

The score this produces is the campaign's actual result: how close the model is
on material and settings it has never seen.

Usage: tools/cells4.py > rig/cells4.json
"""
import csv, json, os, sys

TSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'docs', 'reference', 'stock-presets.tsv')
N = {'EnableCompression': False, 'DriveAmount': 0.0, 'DriveType': 0,
     'CrunchAmount': 0.0, 'DampingFrequency': 20000.0, 'TransientShaping': 0.0,
     'BoomAmount': 0.0, 'BoomFrequency': 50.0, 'BoomDecay': 1.0,
     'BoomAudition': False, 'InputTrim': 1.0, 'OutputGain': 1.0, 'DryWet': 1.0}

cells = [{'label': 'dry', 'device_on': False, 'params': dict(N)},
         {'label': 'neutral', 'device_on': True, 'params': dict(N)}]

rows = [l for l in open(TSV) if not l.startswith('#')]
rd = csv.DictReader(rows, delimiter='\t')
for i, r in enumerate(rd):
    p = dict(N)
    p['EnableCompression'] = r['EnableCompression'].strip() == 'true'
    p['DriveAmount']      = float(r['DriveAmount'])
    p['DriveType']        = int(float(r['DriveType']))
    p['CrunchAmount']     = float(r['CrunchAmount'])
    p['DampingFrequency'] = float(r['DampingFrequency'])
    p['TransientShaping'] = float(r['TransientShaping'])
    p['BoomAmount']       = float(r['BoomAmount'])
    p['BoomFrequency']    = float(r['BoomFrequency'])
    p['BoomDecay']        = float(r['BoomDecay'])
    p['DryWet']           = float(r['DryWet'])
    safe = ''.join(ch if (ch.isalnum() or ch in '_-') else '_' for ch in r['preset'])
    cells.append({'label': f'p{i:02d}_{safe}'[:40], 'device_on': True, 'params': p})

print(json.dumps(cells, indent=1))
