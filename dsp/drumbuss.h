// ============================================================================
//  drumbuss.h — Bus Driver's model of Ableton Live 12's Drum Buss.
//
//  Every constant here traces to a measurement in docs/reference/measurements.md,
//  and the section is cited at the point of use. Nothing is tuned by ear and
//  nothing is guessed; where a law is not yet measured it is marked TODO with
//  the export that will supply it, rather than filled in with something
//  plausible.
//
//  MEASURED SIGNAL ORDER (§15, §23, §24, §34 — measured, not taken from docs):
//
//      Trim -> Transients -> Comp -> Drive -> Crunch -> Damp -> Boom
//           -> Dry/Wet -> Output
//
//  Two placements were established by the harmonic-to-linear RATIO, which a
//  gain downstream of a nonlinearity cannot move: Comp is upstream of the
//  distortion (§23) and Transients is upstream of the saturation (§34).
//  Damp is downstream of Crunch (§15 and §24, two instruments).
//
//  ⚠ The device does NOT invert polarity. An earlier measurement said it did
//  and was retracted (§30) — that was phase near 180 degrees at 300 Hz, and
//  phase is not polarity.
// ============================================================================
#pragma once
#include <cmath>
#include <cstring>
#include "../src/shapers.h"

namespace drumbuss {

// ---------------------------------------------------------------- parameters
//
// Ranges are Live's own, read out of its stock .adv presets (§1). InputTrim and
// OutputGain are stored by Live as LINEAR gains, not dB.
struct Params {
    bool  comp      = false;   // EnableCompression — a TOGGLE, not an amount
    float drive     = 0.0f;    // 0..1
    int   driveType = 0;       // 0 soft (a FOLDER, §26), 1 med, 2 hard
    float crunch    = 0.0f;    // 0..1
    float dampHz    = 20000.f; // 500..20000, and it IS the -3 dB corner (§19)
    float trans     = 0.0f;    // -1..+1, asymmetric by sign (§25)
    float boom      = 0.0f;    // 0..1, saturates above 0.75 (§12, §20)
    float boomHz    = 50.0f;   // 30..90
    float boomDecay = 1.0f;    // 0..1
    float trim      = 1.0f;    // 0.000316..1  (-70..0 dB), PRE the nonlinearity
    float outGain   = 1.0f;    // 0.01..1.41254 (-40..+3 dB), POST it (§13)
    float dryWet    = 1.0f;    // 0..1; 0 is a true bypass (§14)
};

// ---------------------------------------------------------------- one-pole LP
//
// §19: Damp is a one-pole low-pass whose -3 dB corner is EXACTLY the parameter
// value in Hz — measured -2.81 dB at 500 for the 500 setting, -2.80 at 1k for
// 1000, -2.65 at 2k, -2.44 at 4k, -2.06 at 8k. Slope about -5.5 dB/octave.
// This stage is complete; there is nothing left to fit in it.
struct OnePoleLP {
    float a = 1.0f, z[2] = {0.0f, 0.0f};
    void set(float fc, float sr) {
        if (fc >= 0.45f * sr) { a = 1.0f; return; }   // effectively open
        a = 1.0f - std::exp(-2.0f * 3.14159265f * fc / sr);
    }
    inline void run(float &l, float &r) {
        z[0] += a * (l - z[0]); l = z[0];
        z[1] += a * (r - z[1]); r = z[1];
    }
    void reset() { z[0] = z[1] = 0.0f; }
};

// ---------------------------------------------------------------- compressor
//
// §17 static curve, isolated from the always-on saturation by subtracting the
// compressor-off cell, then FITTED (§36) rather than read off by eye:
//     threshold -19.99 dBFS
//     ratio     2.34:1
//     knee      +-1.76 dB
//     makeup    fixed, about +11 dB
//     residual  0.589 dB rms over the compressing region
//
// ⚠ The "~4.3:1" quoted earlier in §17 was output-vs-input across the whole
// DEVICE, which includes the always-on saturation compressing alongside. The
// compressor's OWN ratio is 2.34:1. Modelling with 4.3 would double-count the
// saturation, which the Drive stage already provides.
// §33 timing, converged across four smoothing windows with a no-compressor
// control correctly reading ~0:
//     release   about 420 ms (485 ms under heavy drive)
//     attack    about 1.8 ms — weaker evidence, treat as 1.5-2 ms
struct Comp {
    static constexpr float kThreshDb = -19.99f;  // fitted, §36
    static constexpr float kRatio    = 2.34f;    // fitted, §36 — NOT the 4.3
    static constexpr float kKneeDb   = 1.76f;    // fitted, §36
    static constexpr float kMakeupDb = 11.0f;
    static constexpr float kAtkMs    = 1.8f;
    static constexpr float kRelMs    = 420.0f;

