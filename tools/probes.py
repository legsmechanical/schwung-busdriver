#!/usr/bin/env python3
"""probes.py — generate the measurement probe signals.

One probe per stage TYPE, not one drum loop for everything. Drum Buss has an
explicit neutral for every stage, so isolation is exact and we can afford
signals that answer one question each.

All output is 32-bit float stereo WAV at 44100 Hz — the Move's rate. Rendering
or exporting at any other rate skews every filter corner and time constant
uniformly and invisibly.

Usage:  tools/probes.py <outdir>
"""
import math, os, struct, sys, hashlib, json

SR = 44100

# ---------------------------------------------------------------- wav io
def write_wav(path, samples_l, samples_r, sr=SR):
    """32-bit float WAV. Float, not int, because we are measuring transfer
    curves and low-level behaviour — 16-bit quantisation sits exactly where the
    interesting part of a compressor's response lives."""
    n = len(samples_l)
    data = bytearray()
    for i in range(n):
        data += struct.pack('<ff', samples_l[i], samples_r[i])
    hdr = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
    hdr += b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 2, sr, sr * 8, 8, 32)
    hdr += b'data' + struct.pack('<I', len(data))
    with open(path, 'wb') as f:
        f.write(hdr + data)
    return hashlib.sha256(hdr + data).hexdigest()

# ---------------------------------------------------------------- probes
def ramp(seconds=4.0, peak=1.0):
    """Slow bipolar triangle: -peak -> +peak -> -peak, no plateaus.

    ⚠ ONLY VALID FOR A DC-COUPLED PATH. Its fundamental is 1/seconds — 0.25 Hz
    at the default — so anything with a high-pass annihilates it. MEASURED
    2026-08-28: Drum Buss at neutral returns essentially zero for this probe
    (correlation with the input +0.038; output non-zero only at the
    discontinuities), i.e. the device is AC-coupled. Use `swept` for transfer
    curves, and keep this one as the DC-coupling detector it turned out to be.

    ⚠ The first version multiplied the triangle by 2 and clamped, so it sat
    pinned at +-1 for half its duration with a discontinuity in the middle and
    never traversed the range continuously. A curve binned from that probe would
    have been mostly plateau."""
    n = int(seconds * SR)
    out = []
    for i in range(n):
        x = 2.0 * i / (n - 1)                    # 0..2
        v = x if x <= 1.0 else (2.0 - x)         # 0..1..0
        out.append(peak * (2.0 * v - 1.0))       # -1..+1..-1
    return out, out


def swept(seconds=10.0, carrier=300.0, peak=1.0):
    """Amplitude-swept sine — THE transfer-curve probe for a real device.

    A carrier well above any DC blocker or high-pass, amplitude ramped
    0 -> peak -> 0. Every cycle traverses the curve up to the current amplitude,
    so every input level is visited densely, while the carrier sits where no
    high-pass touches it (a 10 Hz one-pole is -0.0 dB at 300 Hz, -32 dB at
    0.25 Hz).

    Sweeping up AND back down also exposes hysteresis: bin the output by input
    level and a memoryless stage gives a LINE, a stage with memory gives a BAND.
    The width is itself the finding — it says a transfer curve is the wrong
    model for that stage, rather than handing back a curve that is quietly an
    average over two different behaviours."""
    n = int(seconds * SR)
    out = []
    for i in range(n):
        t = i / n
        env = (2.0 * t) if t <= 0.5 else (2.0 * (1.0 - t))
        out.append(peak * env * math.sin(2 * math.pi * carrier * i / SR))
    return out, out


def lf_sine(seconds=4.0, hz=2.0, peak=1.0):
    """2 Hz full-scale sine — the same transfer-curve job as the ramp, but it
    traverses every level twice per cycle and is symmetric, so it exposes any
    ASYMMETRY in the shaper directly (a shaper with even harmonics will not
    fold onto itself)."""
    n = int(seconds * SR)
    s = [peak * math.sin(2 * math.pi * hz * i / SR) for i in range(n)]
    return s, s

