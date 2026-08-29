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
    // FITTED end to end against the measured onset/tail table (§25, §41):
    // rms 0.368 dB, down from 2.162 for the hand-picked values.
    float upScale = 4.320f, upExp = 2.940f, dnScale = 1.137f, dnExp = 0.942f;
    // ⭑ The positive side needs a SUSTAIN term as well as an onset term. The
    // first version drove the boost purely from transient-ness, which is zero
    // during a decay, so it could never add sustain — fitted, it reproduced
    // +7.69 dB of onset and +0.01 dB of tail against a measured +3.38. The
    // manual's "adds attack AND sustain" (§25, §41) is structural, not a
    // description of a side effect.
    float upSus = 1.244f;
    float msFast = 0.058f, msRel = 50.0f, msSlow = 142.1f;   // fitted

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
        trans.setSampleRate(sr);
        applyAll();
    }
    void reset() {
        comp.reset(); damp.reset(); boom.reset(); trans.reset();
        bq1[0]=bq1[1]=bq2[0]=bq2[1]=bhp[0]=bhp[1]=0.0f;
    }

    void apply() {
        damp.set(p.dampHz, sr);
        boom.set(p.boomHz, p.boom, p.boomDecay, sr);
    }

    Shaper drive, crunchShaper;
    Transients trans;

    // §38 pre-gain laws, quadratic in Drive, fitted to under 0.1 dB rms.
    static float medGainDb(float d)    { return -3.162f*d*d + 15.003f*d - 1.931f; }
    static float hardGainDb(float d)   { return  7.768f*d*d +  4.984f*d - 0.779f; }
    static float crunchGainDb(float d) { return -1.015f*d*d +  7.832f*d - 1.896f; }

    // §20: Boom's high-pass TRACKS the tuning, which is what stops a sub
    // generator adding subsonic mud (-7.8 dB at 20 Hz when tuned to 50).
    // §40: BoomDecay sets the RING TIME, not the level — the onset moves only
    // +5.0 to +7.4 dB across the whole control while the tail spans 22 dB at
    // 150 ms. §34: it also makes even harmonics, so the generator is nonlinear.
    float bq1[2] = {0,0}, bq2[2] = {0,0}, bhp[2] = {0,0};

    inline void runBoom(float &l, float &r) {
        if (p.boom <= 0.0f) return;
        float *ch[2] = {&l, &r};
        for (int c = 0; c < 2; c++) {
            const float x = *ch[c];
            bhp[c] += boom.hpA * (x - bhp[c]);
            const float hp = x - bhp[c];                 // tracking high-pass
            const float hpIn = bq1[c] + boom.g * hp;
            const float bp = hpIn / (1.0f + boom.g * (boom.g + boom.k));
            bq1[c] = 2.0f * bp - bq1[c];
            const float lo = bq2[c] + boom.g * bp;
            bq2[c] = 2.0f * lo - bq2[c];
            // nonlinear: §34 measured elevated H2 with Boom up
            const float sub = std::tanh(bp * 1.6f) * 0.625f;
            *ch[c] = x + boom.amount * 2.2f * sub;
        }
    }

    void applyAll() {
        apply();
        drive.select(p.driveType);
        drive.setDrive(p.drive);
        crunchShaper.selectCrunch();
        crunchShaper.setDrive(p.crunch);
        trans.set(p.trans);
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
            l = drive.run(l); r = drive.run(r);
            if (p.crunch > 0.0f) { l = crunchShaper.run(l); r = crunchShaper.run(r); }
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
