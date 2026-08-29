# Drum Buss — measured results

Findings that are **confirmed**, with how they were obtained. Anything not in this file is not
yet established. Chat scrollback is not a record.

**Source of every number here:** `rig/renders/campaign/`, exported 2026-08-28 from
`rig/sets/campaign Project/campaign.als`, Live 12.3.2, **engine at 44.1 kHz native**, 32-bit
float, All Individual Tracks, no dither, no normalize. Per-file SHA-256 in
`rig/renders/renders-manifest.json`. Probe: `suite.wav`, sha256 `6f6fb44cd168fc4b…`.

⚠ The renders are **not in git** (1.1 GB) and cannot be regenerated without Ableton Live and a
human export. Everything else in `rig/` is reproducible from `tools/`.

---

## 0. The rig is exact

**Dry track (device bypassed) nulls against the source probe at −300 dB — bit exact.**
Path gain +0.000 dB, alignment lag 0. So nothing in the Live path colours the signal, and every
difference measured below belongs to Drum Buss.

⚠ This only became true after setting **Live's engine** to 44.1 kHz. See
`docs/specs/…-campaign.md` §3.3 — Live renders at the audio device's rate and resamples on
export, and a 48 kHz engine left an −83 dB multiplicative artefact AND meant the device was
running at the wrong rate.

## 1. Device latency: 55 samples (1.25 ms)

Constant across every cell with the device on; 0 with it bypassed. Measured on the −30 dBFS
alignment tone at the head of the suite. Delay compensation is on in the Session; the offset is
uniform, so per-cell alignment absorbs it.

**Two meaningful deviations, both physical rather than noise:**
- **Damp adds group delay**, and it is measurable: 16 kHz → 55, 4 kHz → 56, 2 kHz → 58,
  1 kHz → 61, 500 Hz → **67** samples. That is the low-pass's own phase delay at 300 Hz.
- **`DryWet = 0` sits at 49 samples** — the internal dry path is shorter than the processed one.

## 2. Small-signal gain at −30 dBFS

Measured where every cell is quasi-linear, so these are the *linear* gains before saturation.

| cell | gain (dB) |
|---|---|
| **neutral** (all controls at rest, device ON) | **+3.791** |
| drive soft 0 / .25 / .5 / .75 / 1.0 | 3.791 / 5.726 / 10.707 / 12.004 / **13.291** |
| drive med 0 / .25 / .5 / .75 / 1.0 | 3.791 / 7.535 / 11.271 / 14.988 / **18.661** |
| drive hard 0 / .25 / .5 / .75 / 1.0 | **6.568** / 7.843 / 9.713 / 12.464 / 16.555 |
| crunch .25 / .5 / .75 / 1.0 | 7.340 / 10.285 / 12.796 / **14.980** |
| **comp on** | **+14.866** |

## 3. CONFIRMED: Trim, Output and the neutral gain

- **`InputTrim` and `OutputGain` are exact linear gains.** trim −12 dB → 3.791 − 12.00;
  trim −6 dB → 3.791 − 6.00; out +3 dB → 3.791 + 3.00; out −6 dB → 3.791 − 6.00. All exact to
  0.005 dB. **These two controls need no fitting.**
  ⚠ Measured across the WHOLE suite instead, trim looks non-1:1 (−12 dB in → −10.4 dB out).
  That is saturation downstream of it, not a nonlinear control — which is itself a topology
  constraint: **Trim is before the nonlinearity, Output is after it.**
- **The device is NOT unity at neutral: +3.791 dB**, and it saturates with Drive at 0 (§4).

## 4. CONFIRMED: Drum Buss saturates at Drive = 0

From the earlier swept-probe ladder (⚠ that ladder was rendered through the 48 kHz engine, so
treat the exact numbers as provisional and re-derive from the campaign renders):

| in | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |
|---|---|---|---|---|---|
| out | 0.297 | 0.551 | 0.742 | 0.868 | 0.940 |

