#!/usr/bin/env python3
"""make_rig_set.py — generate a Live Set that renders one whole parameter ladder.

Drum Buss only runs inside Live, so Live has to render every target. But .als is
gzipped XML, so a ladder does not need N exports: it needs ONE Set with N
tracks, each carrying the same probe clip and one Drum Buss at one parameter
cell. Josh opens it and runs Export → All Individual Tracks, once.

Track 1 is ALWAYS the dry reference (Drum Buss off). Every measurement is
relative to it, so Live's own gain staging and any export-path colouring cancel.

Two source files are read from the machine, never redistributed:
  * the base Set — supplies Set/track/mixer XML and a real <DrumBuss> block
  * a Live Lessons Set — supplies a 12.3-era arrangement <AudioClip>, unwarped

Usage:
  tools/make_rig_set.py --probe rig/probes/ramp.wav \
      --param DriveAmount --values 0,0.25,0.5,0.75,1.0 \
      --fixed DriveType=0 --out rig/sets/drive_soft
"""
import argparse, copy, gzip, hashlib, json, os, re, shutil, sys, wave
import xml.etree.ElementTree as ET

# ⚠ Element names carry attributes: the device is <DrumBuss Id="N">, never
# <DrumBuss>. String-searching for the latter reports ZERO in a Set that plainly
# contains one. Everything here goes through a real XML parser for that reason.
DEVICE = 'DrumBuss'

BASE_SET = 'Source set Project/Source set.als'
LESSON_GLOB = ('/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/'
               'Core Library/Lessons/Sets/Driver Error Compensation.als')

# Authoritative ranges, from Live's own stock .adv presets. A value outside
# these is a bug in the caller, not something to silently clamp.
RANGES = {
    'EnableCompression': ('bool', None, None),
    'DriveAmount':       ('float', 0.0, 1.0),
    'DriveType':         ('int',   0,   2),
    'CrunchAmount':      ('float', 0.0, 1.0),
    'DampingFrequency':  ('float', 500.0, 20000.0),
    'TransientShaping':  ('float', -1.0, 1.0),
    'BoomAmount':        ('float', 0.0, 1.0),
    'BoomFrequency':     ('float', 30.0, 90.0),
    'BoomDecay':         ('float', 0.0, 1.0),
    'BoomAudition':      ('bool', None, None),
    'InputTrim':         ('float', 0.0003162277571, 1.0),
    'OutputGain':        ('float', 0.009999999776, 1.41253757),
    'DryWet':            ('float', 0.0, 1.0),
}
# Every stage at rest. The dry reference additionally switches the device off.
NEUTRAL = {
    'EnableCompression': False, 'DriveAmount': 0.0, 'DriveType': 0,
    'CrunchAmount': 0.0, 'DampingFrequency': 20000.0, 'TransientShaping': 0.0,
    'BoomAmount': 0.0, 'BoomFrequency': 50.0, 'BoomDecay': 1.0,
    'BoomAudition': False, 'InputTrim': 1.0, 'OutputGain': 1.0, 'DryWet': 1.0,
}


def load(path):
    return ET.fromstring(gzip.open(path, 'rb').read().decode('utf-8'))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def wav_info(path):
    with wave.open(path, 'rb') as w:
        return w.getnframes(), w.getframerate()
    # NB: 32-bit float WAVs are not readable by `wave`; handled by the caller.


def wav_info_any(path):
    """Frames + rate for PCM or IEEE-float WAV (the `wave` module rejects float)."""
    with open(path, 'rb') as f:
        d = f.read(1 << 16)
    if d[:4] != b'RIFF' or d[8:12] != b'WAVE':
        raise SystemExit(f'not a WAV: {path}')
    pos, rate, ch, bits, frames = 12, None, None, None, None
    size = os.path.getsize(path)
    while pos + 8 <= len(d):
        cid, csz = d[pos:pos+4], int.from_bytes(d[pos+4:pos+8], 'little')
        if cid == b'fmt ':
            ch = int.from_bytes(d[pos+10:pos+12], 'little')
            rate = int.from_bytes(d[pos+12:pos+16], 'little')
            bits = int.from_bytes(d[pos+22:pos+24], 'little')
        elif cid == b'data':
            frames = csz // (ch * bits // 8)
            break
        pos += 8 + csz + (csz & 1)
    if frames is None:                       # data chunk beyond our read
        frames = (size - pos - 8) // (ch * bits // 8)
    return frames, rate, ch, bits