    float aAtk = 0.0f, aRel = 0.0f, env = 0.0f, gain = 1.0f, makeup = 1.0f;

    void setSampleRate(float sr) {
        aAtk = 1.0f - std::exp(-1.0f / (kAtkMs * 1e-3f * sr));
        aRel = 1.0f - std::exp(-1.0f / (kRelMs * 1e-3f * sr));
        makeup = std::pow(10.0f, kMakeupDb / 20.0f);
    }
    void reset() { env = 0.0f; gain = 1.0f; }

    inline void run(float &l, float &r) {
        const float det = std::fabs(l) > std::fabs(r) ? std::fabs(l) : std::fabs(r);
        env += (det > env ? aAtk : aRel) * (det - env);
        const float db = 20.0f * std::log10(env > 1e-9f ? env : 1e-9f);
        float over = db - kThreshDb;
        float grDb = 0.0f;
        if (over > kKneeDb) {
            grDb = (over - over / kRatio);
        } else if (over > -kKneeDb) {                 // quadratic soft knee
            const float t = over + kKneeDb;
            grDb = (1.0f - 1.0f / kRatio) * t * t / (4.0f * kKneeDb);
        }
        gain = std::pow(10.0f, -grDb / 20.0f);
        l *= gain * makeup;
        r *= gain * makeup;
    }
};

// ---------------------------------------------------------------- shapers
//
// §37: med, hard and Crunch each reduce to ONE fixed shaper plus a pre-gain
// (residuals 0.0008-0.07). `soft` does not — it FOLDS, and a monotonic shape
// cannot be scaled into a fold (§29). So all four are stored as the MEASURED
// curves at their measured settings and interpolated, which removes the fit
// residual for the three that fit and is an honest approximation for the one
// that does not.
//
// ⚠ `soft`'s per-bin width reaches 0.754, i.e. at high drive it is not a static
// function of its input at all. The table is an average over that spread. Its
// exact topology is unknown and NOT guessed at here.
//
// Curves are odd by measurement (§22: evens 18-20 dB below odds), so only the
// positive half is stored and the sign is carried through.
struct Shaper {
    const float (*curve)[kShaperN] = nullptr;
    const float *drives = nullptr;
    int steps = 0;
    int i0 = 0, i1 = 0;
    float mix = 0.0f;