def sweep(seconds=10.0, f0=20.0, f1=20000.0, peak=0.5):
    """Exponential sine sweep (Farina).

    Deconvolving against the inverse sweep separates the LINEAR impulse
    response and each HARMONIC ORDER into distinct time windows — so one
    render gives Damp's filter shape and Boom's resonance AND their nonlinear
    content, separately. peak 0.5 leaves headroom so a boosting stage has room
    to boost into (see the headroom trap)."""
    n = int(seconds * SR)
    K = seconds * 2 * math.pi * f0 / math.log(f1 / f0)
    L = seconds / math.log(f1 / f0)
    s = []
    for i in range(n):
        t = i / SR
        s.append(peak * math.sin(K * (math.exp(t / L) - 1.0)))
    # 20 ms raised-cosine fades so the endpoints do not ring
    fade = int(0.02 * SR)
    for i in range(fade):
        w = 0.5 - 0.5 * math.cos(math.pi * i / fade)
        s[i] *= w
        s[n - 1 - i] *= w
    return s, s

def inverse_sweep(seconds=10.0, f0=20.0, f1=20000.0):
    """The Farina inverse filter: the sweep time-reversed with a 1/f amplitude
    envelope, so convolution with the recording yields the impulse response."""
    fwd, _ = sweep(seconds, f0, f1, peak=1.0)
    n = len(fwd)
    L = seconds / math.log(f1 / f0)
    inv = []
    for i in range(n):
        t = (n - 1 - i) / SR
        inv.append(fwd[n - 1 - i] * math.exp(-t / L))
    return inv, inv

def bursts(levels_db=(-60, -48, -36, -30, -24, -18, -12, -6, -3, 0),
           hz=200.0, on=0.5, off=0.5):
    """Sine bursts at a level ladder, each with silence after it.

    The static gain curve of a compressor comes straight off this: measure the
    steady level inside each burst, in against out. The silence lets the
    detector fully release between levels, so each burst is independent rather
    than riding the previous one's gain reduction."""
    l = []
    for db in levels_db:
        a = 10 ** (db / 20.0)
        for i in range(int(on * SR)):
            env = 1.0
            f = int(0.005 * SR)                      # 5 ms edges, no clicks
            if i < f: env = i / f
            if i > on * SR - f: env = (on * SR - i) / f
            l.append(a * env * math.sin(2 * math.pi * hz * i / SR))
        l.extend([0.0] * int(off * SR))
    return l, l

def steps(hz=200.0, lo_db=-40.0, hi_db=-6.0, hold=1.0, reps=3):
    """Hard level steps up and down on a steady tone.

    Attack time is read off the fall of the output after a step UP; release off
    the recovery after a step DOWN. A drum loop cannot give this cleanly
    because level, spectrum and timing all move at once."""
    lo, hi = 10 ** (lo_db / 20.0), 10 ** (hi_db / 20.0)
    l = []
    ph = 0.0
    dph = 2 * math.pi * hz / SR
    for _ in range(reps):
        for a in (lo, hi, lo):
            for _ in range(int(hold * SR)):
                l.append(a * math.sin(ph)); ph += dph
    return l, l

def two_tone(seconds=4.0, lo=60.0, hi=6000.0, peak=0.3):
    """A low and a high tone together — the discriminator for whether Crunch is
    full-band or band-limited, and where its corner sits. A full-scale LF sine
    alone cannot see a mid-high-only effect at all."""
    n = int(seconds * SR)
    s = [peak * (math.sin(2 * math.pi * lo * i / SR) +
                 math.sin(2 * math.pi * hi * i / SR)) for i in range(n)]
    return s, s

def hits(seconds=4.0, bpm=120.0, peak=0.25):
    """Synthetic drum hits: kick body + click, at several decay lengths.

    For the transient stage, and for validation. Deliberately quiet — a stage
    that can boost +15 dB needs room to boost into, or the measurement reads
    the clipping ceiling instead of the control (this exact mistake made our
    own harness report a symmetric control as +6.7/-13.7 dB)."""
    n = int(seconds * SR)
    out = [0.0] * n
    step = int(SR * 60.0 / bpm / 2)
    decays = [0.08, 0.20, 0.45, 0.20]
    for k, start in enumerate(range(0, n - step, step)):
        d = decays[k % len(decays)]
        for i in range(min(step, n - start)):
            t = i / SR
            env = math.exp(-t / d)
            body = math.sin(2 * math.pi * 90.0 * t)
            click = math.exp(-t / 0.002) * math.sin(2 * math.pi * 3000.0 * t)
            out[start + i] += peak * env * (0.8 * body + 0.5 * click)
    out = [max(-1.0, min(1.0, v)) for v in out]
    return out, out

