# Drum Buss fidelity campaign — spec

**Status:** approved 2026-08-28, not started.
**Goal:** rebuild `busdriver` as a faithful model of Ableton Live 12's **Drum Buss**, fit against
rendered measurements rather than designed by ear.

**Scope decisions (Josh, 2026-08-28):**
- **Full clone.** Match Drum Buss's control set and signal order. Our current six-knob surface is
  retired, including the one-knob Compress program and the Attack/Sustain split.
- **Ableton wins every conflict**, including where it overturns a measured decision we already
  ear-approved in DR32 (see §7).

---

## 1. What is already known, and how

⭑ Everything in this section came from **Live's own files on Josh's machine**, not from the
manual and not from a tutorial. It is provenance-checkable and should not be re-derived.

**Source A — the device schema.** `/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/`
`Schema/12.0_12300.txt`, block `<DrumBuss>` (line 1865). Lists every parameter element.

**Source B — 22 stock presets.** `Core Library/Devices/Audio Effects/Drum Buss/*.adv`. These are
**gzipped XML**; each carries a full `<DrumBuss>` block with real values and each parameter's
`MidiControllerRange`, which is where the ranges below come from.

| Parameter | Range | Unit / meaning |
|---|---|---|
| `EnableCompression` | bool | ⚠ a **toggle**, not an amount — the compressor is fixed |
| `DriveAmount` | 0..1 | normalised |
| `DriveType` | 0..2 | enum; 0/1/2 = soft / medium / hard (**order to be confirmed**, §4.1) |
| `CrunchAmount` | 0..1 | normalised |
| `DampingFrequency` | 500..20000 | **Hz**, stored linearly in Hz |
| `TransientShaping` | −1..+1 | bipolar, 0 = neutral |
| `BoomAmount` | 0..1 | normalised |
| `BoomFrequency` | 30..90 | **Hz** |
| `BoomDecay` | 0..1 | normalised |
| `BoomAudition` | bool | monitors the sub path alone |
| `InputTrim` | 0.000316..1 | **linear gain** = −70..0 dB |
| `OutputGain` | 0.01..1.41254 | **linear gain** = −40..+3 dB |
| `DryWet` | 0..1 | |

**Two observations worth carrying:**
- `TransientShaping` values across the stock presets are all **n/63** (0.5238095 = 33/63,
  0.7777778 = 49/63, 0.4761905 = 30/63). Either the control or the preset authoring is quantised
  to 1/63. Do not read more resolution into it than that until measured.
- `BoomFrequency` values are **musical pitches** — 36.7 (D1), 41.2 (E1), 48.9 (G1), 55 (A1),
  65.4 (C2), 74.2, 82.4 (E2). Matches the tutorial's note readout.

**Documented signal order** (Live manual, *Audio Effect Reference → Drum Buss*), corroborated
independently by the tutorial transcript:

```
Trim → Comp → Drive(type) → Crunch → Damp → Transients → Boom → Dry/Wet → Output
```

⚠ **This is a documented premise, not a measured one.** §4.1 measures it before anything is fit
against it. Two sources agreeing on prose is not a measurement.

---

## 2. What our module does today, for contrast

```
Attack → Sustain → Crunch(full-band) → Compress → auto-makeup → [Dry/Wet] → Output
```

Every structural difference, all of which the campaign closes:

| | Drum Buss | ours today |
|---|---|---|
| Compressor | fixed, on a **switch**, **before** the distortion | continuous 1.6-power-law program, **after** Crunch |
| Crunch | sine-shaped, **mid-high only**, paired with Damp | **full-band**, no damp stage |
| Transients | **one** bipolar knob; + adds attack *and* sustain | **two** orthogonal knobs, deliberately decoupled |
| Drive | 3 selectable types | **absent** |
| Damp | low-pass, 500 Hz..20 kHz | **absent** |
| Boom | resonant sub generator + Freq + Decay + audition | **absent** |
| Input Trim | −70..0 dB, pre-everything | **absent** (ours is a post Output trim) |
| Makeup | none | measured per-block auto-makeup |

---

## 3. The rig

### 3.1 Why it looks like this
Drum Buss cannot run outside Live, so Live must render every target. But `.als` files are
**gzipped XML** and §1 Source B gives the exact device block, so a whole parameter ladder can be
**generated as one Set with N tracks** and rendered in a single export. Live's export is offline
and faster than real time. No OSC, no Max patch, no real-time recording.

### 3.2 Protocol
1. `tools/make_rig_set.py` writes `rig/<ladder>.als`: N tracks, each with the **same** source clip
   and one Drum Buss at one parameter cell. Track 1 is always **Drum Buss bypassed** = the dry
   reference.