    void select(int type) {
        switch (type) {
            case 1:  curve = kMedCurve;  drives = kMedDrive;  steps = kMedSteps;  break;
            case 2:  curve = kHardCurve; drives = kHardDrive; steps = kHardSteps; break;
            default: curve = kSoftCurve; drives = kSoftDrive; steps = kSoftSteps; break;
        }
    }
    void selectCrunch() {
        curve = kCrunchCurve; drives = kCrunchDrive; steps = kCrunchSteps;
    }
    void setDrive(float d) {
        if (!steps) return;
        i0 = 0;
        while (i0 < steps - 2 && drives[i0 + 1] < d) i0++;
        i1 = i0 + 1;
        const float span = drives[i1] - drives[i0];
        mix = (span > 1e-9f) ? (d - drives[i0]) / span : 0.0f;
        mix = mix < 0.0f ? 0.0f : (mix > 1.0f ? 1.0f : mix);
    }
    inline float run(float x) const {
        if (!steps) return x;
        const float a = x < 0.0f ? -x : x;
        const float u = a > 1.0f ? 1.0f : a;
        const float f = u * (kShaperN - 1);
        int k = (int)f;
        if (k > kShaperN - 2) k = kShaperN - 2;
        const float t = f - k;
        const float v0 = curve[i0][k] + t * (curve[i0][k + 1] - curve[i0][k]);
        const float v1 = curve[i1][k] + t * (curve[i1][k + 1] - curve[i1][k]);
        const float y = v0 + mix * (v1 - v0);
        return x < 0.0f ? -y : y;
    }
};

// ------------------------------------------------------------- oversampling
//
// §51: the shaping stages alias audibly. Measured with a pure tone in and
// everything that is NOT a harmonic of it measured out: at a 5 kHz input,
// med / hard / crunch put aliased content only **5-6 dB below** the harmonics
// they are meant to produce (-17.3 / -16.2 / -18.4 dB re the fundamental). That
// is the harshness you hear on hats and snare tops, and no amount of curve
// fidelity fixes it.
//
// 2x oversampling around the shapers moves the alias-free limit to the 8th
// harmonic of a 5 kHz tone, which covers what these stages actually generate.
// The device has CPU to spare — the whole module measured 0.788% of one A72
// core with every stage on — so this is cheap insurance rather than a luxury.
//
// Halfband FIR, 15 taps, odd taps zero except the centre: only 4 multiplies per
// output on the upsample and 4 on the downsample.
struct Halfband {
    // Symmetric halfband, centre 0.5, odd taps only. Written in the obvious
    // zero-stuff form rather than polyphase: the first attempt split the
    // branches by hand, mismatched them, and lost 4.5 dB of gain. This version
    // is verified by a NULL TEST (shaper bypassed, in vs out) rather than by
    // inspection.
    // Normalised so the odd taps sum to 0.25 per side, i.e. DC gain exactly 1.
    // Unnormalised they summed to 0.2401, costing 0.33 dB over the round trip —
    // small, but it would have shown up as a mysterious level error later.
    static constexpr float c1 = 0.323948f, c3 = -0.101572f,
                           c5 = 0.043471f, c7 = -0.015848f;
    float z[16] = {0};
    int w = 0;
    void reset() { for (int i = 0; i < 16; i++) z[i] = 0.0f; w = 0; }
    inline void push(float x) { z[w & 15] = x; w++; }
    inline float at(int b) const { return z[(w - 1 - b) & 15]; }
    inline float filt() const {
        return 0.5f * at(7) + c1 * (at(6) + at(8)) + c3 * (at(4) + at(10))
                            + c5 * (at(2) + at(12)) + c7 * (at(0) + at(14));
    }
};

// ---------------------------------------------------------------- the folder
//
// §48: `soft` is a FOLDER, and a static table cannot represent it — the table
// reproduced its harmonics only to ~12 dB (§47) where hard managed 0.58.
//
// A sine folder y = sin(z*x) has an exact analytic harmonic structure: driven by
// a sine of amplitude A it gives H_n = 2*J_n(zA), so H3/H1 = J3(zA)/J1(zA), and
// inverting that against the measured ratio recovers z directly. Doing so at
// every amplitude shows **z proportional to amplitude** (r = 0.91), which is the
// signature of exactly this topology with a pre-gain.
//
// ⚠ Only r = 0.91, not 1. The recovered z DIPS around amp 0.6-0.7, and a pure
// sine folder cannot produce a non-monotonic H3/H1. So this is close to the
// real topology but not identical to it, and it is documented as such rather
// than presented as the answer.
//
// Depth per unit amplitude, recovered per drive setting (§48):
//     z = 2.5071*d^2 - 0.6669*d + 1.6061      (rms 0.234)
struct Folder {
    float z = 1.6061f, makeup = 1.0f;
    void setDrive(float d) {
        z = 2.5071f * d * d - 0.6669f * d + 1.6061f;
        if (z < 0.05f) z = 0.05f;
        // Normalise so the SMALL-SIGNAL gain matches the measured curve: near
        // zero sin(z*x) ~ z*x, so the makeup carries the measured slope.
        makeup = 1.0f / z * (1.6061f + 1.72f * d);
    }
    inline float run(float x) const {
        const float u = z * x;
        return std::sin(u < -3.14159265f ? -3.14159265f
                        : (u > 3.14159265f ? 3.14159265f : u)) * makeup;
    }
};

// ---------------------------------------------------------------- the limiter
//
// §50: `med` is a LIMITER, not a waveshaper. Its measured static curve fits to
// 0.006-0.070 rms (§37) and yet, applied as a waveshaper, it produces ~5 dB
// MORE third harmonic than the device (§47). That combination is diagnostic: a
// stage whose average input/output relationship is right while its harmonic
// output is too high is applying smooth GAIN REDUCTION, not clipping the
// waveform. The tutorial calls this type "limiting distortion"; the measurement
// agrees.
//
// So the same measured curve is used, but as a GAIN TARGET rather than a
// transfer function: the envelope selects a gain from the curve, that gain is
// smoothed, and the smoothed gain multiplies the signal. Steady state is
// identical to the waveshaper; the harmonics are far lower, because the gain no
// longer changes within a cycle.
struct Limiter {
    float aAtk = 0.0f, aRel = 0.0f, env[2] = {0,0}, g[2] = {1.0f, 1.0f};
    float msAtk = 0.30f, msRel = 12.0f;      // fitted, §50