def find_device(track):
    """The <DrumBuss Id="N"> inside a track's device chain."""
    for dc in track.iter('DeviceChain'):
        for devs in dc.findall('Devices'):
            d = devs.find(DEVICE)
            if d is not None:
                return d
    return None


def set_param(dev, name, value):
    el = dev.find(name)
    if el is None:
        raise SystemExit(f'{name}: not present in the device block')
    man = el.find('Manual')
    if man is None:
        raise SystemExit(f'{name}: no <Manual>')
    kind, lo, hi = RANGES[name]
    if kind == 'bool':
        man.set('Value', 'true' if value else 'false')
    else:
        v = float(value)
        if not (lo - 1e-9 <= v <= hi + 1e-9):
            raise SystemExit(f'{name}={v} outside Live\'s own range {lo}..{hi}')
        man.set('Value', repr(int(v)) if kind == 'int' else repr(v))


def offset_ids(el, delta):
    """Live keys automation and modulation by Id. Cloned tracks must not reuse
    them, or two tracks point at one target and the Set is subtly wrong."""
    for e in el.iter():
        for k in ('Id',):
            if k in e.attrib and e.attrib[k].lstrip('-').isdigit():
                e.set(k, str(int(e.attrib[k]) + delta))
        for k in ('Pointee', 'LomId'):
            pass  # values, not ids; left alone deliberately
    for p in el.iter('Pointee'):
        if 'Id' in p.attrib and p.attrib['Id'].isdigit():
            pass  # already handled above


def set_track_name(track, name):
    n = track.find('Name')
    n.find('EffectiveName').set('Value', name)
    n.find('UserName').set('Value', name)


