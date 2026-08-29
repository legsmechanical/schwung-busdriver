#!/usr/bin/env python3
"""score.py — the campaign's actual result: how close is the model on settings
and material it has never seen?

Renders Live's 22 stock presets through OUR module (via the real
audio_fx_api_v2, using tools/render.cpp) and compares against Live's own render
of the same presets on the same held-out material.

⚠ The comparison is done on the VALIDATION segment only. `hits` was used to fit
the Transients law and Boom's decay and is therefore not held out.

Usage: tools/score.py <renders_dir> <set_project_dir>
"""
import json, os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import seg, db
from analyse import read_wav, resolve_probe

RENDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'build', 'render')
# Live's parameter names -> our module's keys, with the unit conversions Live
# does not do (it stores Trim and Output as linear gains).
def to_ours(p):
    import math
    return {
        'comp':       1.0 if p['EnableCompression'] else 0.0,
        'drive':      p['DriveAmount'],
        'drive_type': p['DriveType'],
        'crunch':     p['CrunchAmount'],
        'damp':       p['DampingFrequency'],
        'transients': p['TransientShaping'],
        'boom':       p['BoomAmount'],
        'boom_freq':  p['BoomFrequency'],
        'boom_decay': p['BoomDecay'],
        'trim':       20.0 * math.log10(max(p['InputTrim'], 1e-6)),
        'output':     20.0 * math.log10(max(p['OutputGain'], 1e-6)),
        'drywet':     p['DryWet'],
    }


def main():
    renders, project = sys.argv[1], sys.argv[2]
    probe_path, man = resolve_probe(renders, project)
    off = man['suite']['offsets']
    SEGN = 'valid'
    cells = {t['name']: t for t in man['tracks']}
    files = {}
    for f in sorted(os.listdir(renders)):
        if f.endswith('.wav'):
            for n in cells:
                if f.endswith(n + '.wav'):
                    files[n] = os.path.join(renders, f)

    tmp = tempfile.mkdtemp()
    print(f'{"preset":<30s}{"level err":>11s}{"spec err":>10s}{"resid":>9s}')
    print('-' * 62)
    scores = []
    for name, t in sorted(cells.items()):
        if name.endswith('dry') or name not in files:
            continue
        ours = os.path.join(tmp, name + '.wav')
        args = [RENDER, probe_path, ours] + [f'{k}={v}' for k, v in to_ours(t['params']).items()]
        r = subprocess.run(args, capture_output=True)
        if r.returncode != 0:
            print(f'{name:<30s}  render failed: {r.stderr.decode()[:60]}')
            continue
        live = read_wav(files[name])['l']
        mine = read_wav(ours)['l']
        a = seg(live, off, SEGN, 190)
        b = seg(mine, off, SEGN, 0)
        m = min(len(a), len(b)); a, b = a[:m], b[:m]
        lvl = db(np.sqrt((b*b).mean() + 1e-30)) - db(np.sqrt((a*a).mean() + 1e-30))
        # spectral distance: log-magnitude error over 1/3-octave bands
        n = 1 << 15
        A = np.abs(np.fft.rfft(a[:n] * np.hanning(min(n, len(a)))[:min(n,len(a))], n))
        B = np.abs(np.fft.rfft(b[:n] * np.hanning(min(n, len(b)))[:min(n,len(b))], n))
        f = np.fft.rfftfreq(n, 1/44100)
        band = (f > 40) & (f < 16000)
        sa = db(A[band] / (A[band].max() + 1e-30))
        sb = db(B[band] / (B[band].max() + 1e-30))
        spec = float(np.sqrt(np.mean((sa - sb) ** 2)))
        g = float(a @ b / (b @ b)) if (b @ b) else 0.0
        res = db(float(np.sqrt(((g*b - a) ** 2).mean()) / (np.sqrt((a*a).mean()) + 1e-30)))
        scores.append((lvl, spec, res))
        print(f'{name[:30]:<30s}{lvl:>+10.2f}dB{spec:>9.2f}dB{res:>8.1f}dB')
    if scores:
        L = np.array([s[0] for s in scores]); S = np.array([s[1] for s in scores])
        print('-' * 62)
        print(f'{"MEDIAN":<30s}{np.median(L):>+10.2f}dB{np.median(S):>9.2f}dB')
        print(f'{"WORST":<30s}{L[np.argmax(np.abs(L))]:>+10.2f}dB{S.max():>9.2f}dB')


if __name__ == '__main__':
    main()