    void setSampleRate(float sr) {
        aAtk = 1.0f - std::exp(-1.0f / (msAtk * 1e-3f * sr));
        aRel = 1.0f - std::exp(-1.0f / (msRel * 1e-3f * sr));
    }
    void reset() { env[0]=env[1]=0.0f; g[0]=g[1]=1.0f; }

    inline float run(int c, float x, const Shaper &sh) {
        const float m = std::fabs(x);
        env[c] += (m > env[c] ? aAtk : aRel) * (m - env[c]);
        const float e = env[c] > 1e-6f ? env[c] : 1e-6f;
        const float target = sh.run(e) / e;        // the curve, as a GAIN
        g[c] += (target < g[c] ? aAtk : aRel) * (target - g[c]);
        return x * g[c];
    }
};

// ------------------------------------------------------------- pre-emphasis
//
// §35 measured that the fold law is FREQUENCY-WEIGHTED: the same amplitude
// sweep at four carriers gives the same SHAPE offset by ~5 dB, with 1 kHz and
// 3 kHz consistently hotter than 100 Hz and 300 Hz, and the H3=H1 crossover
// moving from amp 0.93 to 0.87. So the shaper is driven 2-3 dB harder at high
// frequencies.
//
// The shapers themselves were measured at ONE carrier (100 Hz) and were applied
// broadband, which cannot reproduce that. §46 traced the model's ~4.4 dB error
// floor — present even with almost nothing engaged, and growing as stages stack
// — to exactly this.
//
// Structure: shelf -> shaper -> INVERSE shelf. The pair is complementary, so a
// linear "shaper" leaves the response flat (which is what Farina measured for
// the device, §19 neutral flat within 2.4 dB) while a nonlinear one generates
// frequency-dependent harmonics. That is the mechanism, not a tone control
// bolted on to hit a number.
struct Emphasis {
    float a = 0.0f;            // one-pole split
    float A = 1.0f;            // high-band boost going in
    float z[2] = {0.0f, 0.0f}, zi[2] = {0.0f, 0.0f};

    void set(float fc, float boostDb, float sr) {
        a = 1.0f - std::exp(-2.0f * 3.14159265f * fc / sr);
        A = std::pow(10.0f, boostDb / 20.0f);
    }
    void reset() { z[0]=z[1]=zi[0]=zi[1]=0.0f; }
    inline float pre(int c, float x) {
        z[c] += a * (x - z[c]);
        return z[c] + A * (x - z[c]);          // lows flat, highs * A
    }
    inline float post(int c, float x) {
        zi[c] += a * (x - zi[c]);
        return zi[c] + (1.0f / A) * (x - zi[c]);
    }
};

// ---------------------------------------------------------------- Transients
//
// §41 measured law, ASYMMETRIC BY SIGN. Negative is a gate — the onset stays
// flat within 0.3 dB while the tail falls (-1.99 dB at -0.75). Positive raises
// BOTH, onset-weighted (+2.93 / +2.10 at +0.75), and is strongly nonlinear near
// the top: +1.0 reaches +8.02 dB of onset (§25), so most of the range lives in
// the last quarter.
//
// §34: it sits UPSTREAM of the saturation — a 23 dB monotonic span in H3 with
// no Drive at all, which is only possible if it changes what the saturation
// sees.
struct Transients {
    float aF = 0.0f, rF = 0.0f, aS = 0.0f, rS = 0.0f;
    float envF[2] = {0, 0}, envS[2] = {0, 0};
    float up = 0.0f, dn = 0.0f, us = 0.0f;
    // Fitting handles. Defaults are the shipped values; tools/fit_transients.py
    // drives them through the module's hidden _tr_* params so the law is fitted
    // END TO END against the measured onset/tail table, not on the isolated
    // stage — the measurement is of the whole device, and the saturation
    // downstream changes what any transient boost turns into.
    // FITTED SPECTRALLY against Live's own renders of the transient cells
    // (§45). NOT against the onset/tail table: that fit scored 0.368 dB on its
    // own summary and 5.002 dB spectrally — the WORST of the three — while the
    // hand-picked values scored 4.020. Matching two summary numbers per setting
    // says nothing about the audio between them.
    float upScale = 2.627f, upExp = 0.532f, dnScale = 0.814f, dnExp = 1.344f;
    // ⭑ The positive side needs a SUSTAIN term as well as an onset term. The
    // first version drove the boost purely from transient-ness, which is zero
    // during a decay, so it could never add sustain — fitted, it reproduced
    // +7.69 dB of onset and +0.01 dB of tail against a measured +3.38. The
    // manual's "adds attack AND sustain" (§25, §41) is structural, not a
    // description of a side effect.
    float upSus = 0.630f;
    float msFast = 1.507f, msRel = 50.0f, msSlow = 669.1f;   // fitted, §45