2. Josh opens it and runs **Export Audio/Video → All Individual Tracks**.
3. `tools/analyse.py` reads the WAVs and fits.

### 3.3 Rig discipline — non-negotiable
- 🔴 **Set sample rate = 44.1 kHz.** The Move runs 44.1k. Rendering at 48k makes every filter
  corner and time constant we fit wrong by 8.8%, silently and uniformly.
- 🔴 **Export 32-bit float WAV.** We are measuring transfer curves and low-level behaviour; 16-bit
  quantisation sits exactly where the interesting parts are.
- 🔴 **Warn about, and discard, Live's export tail/latency.** Align every render against the dry
  reference track by cross-correlation before comparing anything. Do not assume sample alignment.
- 🔴 **Name the control (workspace standing rule).** Every reported number states the source file
  **by SHA-256**, not by filename, and states which single parameter varied.
- Master chain empty, all track/master faders at unity, no limiter, no dither on export.
- Each ladder writes a `manifest.json`: source hash, per-track parameter cell, Live version,
  sample rate, bit depth, export date.

### 3.4 Our side
`tools/render.cpp` — reads a WAV, applies our module through the **real `audio_fx_api_v2`
surface** at a given parameter set, writes a WAV. Same code path as the device, so a fit cannot
be an artefact of a test-only path. Then **the same analysis code runs over both sides.**

⚠ Our module is int16-in/int16-out by the host contract, while Live renders float. Do the
comparison in float and account for the int16 stage explicitly — it is a real part of what the
Move will do, but it must not be mistaken for a modelling error.

---

## 4. Measurement design

The insight that shapes this: **Drum Buss has an explicit neutral for every stage** (Drive 0,
Crunch 0, Damp 20000, Transients 0, Boom 0, Comp off). Stage isolation is therefore exact, unlike
the Typhon campaign where it never was. That permits sharper probes than program material.

### 4.1 FIRST: verify the signal order (before any fitting)
Everything downstream is fit *within* an assumed topology, so the topology is measured first.

- **Comp before or after Drive?** Hard-clip drive at a level that visibly clips, with Comp on vs
  off. If Comp is upstream, the clipped waveform's flat-top *width* changes with Comp; if
  downstream, the flat top is identical and only the level after it moves.
- **Crunch before or after Damp?** Crunch full + Damp low. Upstream-Crunch means Damp attenuates
  crunch's harmonics; downstream means the harmonics land above the damp corner unattenuated.
- **Where does Transients sit?** Transients full-negative with Drive hard. A gate before a clipper
  behaves very differently from one after it.
- **Is Dry/Wet the whole chain or partial?** Dry/Wet 0 must null against bypass to the noise floor.

**Deliverable:** a measured topology diagram. If it contradicts the manual, the measurement wins
and the spec is amended.

### 4.2 Per-stage probes — matched to the stage's type

| Stage | Probe | Why this and not a drum loop |
|---|---|---|
| **Drive** ×3 types, **Crunch** | **2 Hz full-scale sine**, or a slow ramp | These are memoryless waveshapers. Plotting output against input sample-by-sample recovers the **actual transfer curve** at float precision from ONE render. Fitting a curve through a few harmonic ratios is strictly worse. |
| **Damp**, **Boom** | **Exponential sine sweep** + Farina deconvolution | Recovers the **linear impulse response** *and* separates each harmonic order into its own time window. One render per setting yields both the filter and its nonlinear content. |
| **Comp** | Level-stepped **sine bursts**; **level steps** | Bursts at a level ladder give the static gain curve; a step gives attack and release time constants directly. A drum loop confounds level, spectrum and timing simultaneously. |
| **Transients** | Synthetic hits, controlled attack and decay, at several decay rates | Separates onset from tail cleanly, and shows the program-dependence the manual implies. |
| **Trim / Output / Dry/Wet** | Steady sine | These should be exact gains; confirm and move on. |

⚠ **Crunch is band-limited.** Probe it with material that has content on both sides of the split
so the corner is visible — a full-scale LF sine alone cannot show a mid-high-only effect. Sweep
**and** two-tone.

⚠ **Headroom is part of the measurement.** ([[schwung-busdriver-module]]) The existing harness read
attack as +6.7/−13.7 dB — the signature of a broken asymmetric control — purely because the test
signal clipped. Every probe states its peak level, and every boosting stage is probed with room
to boost into.

### 4.3 Ladder resolution
Coarse first: 5 points per continuous parameter (0, 0.25, 0.5, 0.75, 1.0) to find the shape, then
refine only where the shape needs it. `DampingFrequency` and `BoomFrequency` ladder
**logarithmically**, not linearly.

---

## 5. Fitting

