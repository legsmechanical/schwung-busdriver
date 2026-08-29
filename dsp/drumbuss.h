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

// ---------------------------------------------------------------- Boom
//
// §20: NOT a shelf. A resonant peak at BoomFrequency PLUS a high-pass that
// TRACKS it — tuned to 50 Hz it reads +4.5 dB at 45 Hz and -7.8 dB at 20 Hz,
// and the 20 Hz point moves +0.07 / -7.77 / -14.33 / -23.35 dB as the tuning
// goes 30 / 50 / 70 / 90. That cut is what stops a sub generator adding
// subsonic mud. §34: it also contributes EVEN harmonics, so the generator is
// nonlinear rather than a plain filter.
//
// TODO(campaign3): the resonance Q and the decay law. BoomDecay moved steady
// state only ~1 dB at 125 Hz, so it is temporal and needs the hits segment.
struct Boom {
    float bpZ1 = 0.0f, bpZ2 = 0.0f, hpZ = 0.0f;
    float g = 0.0f, k = 0.0f, hpA = 0.0f, amount = 0.0f;

    void set(float hz, float amt, float decay, float sr) {
        amount = amt;
        const float wc = 2.0f * 3.14159265f * hz / sr;
        g = std::tan(0.5f * wc);
        // TODO(campaign3): Q from the measured peak width; decay from hits.
        const float Q = 1.2f + 2.0f * decay;
        k = 1.0f / Q;
        hpA = 1.0f - std::exp(-wc);          // the tracking high-pass, §20
    }
    void reset() { bpZ1 = bpZ2 = hpZ = 0.0f; }
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
        apply();
    }
    void reset() { comp.reset(); damp.reset(); boom.reset(); }

    void apply() {
        damp.set(p.dampHz, sr);
        boom.set(p.boomHz, p.boom, p.boomDecay, sr);
    }

    // §14: DryWet 0 is a TRUE bypass, measured — slope 0.999, ceiling 0.996,
    // two-tone gains 0.00 dB. So it must null, not merely be quiet.
    bool neutral() const {
        return !p.comp && p.drive <= 0.0f && p.crunch <= 0.0f &&
               p.dampHz >= 19999.0f && std::fabs(p.trans) <= 1e-4f &&
               p.boom <= 0.0f && p.dryWet >= 1.0f;
    }
};

}  // namespace drumbuss