    float sr_ = 44100.0f;
    void setSampleRate(float sr) {
        sr_ = sr;
        aF = 1.0f - std::exp(-1.0f / (msFast * 1e-3f * sr));
        rF = 1.0f - std::exp(-1.0f / (msRel  * 1e-3f * sr));
        aS = 1.0f - std::exp(-1.0f / (0.001f * sr));    // 1 ms, shared attack
        rS = 1.0f - std::exp(-1.0f / (msSlow * 1e-3f * sr));
    }
    void reset() { envF[0] = envF[1] = envS[0] = envS[1] = 0.0f; }
    void set(float t) {
        // The two sides are separate laws because the measurement says they are.
        // Exponents chosen so +0.75 -> +2.93 dB and +1.0 -> +8.02 dB of onset,
        // and -0.75 -> -1.99 dB of tail with the onset flat.
        up = (t > 0.0f) ? std::pow(t, upExp) * upScale : 0.0f;
        us = (t > 0.0f) ? t * upSus : 0.0f;          // the sustain half
        dn = (t < 0.0f) ? std::pow(-t, dnExp) * dnScale : 0.0f;
    }
    inline void run(float &l, float &r) {
        float *ch[2] = {&l, &r};
        for (int c = 0; c < 2; c++) {
            const float m = std::fabs(*ch[c]);
            envF[c] += (m > envF[c] ? aF : rF) * (m - envF[c]);
            envS[c] += (m > envS[c] ? aS : rS) * (m - envS[c]);
            float g = 1.0f;
            if (up > 0.0f) {                       // onset-weighted boost
                float t = (envF[c] - envS[c]) / (envF[c] + 1e-6f);
                if (t < 0.0f) t = 0.0f;
                g *= std::exp2(up * t);
            }
            if (dn > 0.0f || us > 0.0f) {          // the tail term, both signs
                float t = (envS[c] - envF[c]) / (envF[c] + 1e-5f);
                if (t < 0.0f) t = 0.0f;
                if (t > 3.0f) t = 3.0f;
                if (dn > 0.0f) g *= std::exp2(-dn * t);
                if (us > 0.0f) g *= std::exp2( us * t);
            }
            *ch[c] *= g;
        }
    }
};

// ---------------------------------------------------------------- Boom
//
// §20: NOT a shelf. A resonant peak at BoomFrequency PLUS a high-pass that
// TRACKS it — tuned to 50 Hz it reads +4.5 dB at 45 Hz and -7.8 dB at 20 Hz,
// and the 20 Hz point moves +0.07 / -7.77 / -14.33 / -23.35 dB as the tuning
// goes 30 / 50 / 70 / 90. That cut is what stops a sub generator adding
// subsonic mud. §34: it also contributes EVEN harmonics, so the generator is
// nonlinear rather than a plain filter.
//
// CAMPAIGN 2 (2026-09-10): BoomDecay tying its whole range to Q — the first
// attempt in this file, twice — turned out to be the wrong mechanism, not
// just wrongly tuned. Measured directly, with a clean isolated impulse: a
// resonator's OWN state decay can be damped shorter by extra per-sample
// "leak," but it can never be made to ring LONGER than its Q already allows
// — Q sets an upper bound, and no amount of tuning the decay side of the
// equation can put ring back in once Q has damped it away. Confirmed against
// a real Ableton reference render (Josh's `rig/sets/boomdecay*`, this
// session) that BoomDecay does NOT interact with BoomFrequency or BoomAmount
// (the decay=1 vs decay=0 spread is flat to ~1 dB across 30-90 Hz and across
// 0.3-1.0 Amount) — so whatever the real mechanism is, it does not need a
// frequency- or amount-dependent law, which simplifies this a lot.
//
// So: Q is now FIXED, high enough to physically sustain a real multi-hundred-
// ms ring on its own (this is what campaign 1 got backwards — it kept Q low
// "for safety" and tried to get ring time from elsewhere, which cannot work).
// BoomDecay instead drives a SEPARATE per-hit amplitude envelope — fast
// attack (latches onto a transient immediately), decay/release time
// geometric in BoomDecay — that multiplies the resonator's output. It can
// only ever SHORTEN what Q's fixed, long natural ring already provides:
// short release at BoomDecay=0 cuts it down to a tight thump; long release
// at BoomDecay=1 gets out of the way and lets the full natural ring through.
// That is the correct direction for a decay control, and it is why campaign
// 1's mechanism — no matter how it was tuned — could only ever produce a
// SHORTER, never a LONGER, effective ring than a low, safe Q already gives.
//
// Retrigger logic: `trig` is a fast (~1 ms) envelope follower on the same
// tracking-highpassed excitation that drives the resonator. Whenever a new
// hit's `trig` exceeds the currently-decaying `env`, `env` snaps UP to it
// (a louder new hit always wins); otherwise `env` decays at the release rate.
// Standard peak-hold-with-release, the same shape a real analog boom/808 sub
// trigger uses.
//
// 🔴 FOUND WHILE CALIBRATING THE ABOVE: Q was NEVER FUNCTIONAL. The bandpass
// recursion computed here (`bp = (bq1 + g*hp) / (1 + g*(g+k))`) never feeds
// the lowpass integrator's own state back into the numerator — a real
// resonant filter needs that feedback (subtracting the accumulated lowpass
// energy from the excitation) to actually resonate; without it, `k` (1/Q)
// only nudges a denominator that is ~1.0006 at Q=6 and ~1.0018 at Q=2, at
// 50 Hz/44100 Hz — a <0.2% difference across a 40x range of Q, checked by
// hand. That is why every attempt in this file to control ring time via Q
// measured as nearly inert regardless of how it was tuned, all the way back
// to the very first "1.2 + 2*decay" law: Q was cosmetic the whole time, not
// merely mistuned. This was inherited from `dr32`'s original implementation,
// so it likely predates this module.
//
// Replaced with the textbook topology-preserving-transform SVF (Zavalishin /
// "Andy Simper" form) — TWO integrator states (`ic1`, `ic2`) where `ic2` is
// subtracted from the excitation before the bandpass is computed, which is
// the feedback path a resonator actually needs:
//   v3 = in - ic2;  v1 = a1*ic1 + a2*v3;  v2 = ic2 + a2*ic1 + a3*v3;
//   bp = v1;  ic1 = 2*v1 - ic1;  ic2 = 2*v2 - ic2;
// Verified by direct measurement (an isolated impulse, `_boom_q` swept) that
// this ACTUALLY changes ring time with Q, unlike the formula it replaces.
//
// FITTED — for real this time — against a fresh Ableton reference render
// Josh made this session (`rig/sets/boomdecay Project/boomdecay.als`, a
// purpose-built punchy probe, `rig/probes/punch.wav`, chosen because it
// isolates Boom's own ring from the excitation far better than the shared
// `hits.wav`; `measurements.md` §40's table did not reproduce on the real
// device with our own probes and is NOT used here). `tools/fit_boom_decay.py`
// still targets the abandoned §40 numbers — see its own docstring — but its
// render/checkpoint machinery is what this fit reused; only the target table
// and the fitted parameters (Q, relMsLo, relMsHi, not qLo/qHi/tauLoMs/tauHiMs
// — that whole mechanism is gone, replaced by the real feedback fix above)
// changed. Result: rms error **4.97 dB** against the real device, was ~39-44
// dB before the feedback fix (Q literally could not do anything before this).
// Checked for stability: rendered a full repeated-hit probe (`hits.wav`,
// hits every 250 ms — comparable to Q's own ~370 ms ring at these settings)
// and the level settles into a periodic pattern, not runaway growth.
struct Boom {
    float g = 0.0f, k = 0.0f, a1 = 0.0f, a2 = 0.0f, a3 = 0.0f, hpA = 0.0f, amount = 0.0f;
    float Q = 33.73f;                            // fixed — see note above
    float aTrig = 0.0f, relCoef = 1.0f;
    float relMsLo = 45.63f, relMsHi = 1774.0f;   // fitted; see note above

