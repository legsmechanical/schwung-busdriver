// ============================================================================
//  drumbus.h — the Drum Bus glue stage.
//
//  Lifted whole from schwung-dr32's dsp/dr32_fxbus.cpp, where it was the
//  always-on master stage over the summed kit mix. It has no dependency on the
//  kit engine, which is why it can stand alone. Every number in here was
//  measured, and the comments record what was tried and rejected — read them
//  before retuning anything.
//
//  Stages, in order: Attack -> Sustain -> Crunch -> Compress -> makeup.
//  Compress is Airwindows Pop3 (MIT, vendored verbatim); everything else is
//  original to this project.
// ============================================================================
#pragma once
#include <cmath>
#include <cstring>
#include "../vendor/airwindows/airwin_dyn.h"

namespace drumbus {

/** Drum Bus — a drum-bus glue insert in the spirit of Ableton's Drum Buss.
 *
 *  Signal order is Attack -> Sustain -> Crunch -> Compress -> makeup, then the
 *  caller applies Mix (a dry/wet blend, i.e. parallel compression) and Output.
 *
 *    Compress   — Airwindows *Pop3*'s compressor section, driven by ONE knob
 *                 that sweeps a coordinated threshold + ratio + release
 *                 program, followed by our own makeup gain.
 *    Crunch     — full-band saturation: tanh soft knee, a cubic term for grit,
 *                 and a deliberate asymmetry so it produces EVEN harmonics too.
 *    Attack     — fast/smoothed envelope pair, shaping the onset only.
 *    Sustain    — dual-release envelope detector shaping the decay only.
 *
 *  Attack and Sustain are orthogonal AND symmetric by measurement: sweeping
 *  Sustain end to end moves the tail -8.0 to +11.9 dB with the attack at
 *  0.00 dB, and sweeping Attack moves the hit -14.5 to +14.6 dB with the tail
 *  at 0.00 dB. Attack is also program-dependent — a 40 ms swell gets about half
 *  the treatment of a real hit, and steady material moves 0.17 dB.
 *
 *  ── why not what was here before ────────────────────────────────────────
 *  The previous Compress was Airwindows Pressure4, a vari-mu LEVELLER. It was
 *  measured against a drum groove and failed on every count that matters here:
 *
 *    - no threshold at all. Its curve was ~2:1 across the WHOLE range, so a
 *      -48 dBFS signal came out at -30 dBFS: +17.7 dB of lift applied to
 *      sample noise floor, room bleed and reverb tails.
 *    - half the knob was dead — comp=0.50 produced 0.3 dB of gain reduction,
 *      and even at 1.00 only 4.8 dB.
 *    - ~20 ms to reach full gain reduction, so it never caught a kick
 *      (measured kick GR at full knob: 2.0 dB).
 *    - backwards on a groove: a hat landing after a kick came out 17.8 dB
 *      quieter than an isolated hat. It buried the hats instead of holding
 *      the kick.
 *
 *  Pop3 fixes this structurally, not by tuning. Its gain is
 *  (1-ratio) + (popComp*ratio) with popComp clamped to [0,1], so it can only
 *  ever ATTENUATE — measured 0.00 dB of lift on a -48 dBFS sine at every
 *  setting. Makeup is therefore ours to apply deliberately.
 *
 *  The old Transients stage was a single broadband gain from the ratio of two
 *  envelope followers, so the tail tracked the attack instead of opposing it:
 *  at knob 0 it took the attack down 18.1 dB and the tail down 3.0 dB. There
 *  was no sustain control anywhere on it, despite the comment claiming one.
 *  Both stages now use in-house detectors that are symmetric by construction
 *  and target disjoint parts of the hit.
 */
struct DrumBuss {
    float fs = 44100.0f;

