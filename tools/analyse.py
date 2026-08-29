#!/usr/bin/env python3
"""analyse.py — read a rendered ladder and measure it.

The SAME code runs over Live's renders and over ours. That is the whole point:
a difference between the two sides must come from the DSP, not from two
different analysis paths, which is how fidelity campaigns usually fool
themselves.

Commands:
  gate    <renders/> <probe.wav>   phase-0: does the rig lie?
  curve   <renders/> <probe.wav>   transfer curves from a ramp/lfsine ladder
"""
import argparse, hashlib, json, math, os, struct, sys
import numpy as np


# ------------------------------------------------------------------ wav
def read_wav(path):
    b = open(path, 'rb').read()
    if b[:4] != b'RIFF' or b[8:12] != b'WAVE':
        raise SystemExit(f'not a WAV: {path}')
    pos, fmt, ch, rate, bits, data = 12, None, None, None, None, None
    while pos + 8 <= len(b):
        cid = b[pos:pos+4]; ln = struct.unpack('<I', b[pos+4:pos+8])[0]
        if cid == b'fmt ':
            fmt, ch, rate = struct.unpack('<HHI', b[pos+8:pos+16])
            bits = struct.unpack('<H', b[pos+22:pos+24])[0]
        elif cid == b'data':
            data = b[pos+8:pos+8+ln]
        pos += 8 + ln + (ln & 1)
    if fmt == 3 and bits == 32:
        a = np.frombuffer(data, dtype='<f4')
    elif bits == 16:
        a = np.frombuffer(data, dtype='<i2').astype(np.float64) / 32768.0
    elif bits == 32:
        a = np.frombuffer(data, dtype='<i4').astype(np.float64) / 2147483648.0
    else:
        raise SystemExit(f'unsupported wav: fmt {fmt} bits {bits}')
    a = a.astype(np.float64).reshape(-1, ch)
    return {'rate': rate, 'bits': bits, 'float': fmt == 3, 'n': a.shape[0],
            'l': a[:, 0], 'r': a[:, min(1, ch-1)]}


def db(x):
    return 20.0 * math.log10(x) if x > 1e-30 else -300.0


def rms(x):
    x = np.asarray(x)
    return float(np.sqrt((x * x).mean())) if x.size else 0.0


def align(a, b, search=8192):
    """Integer lag of b relative to a, by FFT cross-correlation. Live shifts a
    render by its plugin-delay compensation, and comparing unaligned signals
    yields a 'difference' that is purely timing."""
    a = np.asarray(a); b = np.asarray(b)
    n = 1 << int(np.ceil(np.log2(max(len(a), len(b)) + search + 1)))
    A = np.fft.rfft(a, n); B = np.fft.rfft(b, n)
    cc = np.fft.irfft(B * np.conj(A), n)
    cc = np.concatenate([cc[-search:], cc[:search + 1]])
    return int(np.argmax(cc)) - search


def fit_gain_and_residual(a, b, lag):
    """Best scalar g minimising ||a*g - b||, and the residual after removing it.

    Separating the two matters: a constant gain in the dry path is a benign,
    explainable rig property (a fader), while residual AFTER the gain is removed
    is the path actually colouring the signal."""
    a = np.asarray(a); b = np.asarray(b)
    if lag >= 0:
        x, y = a[:len(b) - lag], b[lag:lag + len(a)]
    else:
        x, y = a[-lag:], b[:len(a) + lag]
    m = min(len(x), len(y)); x, y = x[:m], y[:m]
    g = float(x @ y / (x @ x)) if (x @ x) else 0.0
    r = g * x - y
    return g, (db(float(np.sqrt((r * r).mean()) / np.sqrt((y * y).mean())))
               if (y @ y) else -300.0)


def active_span(x, floor_db=-120.0):
    """First and last sample above a floor. Live's export renders the whole
    arrangement/loop range, so a 4 s clip in an 8-bar range comes back with
    12 s of trailing silence. That is not warping and must not be reported as
    it — compare on the ACTIVE span, and judge stretch on that span's length."""
    x = np.asarray(x)
    nz = np.flatnonzero(np.abs(x) > 10 ** (floor_db / 20.0))
    return (0, 0) if nz.size == 0 else (int(nz[0]), int(nz[-1]) + 1)


