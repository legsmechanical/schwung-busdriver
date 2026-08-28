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


# ------------------------------------------------------------------ wav
def read_wav(path):
    with open(path, 'rb') as f:
        b = f.read()
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
    n = len(data) // (ch * bits // 8)
    L = [0.0] * n
    R = [0.0] * n
    for i in range(n):
        for c in range(ch):
            o = (i * ch + c) * (bits // 8)
            if fmt == 3 and bits == 32:
                v = struct.unpack_from('<f', data, o)[0]
            elif bits == 16:
                v = struct.unpack_from('<h', data, o)[0] / 32768.0
            elif bits == 24:
                raw = data[o] | (data[o+1] << 8) | (data[o+2] << 16)
                if raw & 0x800000: raw -= 1 << 24
                v = raw / 8388608.0
            elif bits == 32:
                v = struct.unpack_from('<i', data, o)[0] / 2147483648.0
            else:
                raise SystemExit(f'unsupported wav: fmt {fmt} bits {bits}')
            if c == 0: L[i] = v
            if c == 1 or ch == 1: R[i] = v
    return {'rate': rate, 'bits': bits, 'float': fmt == 3, 'l': L, 'r': R, 'n': n}


def db(x):
    return 20.0 * math.log10(x) if x > 1e-30 else -300.0


def rms(x):
    return math.sqrt(sum(v * v for v in x) / len(x)) if x else 0.0


def align(a, b, search=8192):
    """Integer lag of b relative to a, by correlation over a decimated window.

    Live shifts a render by its plugin-delay compensation, and comparing
    unaligned signals yields a 'difference' that is purely timing."""
    n = min(len(a), len(b))
    step = max(1, n // 8000)
    best, bestv = 0, -1e30
    for lag in range(-search, search + 1):
        acc = 0.0
        for i in range(0, n, step):
            j = i + lag
            if 0 <= j < len(b):
                acc += a[i] * b[j]
        if acc > bestv:
            bestv, best = acc, lag
    return best


def fit_gain_and_residual(a, b, lag):
    """Best scalar g minimising ||a*g - b||, and the residual after removing it.

    Separating the two matters: a constant gain in the dry path is a benign,
    explainable rig property (a fader), while residual AFTER the gain is removed
    is the path actually colouring the signal. Folding them together reports a
    fader as if it were distortion."""
    num = den = 0.0
    for i in range(len(a)):
        j = i + lag
        if 0 <= j < len(b):
            num += a[i] * b[j]
            den += a[i] * a[i]
    g = (num / den) if den > 0 else 0.0
    rn = rd = 0.0
    for i in range(len(a)):
        j = i + lag
        if 0 <= j < len(b):
            d = g * a[i] - b[j]
            rn += d * d
            rd += b[j] * b[j]
    return g, (db(math.sqrt(rn / rd)) if rd > 0 else -300.0)


def active_span(x, floor_db=-120.0):
    """First and last sample above a floor. Live's export renders the whole
    arrangement/loop range, so a 4 s clip in an 8-bar range comes back with
    12 s of trailing silence. That is not warping and must not be reported as
    it — compare on the ACTIVE span, and judge stretch on that span's length."""
    thr = 10 ** (floor_db / 20.0)
    a = next((i for i, v in enumerate(x) if abs(v) > thr), None)
    if a is None:
        return 0, 0
    b = next((i for i in range(len(x) - 1, -1, -1) if abs(x[i]) > thr), a)
    return a, b + 1


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

    print(f'provenance OK — probe {man["probe"]["file"]} sha256 {got[:16]}… '
          f'read from the rendered project')
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
    if res > -90.0:
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
    probe_path, _man = resolve_probe(a.renders, a.project)
    a.probe = probe_path
    """Transfer curve: output plotted against the INPUT SAMPLE that produced it.

    Only valid for a memoryless stage driven by a slow probe. Any hysteresis
    shows up as a curve with width, which is itself the finding — it means the
    stage is not memoryless and a curve is the wrong model for it."""
    probe = read_wav(a.probe)
    files = find_renders(a.renders)
    dry = [f for f in files if 'dry' in f.lower()]
    dref = read_wav(files[dry[0]]) if dry else probe
    lag = best_offset(probe['l'], dref['l']) if dry else 0

    NB = 256
    for f, p in sorted(files.items()):
        if f == (dry[0] if dry else None):
            continue
        w = read_wav(p)
        acc = [0.0] * NB
        cnt = [0] * NB
        spread = [0.0] * NB
        for i in range(len(probe['l'])):
            j = i + lag
            if not (0 <= j < w['n']):
                continue
            x = probe['l'][i]
            k = int((x + 1.0) * 0.5 * (NB - 1))
            k = 0 if k < 0 else (NB - 1 if k >= NB else k)
            acc[k] += w['l'][j]; cnt[k] += 1
        pts = [(2.0 * k / (NB - 1) - 1.0, acc[k] / cnt[k]) for k in range(NB) if cnt[k]]
        out = os.path.join(a.renders, os.path.splitext(f)[0] + '.curve.tsv')
        with open(out, 'w') as fh:
            fh.write('# input\toutput   (transfer curve)\n')
            for x, y in pts:
                fh.write(f'{x:.6f}\t{y:.6f}\n')
        mid = [y for x, y in pts if abs(x) < 0.05]
        top = [y for x, y in pts if x > 0.95]
        print(f'  {f:<44s} {len(pts):3d} pts   '
              f'small-signal slope {(pts[NB//2+8][1]-pts[NB//2-8][1])/(pts[NB//2+8][0]-pts[NB//2-8][0]):.3f}   '
              f'peak out {max(abs(y) for x,y in pts):.4f}   -> {os.path.basename(out)}')
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