PROBES = {
    'ramp':       (ramp,        'DC-coupling detector (sub-Hz: NOT a curve probe)'),
    'swept':      (swept,       'transfer curve — amplitude-swept 300 Hz carrier'),
    'lfsine':     (lf_sine,     'transfer curve + asymmetry'),
    'sweep':      (sweep,       'Farina: linear IR + harmonic orders'),
    'invsweep':   (inverse_sweep,'Farina inverse filter (not for rendering)'),
    'bursts':     (bursts,      'compressor static gain curve'),
    'steps':      (steps,       'compressor attack/release times'),
    'twotone':    (two_tone,    'Crunch band split'),
    'hits':       (hits,        'transient stage + validation'),
}

ALIGN_DB = -30.0
GAP = 0.5


def align_tone(seconds=1.0, hz=300.0, db_level=ALIGN_DB):
    """Quiet 300 Hz tone at the head of every suite — the ALIGNMENT segment.

    Alignment is the one thing that must work at every parameter cell, and
    correlating a distorted output against a clean input does not: measured
    full-length across one drive ladder it reported 0, 0, 0, 129 and 1305
    samples of latency, and the bad lag silently INVERTED the extracted curve.
    A segment quiet enough to keep every setting quasi-linear makes alignment
    reliable by construction instead of by luck."""
    n = int(seconds * SR)
    a = 10 ** (db_level / 20.0)
    s = []
    for i in range(n):
        env = 1.0
        f = int(0.01 * SR)
        if i < f: env = i / f
        if i > n - f: env = (n - i) / f
        s.append(a * env * math.sin(2 * math.pi * hz * i / SR))
    return s, s


def align_chirp(seconds=0.5, f0=200.0, f1=8000.0, db_level=-30.0):
    """Short BROADBAND chirp — the v2 alignment segment.

    v1 used a −30 dBFS 300 Hz tone. Quiet was right (every cell stays
    quasi-linear there), single-frequency was not: a tone cannot distinguish a
    polarity flip from a half-period shift, so its candidate lags came out 73.5
    samples apart with alternating sign and the first curve extraction was
    silently inverted. A chirp has no period to alias against, so lag AND
    polarity fall out of one correlation."""
    n = int(seconds * SR)
    a = 10 ** (db_level / 20.0)
    L = seconds / math.log(f1 / f0)
    K = seconds * 2 * math.pi * f0 / math.log(f1 / f0)
    s = []
    for i in range(n):
        t = i / SR
        env = 1.0
        f = int(0.005 * SR)
        if i < f: env = i / f
        if i > n - f: env = (n - i) / f
        s.append(a * env * math.sin(K * (math.exp(t / L) - 1.0)))
    return s, s


def steps2k(**kw):
    """Level steps on a 2 kHz carrier — 0.5 ms per cycle.

    v1's steps probe used 200 Hz = 5.0 ms per cycle, which is a hard floor on any
    envelope-derived time constant, and the compressor's attack is below it. Ten
    times the resolution here."""
    return steps(hz=2000.0, **kw)


def swept_at(carrier):
    """Amplitude-swept sine at one carrier — a family of them separates the
    SHAPER from the FILTERING around it.

    At a single carrier, `soft` at high drive showed a large phase-dependent
    spread (sd 0.217 at |x|=0.98 against `hard`'s 0.005), so a static curve is
    insufficient there. Repeating the same amplitude sweep at several carriers
    says whether the fold law itself is frequency dependent or whether only the
    surrounding filtering is."""
    def f(seconds=6.0, peak=1.0):
        n = int(seconds * SR)
        out = []
        for i in range(n):
            t = i / n
            env = (2.0 * t) if t <= 0.5 else (2.0 * (1.0 - t))
            out.append(peak * env * math.sin(2 * math.pi * carrier * i / SR))
        return out, out
    return f


