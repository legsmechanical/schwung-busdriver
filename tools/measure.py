#!/usr/bin/env python3
"""measure.py — read every rendered cell and report what each stage does.

Usage: tools/measure.py <renders_dir> <set_project_dir> [--only substring]
"""
import argparse, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import (SR, align_cell, align_envelope, seg, db, tone_db, transfer_curve,
                      farina_ir, magnitude_response, burst_levels)
from analyse import read_wav, resolve_probe

BURST_LEVELS = (-60, -48, -36, -30, -24, -18, -12, -6, -3, 0)
PIN_LAG = 55   # measured device latency; used when a cell deforms the align tone


def load(renders, project):
    probe_path, man = resolve_probe(renders, project)
    probe = read_wav(probe_path)['l']
    off = man['suite']['offsets']
    cells = {t['name']: t for t in man['tracks']}
    files = {}
    for f in sorted(os.listdir(renders)):
        if not f.endswith('.wav'):
            continue
        for name in cells:
            if f.endswith(name + '.wav'):
                files[name] = os.path.join(renders, f)
    return probe, off, cells, files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('renders'); ap.add_argument('project')
    ap.add_argument('--only', default='')
    ap.add_argument('--out', default=None, help='write a JSON of all results')
    a = ap.parse_args()

    probe, off, cells, files = load(a.renders, a.project)
    dryname = [n for n in cells if n.endswith('dry')][0]
    dry = read_wav(files[dryname])['l']

    results = {}
    names = [n for n in sorted(cells) if a.only in n]

    # ---- Pass 1: establish the DEVICE's lag and polarity from the cells where
    # alignment is trustworthy, then pin them.
    #
    # Latency and polarity belong to the device, not to a parameter setting:
    # delay compensation is uniform and the device does not re-latch its phase
    # when you turn a knob. Fitting them per cell lets a badly-aligned outlier
    # invent physics — drive_hard_1.0 came out at lag 164 with positive polarity
    # and a transfer curve of width +37 dB, i.e. noise.
    probe_lags, pols = [], []
    for name in names:
        if name == dryname:
            continue
        w = read_wav(files[name])['l']
        L, eres, pol = align_envelope(dry, w, off)
        if db(eres) < -12.0:                 # trust only clean alignments
            probe_lags.append(L); pols.append(pol)
    DEV_LAG = int(np.median(probe_lags)) if probe_lags else PIN_LAG
    DEV_POL = -1.0 if sum(1 for p in pols if p < 0) > len(pols) / 2 else 1.0
    print(f'device lag  {DEV_LAG} samples ({DEV_LAG/SR*1000:.2f} ms) '
          f'from {len(probe_lags)}/{len(names)-1} cleanly-aligned cells'
          f'   polarity {"INVERTING" if DEV_POL < 0 else "normal"}'
          f' ({sum(1 for p in pols if p < 0)}/{len(pols)} agree)\n')

    print(f'{"cell":<24s} {"lag":>4s} {"pol":>4s} {"g@-30":>7s} | {"slope0":>7s} '
          f'{"sat+":>7s} {"width":>7s} | {"60Hz":>7s} {"6kHz":>7s} {"tilt":>7s}')
    print('-' * 96)
    for name in names:
        w = read_wav(files[name])['l']
        # Envelope-based: carrier-free, so it cannot pick a half-period-shifted
        # lag and silently invert every curve downstream.
        lag_own, eres, pol_own = align_envelope(dry, w, off)
        trusted = db(eres) < -12.0
        lag = lag_own if trusted else DEV_LAG
        # The bypassed reference is the device NOT being in circuit, so the
        # device's polarity must not be applied to it.
        pol = 1.0 if name == dryname else DEV_POL
        _, res, g = align_cell(dry, w, off)

        r = {'lag': int(lag), 'lag_own': int(lag_own), 'lag_trusted': trusted,
             'env_resid_db': db(eres), 'polarity': pol,
             'align_resid_db': db(res), 'gain_small_db': db(abs(g)),
             'params': cells[name]['params'],
             'device_on': cells[name]['device_on']}

        # --- transfer curve, from the amplitude-swept carrier
        # Multiply out the device's polarity so the curve describes the SHAPE.
        # Polarity is reported separately rather than baked into every number.
        x = seg(probe, off, 'swept'); y = pol * seg(w, off, 'swept', lag)
        m = min(len(x), len(y))
        tc = transfer_curve(x[:m], y[:m]) if m > 1000 else None
        if tc:
            r['curve'] = {k: tc[k] for k in
                          ('slope0', 'out_pos', 'out_neg', 'asym', 'width_db')}

        # --- Crunch band split, from the two-tone probe
        xt = seg(probe, off, 'twotone'); yt = pol * seg(w, off, 'twotone', lag)
        m = min(len(xt), len(yt))
        if m > 1000:
            lo_i, hi_i = tone_db(xt[:m], 60.0), tone_db(xt[:m], 6000.0)
            lo_o, hi_o = tone_db(yt[:m], 60.0), tone_db(yt[:m], 6000.0)
            r['twotone'] = {'lo_gain': lo_o - lo_i, 'hi_gain': hi_o - hi_i,
                            'tilt': (hi_o - hi_i) - (lo_o - lo_i)}

        print(f'{name:<24s} {lag:>4d}{"" if trusted else "*"} '
              f'{"INV" if pol<0 else "+":>3s} '
              f'{r["gain_small_db"]:>+7.2f} | '
              + (f'{tc["slope0"]:>7.3f} {tc["out_pos"]:>7.4f} {tc["width_db"]:>6.1f}dB'
                 if tc else f'{"—":>7s} {"—":>7s} {"—":>8s}')
              + ' | '
              + (f'{r["twotone"]["lo_gain"]:>+7.2f} {r["twotone"]["hi_gain"]:>+7.2f} '
                 f'{r["twotone"]["tilt"]:>+7.2f}' if 'twotone' in r else ''))
        results[name] = r

    if a.out:
        with open(a.out, 'w') as f:
            json.dump(results, f, indent=1, default=float)
        print(f'\nwrote {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