def install_clip(track, clip_template, rel_path, abs_path, frames, rate, beats):
    """Put ONE unwarped clip at bar 1 of this track's arrangement."""
    events = None
    for seq in track.iter('MainSequencer'):
        for samp in seq.findall('Sample'):
            for aa in samp.iter('ArrangerAutomation'):
                events = aa.find('Events')
                break
    if events is None:
        raise SystemExit('no ArrangerAutomation/Events on the track')
    for child in list(events):
        events.remove(child)

    clip = copy.deepcopy(clip_template)
    clip.set('Id', '1')
    clip.set('Time', '0')

    def put(tag, value, root=clip):
        e = root.find('.//' + tag)
        if e is not None:
            e.set('Value', value)

    # 🔴 Warp OFF. A warped clip is time-stretched to the Set tempo, so every
    # time constant and transfer curve measured would belong to Live's warp
    # engine, not to Drum Buss. The analysis re-checks rendered length anyway.
    put('IsWarped', 'false')
    put('CurrentStart', '0')
    put('CurrentEnd', repr(beats))
    put('LoopStart', '0')
    put('LoopEnd', repr(beats))
    put('StartRelative', '0')
    put('HiQ', 'false')          # no resampling niceties in the measurement path
    for lp in clip.iter('Loop'):
        for t, v in (('LoopStart', '0'), ('LoopEnd', repr(beats)),
                     ('LoopOn', 'false'), ('HiddenLoopStart', '0'),
                     ('HiddenLoopEnd', repr(beats))):
            e = lp.find(t)
            if e is not None:
                e.set('Value', v)

    for sr in clip.iter('SampleRef'):
        fr = sr.find('FileRef')
        if fr is not None:
            for t, v in (('RelativePath', rel_path), ('Path', abs_path),
                         ('RelativePathType', '3'), ('LivePackName', ''),
                         ('LivePackId', ''), ('OriginalFileSize', str(os.path.getsize(abs_path)))):
                e = fr.find(t)
                if e is not None:
                    e.set('Value', v)
        for t, v in (('DefaultDuration', str(frames)), ('DefaultSampleRate', str(rate))):
            e = sr.find(t)
            if e is not None:
                e.set('Value', v)
    events.append(clip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True, help='probe WAV to feed every cell')
    ap.add_argument('--param', help='parameter to sweep')
    ap.add_argument('--values', help='comma-separated values for --param')
    ap.add_argument('--fixed', action='append', default=[],
                    help='Name=value held constant on every cell (repeatable)')
    ap.add_argument('--out', required=True, help='output project dir (no extension)')
    ap.add_argument('--base', default=BASE_SET)
    ap.add_argument('--tempo', type=float, default=120.0)
    a = ap.parse_args()

    frames, rate, ch, bits = wav_info_any(a.probe)
    if rate != 44100:
        raise SystemExit(f'🔴 probe is {rate} Hz. The Move runs 44100; a rate '
                         f'mismatch skews every corner and time constant.')
    beats = frames / rate * (a.tempo / 60.0)

    root = load(a.base)
    tracks_el = root.find('.//Tracks')
    template = tracks_el.find('AudioTrack')
    if template is None:
        raise SystemExit('base Set has no AudioTrack')
    if find_device(template) is None:
        raise SystemExit(f'base Set\'s audio track has no {DEVICE} device')

    if not os.path.exists(LESSON_GLOB):
        raise SystemExit(f'need the Live Lessons Set for the arrangement-clip '
                         f'XML: {LESSON_GLOB}')
    lroot = load(LESSON_GLOB)
    clip_template = next(lroot.iter('AudioClip'), None)
    if clip_template is None:
        raise SystemExit('no AudioClip in the lesson Set')

    fixed = {}
    for f in a.fixed:
        k, v = f.split('=', 1)
        if k not in RANGES:
            raise SystemExit(f'unknown parameter {k}')
        fixed[k] = (v.lower() == 'true') if RANGES[k][0] == 'bool' else float(v)

    cells = [('dry', None)]
    if a.param:
        if a.param not in RANGES:
            raise SystemExit(f'unknown parameter {a.param}')
        for v in a.values.split(','):
            val = (v.lower() == 'true') if RANGES[a.param][0] == 'bool' else float(v)
            cells.append((f'{a.param}_{v}', val))
    else:
        cells.append(('neutral', None))

    # project scaffolding
    proj = a.out + ' Project'
    os.makedirs(os.path.join(proj, 'Samples', 'Imported'), exist_ok=True)
    probe_name = os.path.basename(a.probe)
    dst = os.path.join(proj, 'Samples', 'Imported', probe_name)
    shutil.copyfile(a.probe, dst)
    rel = f'Samples/Imported/{probe_name}'

    for t in list(tracks_el):
        tracks_el.remove(t)

    manifest = {
        'generated': 'tools/make_rig_set.py',
        'probe': {'file': probe_name, 'sha256': sha256(a.probe),
                  'frames': frames, 'sample_rate': rate, 'channels': ch, 'bits': bits},
        'base_set': a.base, 'clip_template_from': LESSON_GLOB,
        'swept_param': a.param, 'fixed': {k: v for k, v in fixed.items()},
        'tempo': a.tempo, 'tracks': [],
        'export': {'rendered_track': 'All Individual Tracks', 'sample_rate': 44100,
                   'bit_depth': 32, 'dither': 'off', 'normalize': 'off'},
    }

    for idx, (label, val) in enumerate(cells):
        tr = copy.deepcopy(template)
        offset_ids(tr, 100000 * (idx + 1))
        name = f'{idx:02d}_{label}'
        set_track_name(tr, name)
        dev = find_device(tr)

        for k, v in NEUTRAL.items():
            set_param(dev, k, v)
        for k, v in fixed.items():
            set_param(dev, k, v)

        if label == 'dry':
            on = dev.find('On').find('Manual')
            on.set('Value', 'false')            # device bypassed = the reference
        elif val is not None:
            set_param(dev, a.param, val)

        install_clip(tr, clip_template, rel, os.path.abspath(dst), frames, rate, beats)
        tracks_el.append(tr)

        cell = dict(NEUTRAL); cell.update(fixed)
        if label != 'dry' and val is not None:
            cell[a.param] = val
        manifest['tracks'].append({'index': idx, 'name': name,
                                   'device_on': label != 'dry', 'params': cell})

    als = a.out + ' Project/' + os.path.basename(a.out) + '.als'
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    with gzip.open(als, 'wb') as f:
        f.write(xml)
    with open(os.path.join(proj, 'rig-manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f'wrote {als}')
    print(f'  {len(cells)} tracks (track 0 = dry reference, device OFF)')
    print(f'  probe {probe_name}  {frames} frames @ {rate} Hz  sha256 {manifest["probe"]["sha256"][:16]}…')
    if a.param:
        print(f'  sweeping {a.param} over {a.values}')
    if fixed:
        print(f'  fixed: {fixed}')
    print()
    print('EXPORT SETTINGS ARE THE RIG — in Live: Export Audio/Video →')
    print('  Rendered Track: All Individual Tracks   Sample Rate: 44100')
    print('  Bit Depth: 32                           Dither: off   Normalize: off')


if __name__ == '__main__':
    main()
