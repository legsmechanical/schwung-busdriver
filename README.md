# Drum Bus

A drum-bus glue effect for [Schwung](https://github.com/charlesvestal/schwung)
on Ableton Move. Six knobs, one page, transparent until you touch it.

> ⚠️ **Work in progress.** The DSP is measured and ear-checked in its original
> home (it ran as the master stage in a drum-rack module), but this standalone
> build has not yet been verified on hardware. Expect the parameter ranges to
> move before v1.0.

## Controls

| Knob | Range | What it does |
|---|---|---|
| **Compress** | 0..1 | One knob over a coordinated threshold + ratio + release program. Threshold −4 → −38 dBFS, ratio 0.06 → full limit, release ~115 → ~55 ms, attack pinned near 11 ms so the beater click survives. |
| **Crunch** | 0..1 | Full-band saturation: tanh soft knee, a cubic term for grit, and a deliberate asymmetry so it makes even harmonics too. Output-normalised, DC-blocked. |
| **Attack** | −1..+1 | Shapes the onset only. Up sharpens, down softens, ±15 dB at a fully transient hit. The tail does not move. |
| **Sustain** | −1..+1 | Shapes the decay only. Up lengthens, down shortens, about −8 / +12 dB. The onset does not move. |
| **Dry/Wet** | 0..1 | A blend over the whole stage, so anything less than 1 is parallel compression. |
| **Output** | −24..+12 dB | Trim after the auto-makeup, for when the makeup's +15 dB cap leaves you short or a crunch-only setting runs hot. |

All four shaping controls are neutral at their defaults, and a neutral Drum Bus
is **bit-identical to its input** — actually skipped, not run-and-do-nothing.

## Why it sounds like it does

Every number in `dsp/drumbus.h` was measured, and the comments record what was
tried and rejected. The short version:

- **Compress only ever attenuates.** Airwindows Pop3's gain is
  `(1-ratio) + (popComp*ratio)` with `popComp` clamped to `[0,1]` — measured
  **0.00 dB of lift on a −48 dBFS sine at every setting**. The vari-mu leveller
  that came before it lifted the same signal by **+17.7 dB**, dragging up sample
  noise floor, room bleed and reverb tails, and on a groove it buried the hats
  behind the kick by 17.8 dB.
- **Makeup is measured per block, not predicted.** Block RMS either side of the
  compressor, smoothed over ~300 ms, gated on real signal, capped at +15 dB. The
  analytic version was +21 dB wrong at the top of the knob, because an 11 ms
  attack never reaches the steady state the maths assumes.
- **The knob taper is a 1.6 power law**, chosen off the measured duck curve:
  −0.22 dB at 0.30, −1.4 at 0.50, −4.4 at 0.70, −11.5 at 0.90, −21.5 at 1.00.
  Linear stepped straight into audible compression; squared left the bottom half
  inert.
- **Attack and Sustain are orthogonal and symmetric by construction.** Attack
  compares a fast peak follower against a *smoothed version of that same
  follower*, so its reading collapses to zero during a decay. Sustain uses two
  followers sharing an attack but with different *releases*, so its reading is
  zero at the hit and grows through the tail. The stage they replaced was a
  single broadband gain that moved the attack 18.1 dB and the tail 3.0 dB in the
  same direction.
- **Crunch is full-band.** An earlier version split at ~1.2 kHz and folded only
  the top, which audibly thinned the kick — that is EQ, not saturation. Verified
  spectrum-neutral to 0.12 dB between a 60 Hz and a 6 kHz tone.

## Install

Via the Schwung module manager (`http://move.local:7700`), or manually:

```bash
scripts/build.sh      # Docker cross-compile + package dist/
scripts/install.sh    # scp to move.local (MOVE_HOST=172.16.254.1 for USB tether)
```

Then insert **Drum Bus** as an Audio FX in a Signal Chain (or Master FX).

## Development

`tests/run_tests.sh` — native build, 32 checks driven through the real
`audio_fx_api_v2` surface. They assert properties rather than proxies: that the
compressor cannot lift a quiet signal at any setting, that Attack leaves the
tail alone and Sustain leaves the onset alone, that Crunch is spectrum-neutral,
that a neutral stage is bit-identical to dry.

## Credits

MIT (see `LICENSE`). The Compress stage is **Airwindows Pop3** by Chris Johnson,
MIT, vendored verbatim — see [`vendor/SOURCES.md`](vendor/SOURCES.md). The rest
of the DSP is original, lifted from [schwung-dr32](https://github.com/legsmechanical/schwung-dr32)
where it began life as that module's always-on master bus. Built on the Schwung
framework by Charles Vestal.
