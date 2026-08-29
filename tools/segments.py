#!/usr/bin/env python3
"""segments.py — slice a rendered suite and measure each segment with the right
instrument.

One Live export gives 59 cells x 8 probe segments. Each segment answers one
question and needs its own analysis; running one metric over the whole 56 s
would average unrelated behaviours together and mean nothing.

Nothing here fits anything. It MEASURES, and reports numbers with their
provenance so the fitting step has something honest to work from.
"""
import json, math, os
import numpy as np

SR = 44100


# --------------------------------------------------------------- alignment
def align_cell(dry, wet, off, pin=None, span=512):
    """Lag of a cell relative to the dry reference, measured on the -30 dBFS
    alignment tone at the head of the suite.

    Quiet on purpose: every cell, including hard drive at 1.0, is quasi-linear
    there. Correlating a distorted output against a clean input is NOT a valid
    aligner — full-length it reported 0/0/0/129/1305 samples across one drive
    ladder, and the bad lag silently inverted an extracted transfer curve.

    Returns (lag, residual_db). If the residual is poor the caller should fall
    back to `pin`: transient shaping deforms even the quiet tone, and
    transient_1.0 railed to lag 496 that way.
    """
    o = off['align']
    s, n = o['start'], o['frames']
    a = dry[s:s + n]
    best = (0, 1e9)
    for L in range(-span, span + 1):
        lo = s + L
        if lo < 0 or lo + n > len(wet):
            continue
        b = wet[lo:lo + n]
        d = float(a @ a)
        if d <= 0:
            continue
        g = float(a @ b) / d
        r = g * a - b
        res = float(np.sqrt((r * r).mean()) / (np.sqrt((b * b).mean()) + 1e-30))
        if res < best[1]:
            best = (L, res, g)
    return best


def envelope(x, win=64):
    return np.convolve(np.abs(x), np.ones(win) / win, 'same')


def align_envelope(dry, wet, off, segname='bursts', span=(-200, 400)):
    """Lag by ENVELOPE cross-correlation, plus the polarity at that lag.

    ⚠⚠ A pure tone cannot distinguish a polarity flip from a half-period shift.
    The −30 dBFS alignment tone is a 300 Hz sine, so its candidates come out
    spaced 73.5 samples apart with ALTERNATING SIGN — 49 (g=−1), 122 (g=+1),
    196 (g=−1) — and picking the wrong one silently inverts every transfer curve
    extracted afterwards. The envelope of the burst segment has no carrier, so it
    cannot alias, and it settles the question.

    MEASURED 2026-08-28: every cell correlates NEGATIVE at its envelope lag.
    **Drum Buss inverts polarity.** The bypassed dry track is bit-exact and
    positive, so the inversion belongs to the device, not the rig.

    FFT-based: the direct loop was 601 lags x 441k samples per cell and did not
    finish 59 cells in fifteen minutes.
    """
    a = envelope(seg(dry, off, segname))
    s0, n = off[segname]['start'], len(a)
    lo, hi = span
    b = wet[max(0, s0 + lo): s0 + hi + n]
    if len(b) < n:
        return 0, 1e9, 1.0
    be = envelope(b)
    m = 1 << int(np.ceil(np.log2(len(be) + n)))
    cc = np.fft.irfft(np.fft.rfft(be, m) * np.conj(np.fft.rfft(a, m)), m)
    k = int(np.argmax(cc[:hi - lo + 1]))
    L = lo + k + (0 if s0 + lo >= 0 else -(s0 + lo))

    seg_b = wet[s0 + L: s0 + L + n]
    mm = min(len(seg_b), n)
    if mm < n // 2:
        return L, 1e9, 1.0
    ae, bb = a[:mm], envelope(seg_b)[:mm]
    d = float(ae @ ae)
    g = float(ae @ bb) / d if d else 0.0
    r = g * ae - bb
    res = float(np.sqrt((r * r).mean()) / (np.sqrt((bb * bb).mean()) + 1e-30))

    xa = seg(dry, off, segname)[:mm]
    polarity = -1.0 if float(xa @ seg_b[:mm]) < 0 else 1.0
    return L, res, polarity


def seg(x, off, name, lag=0):
    o = off[name]
    s = o['start'] + lag
    s = max(0, s)
    return x[s:s + o['frames']]


def db(x):
    x = float(x)
    return 20.0 * math.log10(x) if x > 1e-30 else -300.0


def tone_db(x, hz, sr=SR):
    """Level of one frequency component, via Goertzel over a Hann window."""
    n = len(x)
    w = np.hanning(n)
    k = 2 * np.pi * hz / sr
    ph = np.exp(-1j * k * np.arange(n))
    return db(2.0 * abs(np.sum(x * w * ph)) / (w.sum() + 1e-30))


