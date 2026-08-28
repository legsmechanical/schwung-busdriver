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
