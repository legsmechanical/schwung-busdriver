# Bus Driver

A model of Ableton Live 12's **Drum Buss**, for [Schwung](https://github.com/charlesvestal/schwung)
on Ableton Move. Built from measurement of the device rather than from its documentation.

> ⚠️ **Work in progress.** Validated against Live's 22 stock Drum Buss presets on audio never used
> to build it: level within about 1 dB, spectral match around 5–6 dB in third octaves. That is
> close, not exact — **a model, not a clone**. Not yet ear-checked on hardware.

## Controls

| Knob | Range | What it does |
|---|---|---|
| **Drive** + **Character** | 0..1, 3 types | Three genuinely different machines. **Soft is a wavefolder** — past about half way its 3rd harmonic overtakes the fundamental. **Medium** is a limiter, and the only one with measurable asymmetry. **Hard** is a clean clipper. |
| **Crunch** | 0..1 | Mid-high grit. Its brightness is **not an EQ curve** — the linear response is a broad mid boost and the high end comes from harmonics it generates. |
| **Damp** | 500..20000 Hz | One-pole low-pass. The number **is** the −3 dB corner, and the low end is untouched at every setting. Sits after Crunch, so it tames what Crunch adds. |
| **Transients** | −1..+1 | Asymmetric by sign. **Down is a gate** — shortens the tail, leaves the hit alone. **Up raises attack and sustain**, attack more. Most of the range is in the last quarter. |
| **Compress** | switch | A fixed compressor, not an amount: threshold −20 dBFS, ~2.3:1 soft knee, +11 dB makeup, ~420 ms release. Sits **before** the drive, so it changes what the distortion sees. |
| **Boom** / **Freq** / **Decay** | 0..1, 30..90 Hz, 0..1 | A tuned sub generator that boosts around its tuning and **cuts below it**, which is what stops it adding subsonic mud. Amount does little past 0.75. Decay sets ring time, not level. |
| **Trim** | −70..0 dB | Before the distortion — sets how hard you hit it. |
| **Dry/Wet** | 0..1 | Blend across the whole device, so under 100% is parallel processing. At 0 it is a true bypass and nulls. |
| **Output** | −40..+3 dB | After everything. A clean level control. |

⚠️ **It is not transparent at its defaults** — it adds about 3 dB and saturates. That is what the
original does; only Dry/Wet at 0 is a bypass.

## Measured signal order

```
Trim → Transients → Compress → Drive → Crunch → Damp → Boom → Dry/Wet → Output
```

Measured, not taken from the documentation. Two placements rest on an argument that a gain
downstream of a nonlinearity cannot change the harmonic-to-linear **ratio**: toggling Compress
moves that ratio, and so does Transients, so both must sit upstream of the distortion.

## How it was built

Ableton's device only runs inside Live, so Live rendered every measurement. `.als` files are
gzipped XML, so `tools/` generates a Set with one track per parameter cell, each carrying a probe
suite, and a single offline export produces the whole ladder. Four exports, 138 cells.

The method and every number are in
[`docs/reference/measurements.md`](docs/reference/measurements.md) and
[`docs/specs/`](docs/specs/) — including the things that went wrong, which is most of the useful
part: a retracted polarity finding, a resampler hiding in the render path, and a curve fit that
improved its own metric while making the model worse.

## Install

```bash
scripts/build.sh      # Docker cross-compile + package dist/
scripts/install.sh    # scp to move.local (MOVE_HOST=172.16.254.1 for USB tether)
```

Then insert **Bus Driver** as an Audio FX in a Signal Chain (or Master FX).

## Development

`tests/run_tests.sh` — offline harness driven through the real `audio_fx_api_v2` surface. The
checks assert against **Ableton's measurements**, not against this implementation's own behaviour,
so they can fail when the model is wrong rather than only when it changes.

`tools/score.py` — scores the model against the 22 stock presets on held-out audio. That number is
the project's actual claim.

## Credits

MIT (see `LICENSE`). Built on the Schwung framework by Charles Vestal. Drum Buss is Ableton's
device; this is an independent model of it, not affiliated with or endorsed by Ableton.