def find_renders(d):
    out = {}
    for f in sorted(os.listdir(d)):
        if f.lower().endswith(('.wav', '.aif', '.aiff')):
            out[f] = os.path.join(d, f)
    return out


# ------------------------------------------------------------------ gate
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def resolve_probe(renders_dir, project_dir):
    """Resolve the probe from the SET PROJECT Live actually read, not from a
    loose path the caller supplies.

    The generator copies the probe into the project's Samples/Imported/, so that
    copy IS what was rendered. Pointing the gate at tools/probes output instead
    lets the probe be regenerated out from under an existing export — which
    happened here: probes.py was re-run after a bug was found in the ramp, and
    the gate then compared a render against a signal that never produced it, and
    also 'verified' provenance against a manifest that had been rewritten in the
    same regeneration. A filename is not provenance, and neither is a manifest
    that can be rewritten independently of the renders.

    Mtimes are compared as a second guard: if the project is NEWER than the
    renders, the Set was regenerated after exporting and the pairing is stale."""
    man_path = os.path.join(project_dir, 'rig-manifest.json')
    if not os.path.exists(man_path):
        raise SystemExit(f'no rig-manifest.json in {project_dir}')
    with open(man_path) as f:
        man = json.load(f)
    probe = os.path.join(project_dir, 'Samples', 'Imported', man['probe']['file'])
    if not os.path.exists(probe):
        raise SystemExit(f'probe copy missing from the project: {probe}')

    got = sha256_file(probe)
    want = man['probe']['sha256']
    if got != want:
        raise SystemExit(f'🔴 project probe {got[:16]}… != manifest {want[:16]}…')

    rend = [os.path.join(renders_dir, f) for f in os.listdir(renders_dir)
            if f.lower().endswith(('.wav', '.aif', '.aiff'))]
    if not rend:
        raise SystemExit(f'no renders in {renders_dir}')
    newest_render = max(os.path.getmtime(f) for f in rend)
    if os.path.getmtime(man_path) > newest_render + 1:
        raise SystemExit(
            f'🔴 STALE PAIRING — the Set project was regenerated AFTER these '
            f'renders were exported.\n'
            f'   project  {os.path.getmtime(man_path):.0f}\n'
            f'   renders  {newest_render:.0f}\n'
            f'   Re-export from the current Set before analysing.')

    # stderr: this is diagnostic, and it must not land in anything that
    # captures stdout — it contaminated a generated C header once.
    print(f'provenance OK — probe {man["probe"]["file"]} sha256 {got[:16]}… '
          f'read from the rendered project', file=sys.stderr)
    return probe, man