    void set(float hz, float amt, float decay, float sr) {
        amount = amt;
        const float wc = 2.0f * 3.14159265f * hz / sr;
        g = std::tan(0.5f * wc);
        k = 1.0f / Q;
        a1 = 1.0f / (1.0f + g * (g + k));
        a2 = g * a1;
        a3 = g * a2;
        hpA = 1.0f - std::exp(-wc);          // the tracking high-pass, §20
        aTrig = 1.0f - std::exp(-1.0f / (0.001f * sr));   // ~1 ms, latches onto a hit fast
        const float d01 = decay < 0.0f ? 0.0f : (decay > 1.0f ? 1.0f : decay);
        const float relMs = relMsLo * std::pow(relMsHi / relMsLo, d01);
        relCoef = std::exp(-1.0f / (relMs * 1e-3f * sr));
    }
    void reset() {}
};

// ---------------------------------------------------------------- the device
struct DrumBuss {
    float sr = 44100.0f;
    Params p;
    Comp comp;
    OnePoleLP damp;
    Boom boom;

    void setSampleRate(float s) {
        sr = (s > 1.0f) ? s : 44100.0f;
        comp.setSampleRate(sr);
        trans.setSampleRate(sr);
        lim.setSampleRate(sr);
        applyAll();
    }
    void reset() {
        comp.reset(); damp.reset(); boom.reset(); trans.reset(); emph.reset(); lim.reset();
        upL.reset(); upR.reset(); dnL.reset(); dnR.reset();
        ic1[0]=ic1[1]=ic2[0]=ic2[1]=bhp[0]=bhp[1]=0.0f;
        trig[0]=trig[1]=boomEnv[0]=boomEnv[1]=0.0f;
    }