An odd, soft-saturating curve, symmetric to 0.0002 (no even harmonics). **The Drive knob adds to
a saturation that is always present.** Our module has no equivalent.

The **hard** type has a different baseline (+6.57 dB at Drive 0 vs +3.79 for soft and medium), so
the three types do not share a gain-staging origin.

## 5. CONFIRMED: Drum Buss is AC-coupled

At neutral it returns essentially nothing for a 0.25 Hz triangle — correlation with the input
**+0.038**, output non-zero only at the discontinuities. Consequence: **a slow-ramp transfer-curve
probe is invalid for this device**; use the amplitude-swept carrier.

## 6. The fixed compressor contributes ~+11.1 dB of makeup

`comp_on` reads +14.866 dB against neutral's +3.791 at −30 dBFS. Static curve and time constants
are in the `bursts` and `steps` segments, not yet extracted.

## 7. OPEN — flagged, not concluded

- **`DryWet = 0` may not be a true bypass.** Its peak over the suite is 1.287 against the dry
  track's 1.000, yet its gain on the quiet alignment tone is 0.000 dB. Both cannot describe a
  plain dry path. Needs the segment-aware analysis before claiming anything.
- **High Drive is not a memoryless waveshaper.** At Drive 1.0 the per-bin spread of the transfer
  curve reaches sd 0.35–0.50 against values of ~0.6 — a static curve is the wrong model there.
- **Transient cells align poorly** (residual −9 to −25 dB vs −39 elsewhere) because transient
  shaping deforms the alignment tone itself. `transient_1.0` railed to lag 496 and is not to be
  trusted. Pin those to the measured 55 samples rather than fitting the lag.
- **Signal order is not yet measured** — cells 54–58 exist for it, unanalysed.

---

# Stage measurements (2026-08-28, all 59 cells)

Produced by `tools/measure.py rig/renders/campaign "rig/sets/campaign Project"`, full table in
`rig/measurements.json`. Runs in ~4 s.

## 8. 🔴 CONFIRMED: **Drum Buss INVERTS POLARITY**

Every cell correlates **negative** against the dry reference at its true lag; the bypassed dry
track is bit-exact and positive, so the inversion is the device's. `DryWet = 0` gives exactly
**−0.99998**, i.e. −1× the input.

⚠⚠ **This nearly went undetected, and would have inverted every curve.** A pure tone cannot
distinguish a polarity flip from a half-period shift: the 300 Hz alignment tone produced
candidates at lag 49 (g=−1), 122 (g=+1), 196 (g=−1) — spaced 73.5 samples with alternating sign.
Alignment is now done on the **burst ENVELOPE**, which has no carrier and cannot alias.
**Practical consequence:** blending Drum Buss against an external dry path partially cancels.

## 9. Device latency: **58 samples (1.32 ms)**, uniform

From 35 of 58 cleanly-aligned cells; 34/35 agree on polarity. Latency and polarity are device
properties and are pinned across cells — fitting them per cell let one badly-aligned outlier
invent physics (`drive_hard_1.0` came out at lag 164, positive, curve width +37 dB = noise).

## 10. CONFIRMED: **Crunch is band-limited** — our full-band version is wrong

Two-tone (60 Hz / 6 kHz), relative to neutral:

| Crunch | 60 Hz | 6 kHz | tilt |
|---|---|---|---|
| 0.25 | −0.29 | +2.65 | **+2.93** |
| 0.50 | −0.97 | +4.59 | **+5.57** |
| 0.75 | −2.16 | +5.90 | **+8.06** |
| 1.00 | **−4.03** | **+6.77** | **+10.81** |

It **boosts highs and cuts lows**. DR32's comment rejected a ~1.2 kHz split as *"EQ, not
saturation"* that *"audibly thinned the kick"* — that is precisely what Drum Buss does, and it
pairs it with Damp as the antidote.

## 11. Damp: a clean low-pass, 60 Hz untouched