    awk_pop3::Pop3   comp;      // compressor (its gate section is left off)
    /** Attack section.
     *
     *  Was Airwindows Point, which is excellent at SHARPENING and nearly inert
     *  at softening — the whole lower half of the knob bought under 2 dB
     *  (measured -1.92 dB at 0.00, -0.10 dB at 0.375) against +8.54 dB at the
     *  top. That is structural, not tuning: Point boosts by DIVIDING the slow
     *  follower's rate (nibDiv/(1.001-x), which reaches 3.1x) and softens by
     *  MULTIPLYING it (nibDiv*(1.001-(0.75x)^2), which cannot get past 0.44x).
     *  The softening direction simply cannot travel.
     *
     *  So the detector is ours, and symmetric by construction: a fast peak
     *  follower, and a slow SMOOTHING of that follower. Their difference is
     *  large only while the fast one is outrunning the smoothed one, i.e. at an
     *  onset.
     *
     *  The smoothed follower is what makes this attack-only. During a decay it
     *  lags ABOVE the fast one, so the difference goes negative and clamps to
     *  zero — the tail is untouched. An earlier version used two followers with
     *  different ATTACKS and a shared release; that never reconverged, because
     *  two envelopes falling at the same exponential rate keep whatever gap
     *  they had, so its "transient" reading stayed constant through the decay
     *  and the stage became a broadband gain (measured: attack AND tail both
     *  moved together). */
    struct Attack {
        float aFast = 0.0f, rFast = 0.0f, aSmooth = 0.0f;
        float envF[2] = { 0.0f, 0.0f }, envS[2] = { 0.0f, 0.0f };
        float depth = 0.0f;
        void setSampleRate(float fs) {
            aFast   = 1.0f - expf(-1.0f / (0.0005f * fs));  // 0.5 ms attack
            rFast   = 1.0f - expf(-1.0f / (0.050f * fs));   // 50 ms release
            aSmooth = 1.0f - expf(-1.0f / (0.030f * fs));   // 30 ms, both ways
        }
        void reset() { envF[0] = envF[1] = envS[0] = envS[1] = 0.0f; }
        inline void run(float *l, float *r, int n) {
            float *ch[2] = { l, r };
            for (int c = 0; c < 2; c++) {
                for (int i = 0; i < n; i++) {
                    float m = fabsf(ch[c][i]);
                    envF[c] += (m > envF[c] ? aFast : rFast) * (m - envF[c]);
                    envS[c] += aSmooth * (envF[c] - envS[c]);
                    // Normalised by envF, NOT by envS. Dividing by the
                    // smoothed follower looks equivalent and is not: coming out
                    // of silence envS is ~0, so the ratio explodes for ANY
                    // onset however gradual. Measured, that version applied an
                    // identical +-16.26 dB to a 3 ms click and to a 25 ms
                    // fade-in — a fixed gain on the first few ms, not transient
                    // shaping. Against envF the quantity is bounded in [0,1]
                    // and reads as "what fraction of this moment is faster than
                    // the local average", which is what transient-ness means.
                    float t = (envF[c] - envS[c]) / (envF[c] + 1e-6f);
                    if (t < 0.0f) t = 0.0f;      // decay: smoothed sits above
                    if (t > 1.0f) t = 1.0f;
                    float g = exp2f(depth * t);
                    if (g < 0.05f) g = 0.05f;
                    if (g > 12.0f) g = 12.0f;
                    ch[c][i] *= g;
                }
            }
        }
    } atk;