PROBES2 = {
    'align2':   (align_chirp,        'broadband chirp: lag AND polarity, unambiguous'),
    'steps2k':  (steps2k,            'compressor times, 2 kHz carrier (0.5 ms/cycle)'),
    'sw100':    (swept_at(100.0),    'fold law @ 100 Hz'),
    'sw300':    (swept_at(300.0),    'fold law @ 300 Hz (matches the v1 suite)'),
    'sw1k':     (swept_at(1000.0),   'fold law @ 1 kHz'),
    'sw3k':     (swept_at(3000.0),   'fold law @ 3 kHz'),
    'hits':     (hits,               'transient stage + where it sits in the chain'),
}
SUITE2_ORDER = ['align2', 'steps2k', 'sw100', 'sw300', 'sw1k', 'sw3k', 'hits']


SUITE_ORDER = ['align', 'swept', 'twotone', 'sweep', 'bursts', 'steps', 'hits', 'ramp']


def build_named_suite(outdir, order, table, fname):
    segs, offsets = [], {}
    gap = [0.0] * int(GAP * SR)
    for name in order:
        fn = table[name][0] if name in table else PROBES[name][0]
        l, _ = fn()
        offsets[name] = {'start': len(segs), 'frames': len(l),
                         'seconds': round(len(l) / SR, 4)}
        segs.extend(l); segs.extend(gap)
    path = os.path.join(outdir, fname)
    h = write_wav(path, segs, segs)
    return path, h, offsets, len(segs)


def build_suite(outdir):
    """One WAV holding every probe end to end, with silence between them.

    So that ONE Live export can cover the whole campaign: each track is a
    parameter cell, each track carries this whole suite, and the analysis slices
    it by the offsets recorded here. Gaps let the device's state (compressor
    release, reverb tail) settle so one probe cannot contaminate the next."""
    segs, offsets = [], {}
    gap = [0.0] * int(GAP * SR)
    for name in SUITE_ORDER:
        fn = align_tone if name == 'align' else PROBES[name][0]
        l, _ = fn()
        offsets[name] = {'start': len(segs), 'frames': len(l),
                         'seconds': round(len(l) / SR, 4)}
        segs.extend(l)
        segs.extend(gap)
    path = os.path.join(outdir, 'suite.wav')
    h = write_wav(path, segs, segs)
    return path, h, offsets, len(segs)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else 'rig/probes'
    os.makedirs(outdir, exist_ok=True)
    manifest = {'sample_rate': SR, 'format': 'wav 32-bit float stereo', 'probes': {}}
    for name, (fn, why) in PROBES.items():
        l, r = fn()
        path = os.path.join(outdir, name + '.wav')
        h = write_wav(path, l, r)
        manifest['probes'][name] = {
            'file': name + '.wav', 'sha256': h, 'frames': len(l),
            'seconds': round(len(l) / SR, 4),
            'peak': round(max(abs(v) for v in l), 6), 'purpose': why,
        }
        print(f'{name:10s} {len(l)/SR:6.2f}s  peak {max(abs(v) for v in l):.3f}  {h[:16]}…  {why}')
    p2, h2, off2, tot2 = build_named_suite(outdir, SUITE2_ORDER, PROBES2, 'suite2.wav')
    manifest['suite2'] = {'file': 'suite2.wav', 'sha256': h2, 'frames': tot2,
                          'seconds': round(tot2 / SR, 3), 'gap_seconds': GAP,
                          'align_segment': 'align2', 'offsets': off2}
    print(f'\nsuite2.wav {tot2/SR:6.2f}s  {h2[:16]}…  ({len(off2)} segments)')
    for k, v in off2.items():
        print(f'   {k:9s} @ {v["start"]/SR:6.2f}s  {v["seconds"]:5.2f}s')

    path, h, offsets, total = build_suite(outdir)
    manifest['suite'] = {'file': 'suite.wav', 'sha256': h, 'frames': total,
                         'seconds': round(total / SR, 3), 'gap_seconds': GAP,
                         'align_segment': 'align', 'offsets': offsets}
    print(f'\nsuite.wav  {total/SR:6.2f}s  {h[:16]}…  '
          f'({len(offsets)} segments, {GAP}s gaps)')
    for k, v in offsets.items():
        print(f'   {k:9s} @ {v["start"]/SR:6.2f}s  {v["seconds"]:5.2f}s')
    with open(os.path.join(outdir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f'\nwrote {len(PROBES)} probes + manifest.json to {outdir}/')
    print('NOTE: every reported number cites the source by SHA-256, never by filename.')

if __name__ == '__main__':
    main()