def cmd_gate(a):
    probe_path, man = resolve_probe(a.renders, a.project)
    probe = read_wav(probe_path)
    print(f'probe: {probe["n"]} frames @ {probe["rate"]} Hz, '
          f'{"float" if probe["float"] else "int"}{probe["bits"]}\n')

    files = find_renders(a.renders)
    if not files:
        raise SystemExit(f'no renders in {a.renders}')

    dry = [f for f in files if 'dry' in f.lower()]
    if not dry:
        raise SystemExit('no track named *dry* — the reference is missing')
    dref = read_wav(files[dry[0]])

    problems = []
    if dref['rate'] != 44100:
        problems.append(f'🔴 render is {dref["rate"]} Hz, not 44100 — every filter '
                        f'corner and time constant would be off by '
                        f'{100*(dref["rate"]/44100-1):+.1f}%')
    if dref['bits'] < 32:
        problems.append(f'⚠ render is {dref["bits"]}-bit, not 32 — quantisation '
                        f'sits where the low-level behaviour is')

    pa, pb = active_span(probe['l'])
    da, dbn = active_span(dref['l'])
    plen, dlen = pb - pa, dbn - da
    src = probe['l'][pa:pb]
    ren = dref['l'][da:dbn]
    lag = align(src, ren)
    gain, res = fit_gain_and_residual(src, ren, lag)
    print(f'DRY REFERENCE  {dry[0]}')
    print(f'  frames         {dref["n"]} total, {dlen} active '
          f'(probe {probe["n"]} / {plen} active)')
    print(f'  trailing pad   {(dref["n"]-dbn)/dref["rate"]:.3f}s '
          f'(Live renders the whole export range, not the clip)')
    print(f'  rate/bits      {dref["rate"]} Hz / {dref["bits"]}-bit '
          f'{"float" if dref["float"] else "int"}')
    railed = abs(lag) >= 8191
    print(f'  alignment lag  {lag} samples (within the active span)'
          + ('   🔴 RAILED at the search limit — alignment did not converge, so '
             'every number below is suspect' if railed else ''))
    print(f'  path gain      {db(abs(gain)):+.3f} dB  (scalar best fit)')
    print(f'  residual       {res:.1f} dB  (after removing that gain)')

    # Length drift is the warp tell: a warped clip is time-stretched to tempo.
    if plen and abs(dlen - plen) > probe['rate'] * 0.01:
        problems.append(f'🔴 ACTIVE length differs from the probe by '
                        f'{(dlen-plen)/probe["rate"]:+.4f}s ({dlen/plen:.4f}x) — a '
                        f'warped clip does exactly this. Trailing silence alone is '
                        f'fine and is not this check.')
    # -80, not -90. MEASURED 2026-08-28: Live's own bypassed playback path
    # leaves a MULTIPLICATIVE residual at about -85 dB relative to instantaneous
    # signal — noise-like (crest 14.2 dB), correlation with the signal envelope
    # +1.0000, ratio IQR 0.00 dB, i.e. ~14-bit relative precision. It is not
    # ours and cannot be removed from this side. Everything this campaign fits
    # (transfer curves, filter magnitudes, compression curves) lives above
    # -60 dBFS, and our own int16 output floor is -90 dBFS, so the artefact sits
    # ~20 dB below the measurement floor. ⚠ If a measurement ever lands within
    # 20 dB of this, revisit rather than trusting it.
    if res > -80.0:
        problems.append(f'🔴 dry path is COLOURING the signal: residual {res:.1f} dB '
                        f'after removing a scalar gain (want < -90). Something in '
                        f'the path is not a constant gain — do not fit anything '
                        f'until it is explained.')
    if abs(db(abs(gain))) > 0.01:
        problems.append(f'⚠ dry path gain is {db(abs(gain)):+.3f} dB, not unity. '
                        f'Renders are POST-FADER; check the track fader. It '
                        f'cancels against the dry reference, but a rig should not '
                        f'depend on an error cancelling.')

    print(f'\nOTHER TRACKS (level vs dry, sanity only)')
    for f, p in files.items():
        if f == dry[0]:
            continue
        w = read_wav(p)
        wa, wb = active_span(w['l'])
        seg = w['l'][da:dbn] if wb > wa else w['l']
        ref = dref['l'][da:dbn]
        print(f'  {f:<44s} {db(rms(seg)) - db(rms(ref)):+7.2f} dB  '
              f'peak {max((abs(v) for v in seg), default=0):.4f}')

    print()
    if problems:
        for p in problems:
            print(p)
        print('\nGATE: FAIL')
        return 1
    print('GATE: PASS — the dry path is transparent; measurements can be trusted '
          'to the extent the dry null is.')
    return 0