    /** Sustain section.
     *
     *  Point is the right machine for ATTACK but the wrong one for sustain: it
     *  detects "how much louder is now than the local average", and slowing it
     *  down enough to straddle a decay just makes both followers average the
     *  whole hit, so it becomes a broadband level control. Measured at a 104 ms
     *  reaction it moved attack +15.8 dB and tail +13.4 dB TOGETHER — the same
     *  failure as the stage this replaces.
     *
     *  A sustain control needs a detector that is quiet at the onset and grows
     *  through the decay. Two followers sharing an attack but with different
     *  RELEASE times do exactly that: they track together while the signal
     *  rises, then the long-release one sits above the short-release one for
     *  the whole tail. Their ratio is 1 at the hit and climbs afterwards, so
     *  the gain lands on the decay and leaves the transient alone. */
    struct Sustain {
        float aAtt = 0.0f, rFast = 0.0f, rSlow = 0.0f;
        float envF[2] = { 0.0f, 0.0f }, envS[2] = { 0.0f, 0.0f };
        float depth = 0.0f;
        void setSampleRate(float fs) {
            aAtt  = 1.0f - expf(-1.0f / (0.001f * fs));   // 1 ms, shared
            rFast = 1.0f - expf(-1.0f / (0.050f * fs));   // 50 ms
            rSlow = 1.0f - expf(-1.0f / (0.400f * fs));   // 400 ms
        }
        void reset() { envF[0] = envF[1] = envS[0] = envS[1] = 0.0f; }
        inline void run(float *l, float *r, int n) {
            float *ch[2] = { l, r };
            for (int c = 0; c < 2; c++) {
                for (int i = 0; i < n; i++) {
                    float m = fabsf(ch[c][i]);
                    envF[c] += (m > envF[c] ? aAtt : rFast) * (m - envF[c]);
                    envS[c] += (m > envS[c] ? aAtt : rSlow) * (m - envS[c]);
                    // 0 at the onset and in steady state, positive through decay
                    float t = (envS[c] - envF[c]) / (envF[c] + 1e-5f);
                    if (t < 0.0f) t = 0.0f;
                    if (t > 3.0f) t = 3.0f;
                    // exp2f, not powf(2,x): this runs per sample.
                    float g = exp2f(depth * t);
                    if (g < 0.06f) g = 0.06f;
                    if (g > 8.0f)  g = 8.0f;
                    ch[c][i] *= g;
                }
            }
        }
    } sus;

    float crunch = 0.0f;
    float makeup = 1.0f;
    float crunchNorm = 1.0f;
    // Output trim, linear. Sits AFTER the auto-makeup and is the user's own
    // level match on top of it — the makeup is capped at +15 dB and gated on
    // real signal, so it can leave a heavily-compressed bus short, or a
    // crunch-only setting hot. Applied inside processBlock so that Mix upstream
    // stays a genuine dry/wet of the finished stage rather than a fader on it.
    float outGain = 1.0f;
    bool  compOn = false, atkOn = false, susOn = false;
    // DC blocker state — the asymmetric term in the saturator produces an
    // offset by construction, and an offset on a drum bus eats headroom and
    // makes the compressor below it behave differently on each polarity.
    float dcX[2] = { 0.0f, 0.0f }, dcY[2] = { 0.0f, 0.0f };

    void setSampleRate(float sr) {
        fs = (sr > 1.0f) ? sr : 44100.0f;
        comp.setSampleRate(fs);
        atk.setSampleRate(fs);
        sus.setSampleRate(fs);
    }

    static float clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