Attenuation at 6 kHz vs neutral (20 kHz = off), and the group delay it adds:

| Damp | 6 kHz | 60 Hz | lag |
|---|---|---|---|
| 500 Hz | **−20.95** | +0.62 | 70 |
| 1 kHz | −15.03 | +0.61 | 64 |
| 2 kHz | −9.37 | +0.57 | 60 |
| 4 kHz | −4.55 | +0.43 | 59 |
| 8 kHz | −1.48 | +0.20 | 58 |
| 16 kHz | −0.18 | +0.03 | 58 |

Low end is untouched to within 0.6 dB at every setting. The lag column is the filter's own group
delay at 300 Hz, and tracks the corner exactly.

## 12. Boom: a tuned resonance that **saturates above 0.75**

Added low end at 60 Hz, relative to neutral:

| Boom | 60 Hz | 6 kHz |
|---|---|---|
| 0.25 | +3.46 | −0.64 |
| 0.50 | +6.82 | −2.62 |
| 0.75 | **+7.12** | −3.00 |
| 1.00 | **+7.13** | −3.01 |

**0.75 → 1.00 buys 0.01 dB** — the control is effectively finished at 0.75 on this probe. The
6 kHz column falls as Boom rises: the added low end drives the saturator harder and compresses
the highs. That is a stage INTERACTION and it constrains the topology — Boom must sit where the
saturator can see it.

`BoomFrequency` is a tuned resonance, not a shelf: at a 60 Hz probe, 30 Hz→+1.11, 50 Hz→+7.12,
70 Hz→+5.67, 90 Hz→**−4.70** dB (it cuts). `BoomDecay` barely moves the steady level
(+9.62…+9.75), as a decay control should.

## 13. CONFIRMED: Trim is PRE the nonlinearity, Output is POST

Structural, from the transfer curve rather than from levels:
- `out_+3dB`: slope 2.126 = 1.505 × 1.412 and ceiling 1.3325 = 0.9433 × 1.412 — the whole curve
  scales, **so Output is after the saturator**.
- `trim_-12dB`: ceiling 0.371. Post-saturation it would be 0.9433 × 0.251 = 0.237. It is not,
  **so Trim is before the saturator**.

## 14. RESOLVED: `DryWet = 0` IS a true bypass

Earlier flagged as suspect. Slope 0.999, ceiling 0.996, two-tone gains 0.00/0.00 dB, small-signal
gain −0.00 dB. It returns the input — inverted, and delayed 50 rather than 58 samples (the
internal dry path is shorter).

## 15. Topology, first evidence: **Damp is AFTER Crunch**

With Crunch at 1.0, adding Damp at 500 Hz takes 6 kHz from +11.06 to −7.82 = **−18.9 dB**, close
to Damp's own −20.95 dB on a clean signal. So Damp attenuates Crunch's harmonics, which places it
downstream. Matches the manual — now measured.

The Comp-vs-Drive ordering cells (54/55) show small-signal gain rising 16.56 → 28.47 dB while the
ceiling barely moves (0.9859 → 0.9768) — consistent with the compressor feeding MORE into the
clipper, i.e. **Comp before Drive**. Suggestive, not yet conclusive; needs the burst/step analysis.

## 16. Still open

- **`bursts` and `steps` segments are not yet analysed** — the compressor's static curve and its
  attack/release times.
- **The Farina `sweep` segment is not yet deconvolved** — full magnitude responses for Damp and
  Boom rather than two spot frequencies.
- **`hits` not analysed** — the transient stage. Note `transient_1.0` fails alignment even on the
  envelope (lag −53, curve width +33 dB); it needs the pinned lag path.
- Transients changes the small-signal slope monotonically (1.075 / 1.227 / 1.372 / **1.505** /
  1.653 / 1.840 for −1 … +0.5) **on a steady swept tone**, which is not obviously "transient"
  behaviour and is worth understanding.
