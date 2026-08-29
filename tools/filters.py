#!/usr/bin/env python3
"""filters.py — magnitude responses via Farina sweep deconvolution.

Two spot frequencies told us Damp is a low-pass and Boom is a resonance. This
gives the actual curves, and separates the LINEAR response from the device's own
distortion — which matters because Drum Buss saturates even at Drive 0, so a
plain FFT(out)/FFT(in) ratio would fold harmonic products into the "filter".

Usage: tools/filters.py <renders> <project> [--cells substr]
"""
import argparse, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segments import SR, seg, db
from analyse import read_wav, resolve_probe

F0, F1, SWEEP_S = 20.0, 20000.0, 10.0
LAG, POL = 55, 1.0


def inverse_filter(x, f0=F0, f1=F1, seconds=SWEEP_S, sr=SR):
    """Sweep time-reversed with a 1/f amplitude envelope (Farina)."""
    n = len(x)
    L = seconds / math.log(f1 / f0)
    t = np.arange(n) / sr
    # ⚠ The envelope indexes FORWARD over the reversed sweep. Reversed sweep
    # index 0 is the HIGH-frequency end, so exp(-t/L) must be 1 there and
    # f0/f1 (-60 dB here) at the low end. Using exp(-t[::-1]/L) flips it and
    # tilts the whole result by ~84 dB across the band — which showed up as a
    # LOW-PASS reporting +6.8 dB of boost at 2 kHz.
    inv = x[::-1] * np.exp(-t / L)
    return inv / (np.sqrt((inv * inv).mean()) + 1e-30)


def deconvolve(x, y):
    """Full deconvolution. The LINEAR impulse response sits at the main peak;
    harmonic orders land AHEAD of it, separated in time — which is the whole
    reason to use a sweep rather than a tone ladder on a nonlinear device."""
    inv = inverse_filter(x)
    m = 1 << int(np.ceil(np.log2(len(x) + len(inv))))
    full = np.fft.irfft(np.fft.rfft(y, m) * np.fft.rfft(inv, m), m)
    return full, int(np.argmax(np.abs(full)))


def linear_ir(full, peak, pre=512, post=8192):
    """Window around the linear peak only. `pre` must stay short: the 2nd
    harmonic arrives L*ln(2) seconds early, which at these settings is ~0.8 s,
    so a few hundred samples of pre-roll is safely clear of it."""
    a = max(0, peak - pre)
    return full[a:peak + post]


def response(ir, freqs, sr=SR, n=1 << 16):
    H = np.fft.rfft(ir, n)
    out = {}
    for f in freqs:
        k = int(round(f * n / sr))
        out[f] = db(abs(H[k]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('renders'); ap.add_argument('project')
    ap.add_argument('--cells', default='damp')
    a = ap.parse_args()

    probe_path, man = resolve_probe(a.renders, a.project)
    probe = read_wav(probe_path)['l']
    off = man['suite']['offsets']
    cells = {t['name']: t for t in man['tracks']}
    files = {}
    for f in sorted(os.listdir(a.renders)):
        if f.endswith('.wav'):
            for n in cells:
                if f.endswith(n + '.wav'):
                    files[n] = os.path.join(a.renders, f)

    x = seg(probe, off, 'sweep')
    names = [n for n in sorted(cells) if a.cells in n or n.endswith('neutral')]
    FREQS = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 12000, 16000]

    # neutral is the reference: it isolates the stage under test from the
    # device's always-on gain and saturation.
    ref = None
    rows = {}
    for n in names:
        w = read_wav(files[n])['l']
        y = POL * seg(w, off, 'sweep', LAG)
        m = min(len(x), len(y))
        full, peak = deconvolve(x[:m], y[:m])
        ir = linear_ir(full, peak)
        r = response(ir, FREQS)
        rows[n] = r
        if n.endswith('neutral'):
            ref = r

    hdr = f'{"cell":<22s}' + ''.join(f'{f:>8d}' for f in FREQS)
    print('Magnitude response relative to NEUTRAL (dB), from the Farina linear IR')
    print(hdr); print('-' * len(hdr))
    for n in names:
        if n.endswith('neutral'):
            continue
        line = f'{n[3:]:<22s}'
        for f in FREQS:
            line += f'{rows[n][f] - ref[f]:>8.2f}'
        print(line)
    print(f'\n(neutral absolute: ' +
          ' '.join(f'{f}Hz {ref[f]:+.2f}' for f in (63, 1000, 8000)) + ')')


if __name__ == '__main__':
    main()