    /** p1 compress, p2 crunch, p3 attack (0.5 neutral), p4 sustain (0.5 neutral). */
    void setParams(float p1, float p2, float p3, float p4) {
        const float c = clamp01(p1);
        crunch = clamp01(p2);
        compOn = c > 0.001f;

        // --- one knob, a coordinated program ---------------------------------
        // Threshold, ratio and release all move together, on a SQUARED taper.
        //
        // The first version drove them linearly and started the ratio at 0.30,
        // so the knob stepped straight into audible compression the moment it
        // left zero and then had little left to give: measured hat-duck went
        // -1.2 / -3.6 / -7.5 / -14.5 dB across the knob. Squaring spreads the
        // gentle half out and saves the violence for the top, and the top now
        // reaches further than it used to (threshold to -38 dBFS, ratio to a
        // full limit, release down to ~55 ms so it pumps rather than just
        // flattens).
        //
        // Attack stays pinned near Pop3's fastest (~11 ms) at every setting:
        // slow enough to let the beater click through, fast enough to catch the
        // body. That is what keeps click-to-body positive as this is pushed.
        // Exponent chosen off the measured duck curve, not by feel. Linear stepped
        // straight into audible compression (-1.2 dB of duck at knob 0.25) and
        // had little left at the top. 1.6 keeps the bottom genuinely subtle
        // (-0.22 dB at 0.30) while leaving real glue through the middle
        // (-1.4 at 0.50, -4.4 at 0.70) and saving the violence for the end
        // (-11.5 at 0.90, -21.5 at 1.00). A square law was tried and left the
        // whole bottom half inert.
        const float cc = powf(c, 1.6f);
        const float thrDb  = -4.0f - 34.0f * cc;
        const float thrLin = powf(10.0f, thrDb / 20.0f);
        comp.A = powf(thrLin, 0.25f);                 // compThresh = A^4
        const float ratio  = 0.06f + 0.94f * cc;
        comp.B = 1.0f - sqrtf(1.0f - ratio);          // compRatio = 1-(1-B)^2
        comp.C = 0.10f;                               // ~11.5 ms attack
        comp.D = 0.62f - 0.10f * cc;                  // ~115 ms down to ~55 ms
        comp.E = 0.0f;  comp.F = 0.0f;                // gate section off
        comp.G = 0.5f;  comp.H = 0.5f;

        // Makeup is measured, not predicted — see makeupTrack() below. A static
        // analytic makeup was tried first and was badly wrong: computing the
        // gain the compressor would apply to a full-scale steady peak gave
        // +21 dB at the top of the knob, because an 11 ms attack never reaches
        // that steady state on a drum hit. It re-created the exact +17.7 dB
        // low-level lift that Pop3 was brought in to eliminate.

        // --- transient shaping ------------------------------------------------
        // Point's B is bipolar around 0.5; C sets the detector timescale via
        // nibDiv = 1/(C+0.2)^7, so LOWER C is SLOWER (C=0.10 is a ~104 ms
        // follower, C=0.62 only ~0.1 ms). Getting that backwards once made the
        // "sustain" control shape the attack instead of the tail.
        //
        // Its taper also explodes at the very top — B=1 divides by 1.001-1.0
        // and measured +53 dB of attack — so the range is restricted to the
        // band where the response stays monotonic.
        atkOn = fabsf(p3 - 0.5f) > 0.005f;
        susOn = fabsf(p4 - 0.5f) > 0.005f;
        // Signed depth, so up sharpens and down softens by comparable amounts.
        atk.depth = clampBi(p3) * 2.6f;   // +-15.6 dB at a fully transient onset
        // Sustain depth is signed: up lengthens the tail, down shortens it.
        sus.depth = clampBi(p4) * 1.15f;

        recalcCrunch();
    }

    static float clampBi(float v) {                    // 0..1 -> -1..+1
        float b = (v - 0.5f) * 2.0f;
        return b < -1.0f ? -1.0f : (b > 1.0f ? 1.0f : b);
    }

    /** The saturation curve, before makeup.
     *
     *  tanh alone is an ODD function, so the old Crunch measured H2 at -123 dB
     *  — no even harmonics at any drive, which is why it read as fuzz rather
     *  than warmth. The `asym` term is a squared component and is what puts
     *  energy into H2; it costs a DC offset, removed downstream. */
    inline float shape(float x) const {
        const float d  = x * (1.0f + crunch * 24.0f);
        const float sh = tanhf(d);
        const float asym = 0.14f * crunch;
        return sh - 0.15f * sh * sh * sh + asym * sh * sh;
    }

    void recalcCrunch() {
        // Output normalisation, MEASURED over a reference sine rather than
        // assumed: a fixed reference point got this wrong by 8 dB once already.
        const int   K = 64;
        const float amp = 0.3f;
        double in2 = 0.0, out2 = 0.0;
        for (int i = 0; i < K; i++) {
            float x = amp * sinf(2.0f * 3.14159265f * (float)i / (float)K);
            float y = shape(x);
            in2 += (double)x * x;
            out2 += (double)y * y;
        }
        crunchNorm = (out2 > 1e-12) ? (float)std::sqrt(in2 / out2) : 1.0f;
    }