    void apply() {
        damp.set(p.dampHz, sr);
        boom.set(p.boomHz, p.boom, p.boomDecay, sr);
    }

    Shaper drive, crunchShaper;
    Transients trans;
    Emphasis emph;
    Folder folder;
    Limiter lim;
    Halfband upL, upR, dnL, dnR;
    bool oversample = true;
    int shapeMode = 0;          // 0 folder (soft), 1 limiter (med), 2 table (hard)
    // ⚠ OFF by default (0 dB = a no-op). §47: fitted against the four-carrier
    // data it moved the objective from 12.181 to 12.043 dB — i.e. nothing, and
    // the 12 dB baseline is the real problem. The mechanism is real and
    // measured (§35) but is not what limits the model, so it ships inert rather
    // than tuned to look useful. The code stays because the finding is real.
    float emphFc = 600.0f, emphDb = 0.0f;

    // §38 pre-gain laws, quadratic in Drive, fitted to under 0.1 dB rms.
    static float medGainDb(float d)    { return -3.162f*d*d + 15.003f*d - 1.931f; }
    static float hardGainDb(float d)   { return  7.768f*d*d +  4.984f*d - 0.779f; }
    static float crunchGainDb(float d) { return -1.015f*d*d +  7.832f*d - 1.896f; }

    // §20: Boom's high-pass TRACKS the tuning, which is what stops a sub
    // generator adding subsonic mud (-7.8 dB at 20 Hz when tuned to 50).
    // §34: it also makes even harmonics, so the generator is nonlinear.
    // `ic1`/`ic2` are the resonator's own two integrator states (the TPT SVF
    // this now is — see the note at Boom's definition for why the old
    // `bq1`/`bq2` recursion never actually resonated), run at Boom's FIXED Q
    // with no extra damping — a correctly-implemented TPT filter is already
    // unconditionally stable at any Q, so it needs none. `trig`/`boomEnv` are
    // the separate per-hit amplitude envelope BoomDecay actually controls.
    float ic1[2] = {0,0}, ic2[2] = {0,0}, bhp[2] = {0,0};
    float trig[2] = {0,0}, boomEnv[2] = {0,0};

    inline void runBoom(float &l, float &r) {
        if (p.boom <= 0.0f) return;
        float *ch[2] = {&l, &r};
        for (int c = 0; c < 2; c++) {
            const float x = *ch[c];
            bhp[c] += boom.hpA * (x - bhp[c]);
            const float hp = x - bhp[c];                 // tracking high-pass

            // Per-hit amplitude envelope: a fast follower on the same signal
            // that excites the resonator, latching boomEnv UP to any louder
            // new hit and otherwise releasing at BoomDecay's rate. This can
            // only ever shorten the resonator's own natural ring, never
            // lengthen it — see Boom's definition for why that is the point.
            trig[c] += boom.aTrig * (std::fabs(hp) - trig[c]);
            if (trig[c] > boomEnv[c]) boomEnv[c] = trig[c];
            else boomEnv[c] *= boom.relCoef;

            // TPT SVF, bandpass output — v3 subtracts the LOWPASS integrator
            // (ic2) from the excitation, which is the resonant feedback path
            // the old formula was missing.
            const float v3 = hp - ic2[c];
            const float v1 = boom.a1 * ic1[c] + boom.a2 * v3;
            const float v2 = ic2[c] + boom.a2 * ic1[c] + boom.a3 * v3;
            const float bp = v1;
            ic1[c] = 2.0f * v1 - ic1[c];
            ic2[c] = 2.0f * v2 - ic2[c];
            // nonlinear: §34 measured elevated H2 with Boom up
            const float sub = std::tanh(bp * 1.6f) * 0.625f;
            *ch[c] = x + boom.amount * 2.2f * sub * boomEnv[c];
        }
    }

