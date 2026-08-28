# Vendored DSP — provenance

Bus Driver ships **MIT**. Everything here is MIT-compatible; the per-file origin
is recorded so the licence position stays checkable rather than assumed.

| File | Contents | Origin | Licence |
|---|---|---|---|
| `airwindows/airwin_dyn.h` | `Pop3` — the **Compress** stage | Airwindows © Chris Johnson, transplanted verbatim by `schwung-dr32`'s `tools/port_airwindows.py` | **MIT** (Airwindows upstream) |

Everything in `dsp/` is original to this project (carried over from
`schwung-dr32`, same author): the Attack and Sustain detectors, the Crunch
saturator, the one-knob Compress program, and the measured auto-makeup.

## Attribution requirement

Airwindows is MIT and requires the copyright notice to be retained. The notice
at the top of `airwindows/airwin_dyn.h` must not be stripped.

## Two deliberate edits to the transplanted DSP

Both are confined to Pop3's dither, ~157 dB below signal, and both were
verified to still null against upstream:

1. `5.5e-36l` → `5.5e-36`. The `l` suffix makes the dither arithmetic **long
   double**, which on aarch64 is IEEE binary128 emulated in software — that one
   character cost about **1.2% of a Move core**. Invisible off-device, where
   long double is cheap hardware.
2. `pow(2, expon+62)` → `ldexp(1.0, expon+62)`, bit-identical for integer
   exponents, an exponent-field write instead of a transcendental.