    void reset() {
        comp.reset(); atk.reset(); sus.reset();
        dcX[0] = dcX[1] = dcY[0] = dcY[1] = 0.0f;
        makeup = 1.0f;
    }

    /** Auto makeup, MEASURED per block rather than predicted.
     *
     *  Pop3 only ever attenuates, so something has to put the level back or
     *  the Compress knob is just a volume control that goes down. Comparing
     *  the block's RMS either side of the compressor gives the gain reduction
     *  actually applied to actual program material — which for an 11 ms attack
     *  is far less than the steady-state maths predicts.
     *
     *  It is smoothed over ~300 ms so it behaves like makeup and not like a
     *  second, faster compressor, gated on real signal so silence cannot make
     *  it drift upward, and capped: without a cap, a bus fed something already
     *  limited would wind the makeup up indefinitely. */
    void makeupTrack(const float *a, const float *b, int n, double inSq) {
        double outSq = 0.0;
        for (int i = 0; i < n; i++) outSq += (double)a[i] * a[i] + (double)b[i] * b[i];
        // -60 dBFS worth of block energy: below this there is nothing to match.
        if (inSq < 1e-6 * (double)n || outSq <= 1e-20) return;
        float target = (float)std::sqrt(inSq / outSq);
        if (target < 1.0f) target = 1.0f;              // never attenuate further
        if (target > 5.6f) target = 5.6f;              // +15 dB ceiling
        const float alpha = 1.0f - expf(-(float)n / (0.30f * fs));
        makeup += (target - makeup) * alpha;
    }

    /** Block processing: Point and Pop3 both hoist a pile of pow() calls to the
     *  top of their loop, so running them one sample at a time would pay that
     *  cost 44100 times a second. */
    void processBlock(float *io, int n, float *sl, float *sr) {
        for (int i = 0; i < n; i++) { sl[i] = io[2 * i]; sr[i] = io[2 * i + 1]; }
        float *in[2] = { sl, sr }, *out[2] = { sl, sr };

        if (atkOn) atk.run(sl, sr, n);
        if (susOn) sus.run(sl, sr, n);

        if (crunch > 0.0f) {
            // Full-band. An earlier version split at ~1.2 kHz and folded only
            // the top, which audibly thinned the kick — that is EQ, not
            // saturation. Verified spectrum-neutral: 60 Hz and 6 kHz tones come
            // out with the same balance they went in with.
            const float R = 1.0f - 2.0f * 3.14159265f * 10.0f / fs;   // ~10 Hz DC block
            for (int c = 0; c < 2; c++) {
                float *ch = c ? sr : sl;
                for (int i = 0; i < n; i++) {
                    float x = ch[i];
                    float y = x + crunch * (shape(x) * crunchNorm - x);
                    float o = y - dcX[c] + R * dcY[c];
                    dcX[c] = y; dcY[c] = o;
                    ch[i] = o;
                }
            }
        }

        if (compOn) {
            double inSq = 0.0;
            for (int i = 0; i < n; i++) inSq += (double)sl[i] * sl[i] + (double)sr[i] * sr[i];
            comp.processReplacing(in, out, n);
            makeupTrack(sl, sr, n, inSq);
            for (int i = 0; i < n; i++) { sl[i] *= makeup; sr[i] *= makeup; }
        }

        if (outGain != 1.0f) {
            for (int i = 0; i < n; i++) { sl[i] *= outGain; sr[i] *= outGain; }
        }

        for (int i = 0; i < n; i++) { io[2 * i] = sl[i]; io[2 * i + 1] = sr[i]; }
    }
};

}  // namespace drumbus