# --------------------------------------------------------------- instruments
def transfer_curve(x, y, nb=401):
    """Output binned by the input sample that produced it.

    Valid only for a memoryless stage. The swept probe visits every level twice
    (amplitude ramps up then down), so if the stage has memory the two visits
    disagree and the bin gains WIDTH. `width` is that spread relative to the
    curve: a wide band means a transfer curve is the WRONG MODEL here, not that
    the curve is noisy.
    """
    edges = np.linspace(-1.0, 1.0, nb + 1)
    idx = np.clip(np.digitize(x, edges) - 1, 0, nb - 1)
    cnt = np.bincount(idx, minlength=nb)
    sm = np.bincount(idx, weights=y, minlength=nb)
    sq = np.bincount(idx, weights=y * y, minlength=nb)
    ok = cnt > 20
    centres = 0.5 * (edges[:-1] + edges[1:])
    mean = np.zeros(nb); mean[ok] = sm[ok] / cnt[ok]
    sd = np.zeros(nb)
    sd[ok] = np.sqrt(np.maximum(sq[ok] / cnt[ok] - mean[ok] ** 2, 0))
    c = np.flatnonzero(ok)
    if len(c) < 20:
        return None
    mid = c[np.argmin(np.abs(centres[c]))]
    lo, hi = max(mid - 10, c[0]), min(mid + 10, c[-1])
    slope = (mean[hi] - mean[lo]) / (centres[hi] - centres[lo])
    return {'centres': centres[c], 'mean': mean[c], 'sd': sd[c],
            'slope0': float(slope), 'out_pos': float(mean[c[-1]]),
            'out_neg': float(mean[c[0]]),
            'asym': float(mean[c[-1]] + mean[c[0]]),
            'width_db': db(float(np.mean(sd[ok] / (np.abs(mean[ok]) + 1e-6))))}


def farina_ir(x, y, f0=20.0, f1=20000.0, seconds=10.0, sr=SR):
    """Linear impulse response by deconvolving an exponential sweep.

    The inverse filter is the sweep time-reversed with a 1/f envelope. After
    convolution the LINEAR response sits at the end of the result and each
    harmonic order lands ahead of it, separated in time — so the filter can be
    read without the device's own distortion contaminating it. That separation
    is the whole reason to use a sweep here rather than a tone ladder.
    """
    n = len(x)
    L = seconds / math.log(f1 / f0)
    t = np.arange(n) / sr
    inv = x[::-1] * np.exp(-t[::-1] / L)
    inv /= (np.abs(inv).max() + 1e-30)
    m = 1 << int(np.ceil(np.log2(2 * n)))
    H = np.fft.rfft(y, m) * np.fft.rfft(inv, m)
    full = np.fft.irfft(H, m)
    peak = int(np.argmax(np.abs(full)))
    a = max(0, peak - 256)
    return full[a:peak + 4096], peak - a


def magnitude_response(ir, sr=SR, freqs=(60, 125, 250, 500, 1000, 2000,
                                         4000, 8000, 12000, 16000)):
    n = 1 << 16
    H = np.fft.rfft(ir, n)
    f = np.fft.rfftfreq(n, 1 / sr)
    out = {}
    for hz in freqs:
        k = int(round(hz * n / sr))
        out[hz] = db(abs(H[k]))
    return out


def burst_levels(x, y, levels_db, on=0.5, off_s=0.5, sr=SR):
    """Static gain curve: measured level in vs out over the steady part of each
    burst.

    The silence between bursts lets the detector fully release, so each level is
    independent rather than riding the previous one's gain reduction.
    """
    rows = []
    step = int((on + off_s) * sr)
    for i, lvl in enumerate(levels_db):
        s = i * step + int(0.15 * sr)          # skip the attack
        e = i * step + int(on * sr) - int(0.02 * sr)
        if e > len(y):
            break
        xi, yi = x[s:e], y[s:e]
        rows.append((lvl, db(np.sqrt((xi * xi).mean())),
                     db(np.sqrt((yi * yi).mean()))))
    return rows


def env_follow(x, atk_ms=1.0, rel_ms=1.0, sr=SR):
    a = 1.0 - math.exp(-1.0 / (atk_ms * 1e-3 * sr))
    r = 1.0 - math.exp(-1.0 / (rel_ms * 1e-3 * sr))
    e = np.zeros(len(x)); v = 0.0
    ax = np.abs(x)
    for i in range(len(x)):
        c = a if ax[i] > v else r
        v += c * (ax[i] - v)
        e[i] = v
    return e