**Live renders are one-time targets; our renderer is fast and offline.** So do not hand-draw laws
through the measurements — **optimise numerically** against fixed targets.

- Per stage, express our model with free parameters, then minimise error against the Live target
  with a gradient-free optimiser (Nelder-Mead, then differential evolution where it stalls).
- Loss: for waveshapers, RMS error on the **transfer curve itself**, which is direct and has no
  windowing choices. For filters, log-magnitude error over the IR's spectrum. For dynamics, error
  on the static curve plus the fitted time constants.
- **Match the MECHANISM, not the metric** ([[schwung-fidelity-methodology]]). A fit that hits the
  number with the wrong structure will break something orthogonal. Prefer the right topology with
  a worse number over the wrong topology with a better one, and say so when it happens.
- Every fitted constant is logged with the render it came from, by hash.

---

## 6. Validation — held out, never fit to

- **The 22 stock presets are the validation set** (§1 Source B), with their exact settings already
  extracted. Render each through Live and through ours; compare. **Nothing in this set is ever
  used for fitting.**
- Plus real drum program material, likewise held out.
- A model that matches on the material it was fit to has demonstrated nothing.

**Gate:** objective scorecard first; **one broad ear A/B at the end of the arc**, not per slice
([[schwung-echidna-objective-gate-ears-at-end]]).

---

## 7. Conflicts this campaign deliberately overturns

Josh's call: Ableton wins. Recording them so nobody later "fixes" them back.

1. **Crunch becomes band-limited.** DR32's comment rejects a ~1.2 kHz split as *"EQ, not
   saturation"* that *"audibly thinned the kick"*. Mid-high-only is what Drum Buss actually does —
   and it pairs it with **Damp** as the antidote. We rejected the reference behaviour without
   knowing it was the reference behaviour.
2. **Attack + Sustain collapse into one Transients knob.** They were split because a combined
   control moved attack and tail together, treated as a defect. The manual says Ableton's positive
   Transients *"adds attack and sustain"* — moving both together is the **intent**.
3. **The one-knob Compress program is retired** for a fixed compressor on a switch.
4. **Compression moves before the distortion.**

Our measured auto-makeup has no counterpart in Drum Buss and should be **dropped** unless
measurement shows Ableton's fixed compressor has makeup of its own — which §4.2's burst ladder
will answer directly.

---

## 8. Constraint: this has to run on a Move

The current stage costs **0.37% of an A72 core**. The clone adds a resonant sub generator, a
filter, and three drive types. Naïve oversampled clipping is the obvious blow-up risk.

- Budget check at the end of every phase, on device, not on the Mac.
- ⚠ `long double` on aarch64 is **software-emulated** — one `l` suffix in vendored dither cost
  ~1.2% of a core (`vendor/SOURCES.md`). Watch for it in anything new.
- Where full fidelity is not affordable, **anchor and document the bound** rather than chase it.

---

## 9. Phases

| # | Phase | Deliverable | Gate |
|---|---|---|---|
| 0 | Rig bootstrap | `make_rig_set.py`, `render.cpp`, `analyse.py`; one dry-vs-dry null render | dry track nulls against source < −90 dB |
| 1 | **Topology** (§4.1) | measured signal-order diagram | order confirmed or spec amended |
| 2 | Static gains | Trim, Output, Dry/Wet laws | exact to 0.05 dB |
| 3 | Waveshapers | Drive ×3 + Crunch transfer curves, band split | curve RMS error stated |
| 4 | Filters | Damp + Boom, IR-fit | magnitude error over band stated |
| 5 | Dynamics | Comp static curve + time constants; Transients | step response matched |
| 6 | Integration | all stages, order per phase 1 | 22 stock presets scored |
| 7 | Device | CPU budget, deploy, one broad ear A/B | Josh's ear |

---

## 10. Open — needed before phase 0

- [ ] ⛳ **One bootstrap Live Set from Josh.** One audio track, any drum loop, one Drum Buss,
      nothing else, saved anywhere. Needed once, to learn the Set-level XML; after that every
      ladder is generated and Josh only ever hits Export.
- [ ] Confirm the `DriveType` enum order (0/1/2 → soft/medium/hard) — assumed from the manual's
      "increasing degree of distortion", measured in phase 3.
- [x] ~~Decide the name once it is a clone rather than an homage.~~ **RESOLVED 2026-08-28 (Josh):
      "Bus Driver"** — id `busdriver`, repo `schwung-busdriver`, abbrev `DRVR`. Deliberately not
      "Drum Bus": a public-catalog module that is a faithful clone should not also carry a name a
      keystroke away from the Ableton device it models. "Drum Buss" appears in this repo only as
      the name of the thing being modelled, never as our own.