# ------------------------------------------------------------------ curve
def cmd_curve(a):
    """Transfer curve: output binned by the INPUT SAMPLE that produced it.

    Valid only for a memoryless stage. Sweeping the probe up AND down means each
    input level is visited twice; if the stage has memory the two visits differ
    and the bin acquires WIDTH. That width is reported, and it is the finding —
    a wide band says a transfer curve is the wrong model, rather than handing
    back a curve that is quietly an average of two behaviours."""
    probe_path, man = resolve_probe(a.renders, a.project)
    probe = read_wav(probe_path)
    files = find_renders(a.renders)
    dry = [f for f in files if 'dry' in f.lower()]
    dref = read_wav(files[dry[0]])
    da, dbn = active_span(dref['l'])
    pa, pb = active_span(probe['l'])
    lag = align(probe['l'][pa:pb], dref['l'][da:dbn]) + da - pa

    NB = 401
    edges = np.linspace(-1.0, 1.0, NB + 1)
    print(f'{"track":<26s} {"pts":>4s} {"lag":>5s} {"slope@0":>8s} {"out@+1":>8s} '
          f'{"out@-1":>8s} {"asym":>7s} {"width":>8s}')
    for f, path in sorted(files.items()):
        if f == dry[0]:
            continue
        w = read_wav(path)
        x = probe['l'][pa:pb]
        # ⚠ Align EVERY track independently. Reusing the dry track's lag assumes
        # the device adds no latency; at 300 Hz a half-period error is only 73
        # samples and it inverts the curve — the first run of this reported
        # out@+1 = -0.75, which reads as a phase-inverting saturator and is
        # really just 73 samples of unmodelled delay.
        # ⚠ Align on the LOW-LEVEL HEAD, and chain through the dry reference.
        #
        # Correlating a heavily distorted output against the clean input does not
        # give a trustworthy peak: measured full-length, the same device reported
        # 0, 0, 0, 129 and 1305 samples of latency across a drive ladder, which is
        # not a thing a device can do. On the first 2 s — where the swept probe is
        # still quiet and every drive setting is in its quasi-linear region — all
        # five agree on -18 samples (0.41 ms), and that is the real number.
        HEAD = 2 * probe['rate']
        lw = align(dref['l'][da:da + HEAD], w['l'][da:da + HEAD], search=4096)
        off = pa + lag + lw
        xs = x
        if off < 0:                      # device runs EARLY (Live over-compensates
            xs = x[-off:]                # its reported latency); trim the input
            off = 0                      # rather than reading before the file
        y = w['l'][off:off + len(xs)]
        m = min(len(xs), len(y)); x2, y = xs[:m], y[:m]
        if m < len(xs) // 2:
            print(f'  {f}: alignment failed (off {off}, overlap {m}) — skipped')
            continue
        lg = lw
        x = x2

        idx = np.clip(np.digitize(x, edges) - 1, 0, NB - 1)
        cnt = np.bincount(idx, minlength=NB)
        sm  = np.bincount(idx, weights=y, minlength=NB)
        sq  = np.bincount(idx, weights=y * y, minlength=NB)
        ok = cnt > 20
        centres = 0.5 * (edges[:-1] + edges[1:])
        mean = np.zeros(NB); mean[ok] = sm[ok] / cnt[ok]
        var = np.zeros(NB); var[ok] = np.maximum(sq[ok] / cnt[ok] - mean[ok] ** 2, 0)
        sd = np.sqrt(var)

        out = os.path.join(a.renders, os.path.splitext(f)[0] + '.curve.tsv')
        with open(out, 'w') as fh:
            fh.write(f'# transfer curve from {os.path.basename(probe_path)} '
                     f'sha256 {man["probe"]["sha256"]}\n')
            fh.write('# input\toutput\tsd\tn\n')
            for k in np.flatnonzero(ok):
                fh.write(f'{centres[k]:.6f}\t{mean[k]:.8f}\t{sd[k]:.8f}\t{cnt[k]}\n')

        c = np.flatnonzero(ok)
        mid = c[np.argmin(np.abs(centres[c]))]
        lo_i, hi_i = mid - 10, mid + 10
        slope = (mean[hi_i] - mean[lo_i]) / (centres[hi_i] - centres[lo_i])
        top = mean[c[-1]]; bot = mean[c[0]]
        asym = top + bot                       # 0 for an odd (symmetric) curve
        width = db(float(np.mean(sd[ok] / (np.abs(mean[ok]) + 1e-6))))
        print(f'{f[-26:]:<26s} {len(c):>4d} {lg:>5d} {slope:>8.4f} {top:>8.4f} '
              f'{bot:>8.4f} {asym:>+7.4f} {width:>7.1f}dB')
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('gate'); g.add_argument('renders'); g.add_argument('project')
    c = sub.add_parser('curve'); c.add_argument('renders'); c.add_argument('project')
    a = ap.parse_args()
    sys.exit({'gate': cmd_gate, 'curve': cmd_curve}[a.cmd](a))


if __name__ == '__main__':
    main()