    void applyAll() {
        apply();
        emph.set(emphFc, emphDb, sr);
        drive.select(p.driveType);
        drive.setDrive(p.drive);
        folder.setDrive(p.drive);
        // soft = folder (§48). med and hard = tables.
        // ⚠ med was tried as a LIMITER (§50) on the theory that a right curve
        // with too many harmonics means smooth gain reduction rather than
        // waveshaping — the tutorial calls it "limiting distortion". MEASURED
        // AND REJECTED: 9.95 dB against the table's 4.16, degrading
        // monotonically as release lengthens, i.e. the data wants LESS memory,
        // not more. The Limiter struct is kept for the record but is not in the
        // path.
        shapeMode = (p.driveType == 0) ? 0 : 2;
        crunchShaper.selectCrunch();
        crunchShaper.setDrive(p.crunch);
        trans.set(p.trans);
    }

    // One sample through the shaping section: drive character, then Crunch.
    inline float shape(int c, float x) {
        if (shapeMode == 0)      x = folder.run(x);          // §48 soft folds
        else if (emphDb != 0.0f) x = emph.post(c, drive.run(emph.pre(c, x)));
        else                     x = drive.run(x);
        if (p.crunch > 0.0f)     x = crunchShaper.run(x);
        return x;
    }

    // Block processing. Order is the MEASURED one; see the header.
    void process(float *io, int n) {
        const float outG = p.outGain;
        if (neutral()) {                       // DryWet 0 only — see neutral()
            if (outG != 1.0f)
                for (int i = 0; i < 2 * n; i++) io[i] *= outG;
            return;
        }
        const float mix = p.dryWet;
        for (int i = 0; i < n; i++) {
            const float dl = io[2*i], dr = io[2*i+1];
            float l = dl * p.trim, r = dr * p.trim;      // §13 Trim is PRE
            trans.run(l, r);                             // §34 upstream of sat
            if (p.comp) comp.run(l, r);                  // §23 upstream of dist
            // --- the shaping section, 2x oversampled (§51) -------------------
            if (oversample) {
                // up: zero-stuff, filter, x2 for the interpolation gain
                upL.push(l); const float lA = 2.0f * upL.filt();
                upL.push(0.0f); const float lB = 2.0f * upL.filt();
                upR.push(r); const float rA = 2.0f * upR.filt();
                upR.push(0.0f); const float rB = 2.0f * upR.filt();
                // shape at 2x
                dnL.push(shape(0, lA)); dnL.push(shape(0, lB));
                dnR.push(shape(1, rA)); dnR.push(shape(1, rB));
                // down: filter, take one of two
                l = dnL.filt(); r = dnR.filt();
            } else {
                l = shape(0, l); r = shape(1, r);
            }
            damp.run(l, r);                              // §24 after Crunch
            runBoom(l, r);
            l = dl + (l - dl) * mix;                     // Dry/Wet across the stage
            r = dr + (r - dr) * mix;
            io[2*i]   = l * outG;                        // §13 Output is POST
            io[2*i+1] = r * outG;
        }
    }

    // 🔴 THE ONLY TRUE BYPASS IS DryWet = 0 (§14).
    //
    // ⚠ This started life checking "every control at rest", inherited from the
    // DR32 stage this module grew out of, where neutral WAS transparent. Drum
    // Buss is not: at its defaults it applies about +3.8 dB and SATURATES
    // (§2, §4), measured on the held-out validation material as +3.04 dB with
    // the peak pushed from 0.85 to 0.998. The wrong bypass cost 3 dB on every
    // preset in the first validation run, and is exactly the kind of inherited
    // assumption this campaign exists to remove.
    bool neutral() const { return p.dryWet <= 0.0f; }
};

}  // namespace drumbuss
