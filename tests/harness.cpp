/* harness.cpp — offline checks for the Bus Driver, driven through the real
 * audio_fx_api_v2 surface (not the DSP struct directly), so the host contract
 * is exercised too.
 *
 * These assert PROPERTIES, not proxies. That distinction is the whole point:
 * DR32's original bus stage passed a green suite while its compressor lifted a
 * -48 dBFS signal by +17.7 dB, its "transients" control moved the attack and
 * the tail together, and half its knob was dead. Every check below is aimed at
 * one of those specific failure shapes.
 */
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <vector>
#include <string>

#include "../shared/audio_fx_api_v2.h"
extern "C" audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host);

static int g_fail = 0, g_pass = 0;

static void ok(bool cond, const char *fmt, ...) {
    char msg[512];
    va_list ap; va_start(ap, fmt); vsnprintf(msg, sizeof msg, fmt, ap); va_end(ap);
    if (cond) { g_pass++; printf("ok:   %s\n", msg); }
    else      { g_fail++; printf("FAIL: %s\n", msg); }
}

static const int SR = 44100;

/* ---- signal helpers ---- */
static std::vector<int16_t> sine(float amp, float hz, int n) {
    std::vector<int16_t> v(n * 2);
    for (int i = 0; i < n; i++) {
        float s = amp * sinf(2.0f * (float)M_PI * hz * (float)i / SR);
        int16_t q = (int16_t)lrintf(s * 32767.0f);
        v[2*i] = q; v[2*i+1] = q;
    }
    return v;
}

/* One drum-ish hit: fast attack, exponential decay, with a click on top. */
static std::vector<int16_t> hit(float amp, float decayS, int n, int startFrame = 0) {
    std::vector<int16_t> v(n * 2, 0);
    for (int i = startFrame; i < n; i++) {
        float t = (float)(i - startFrame) / SR;
        float env = expf(-t / decayS);
        float body = sinf(2.0f * (float)M_PI * 90.0f * t);
        float click = expf(-t / 0.002f) * sinf(2.0f * (float)M_PI * 3000.0f * t);
        float s = amp * env * (0.8f * body + 0.5f * click);
        if (s >  1.0f) s =  1.0f;
        if (s < -1.0f) s = -1.0f;
        int16_t q = (int16_t)lrintf(s * 32767.0f);
        v[2*i] = q; v[2*i+1] = q;
    }
    return v;
}

static double rms(const std::vector<int16_t> &v, int from, int to) {
    double s = 0.0; int n = 0;
    for (int i = from; i < to; i++) {
        double l = v[2*i] / 32768.0, r = v[2*i+1] / 32768.0;
        s += l*l + r*r; n += 2;
    }
    return n ? sqrt(s / n) : 0.0;
}
static double peak(const std::vector<int16_t> &v, int from, int to) {
    double m = 0.0;
    for (int i = from; i < to; i++) {
        double l = fabs(v[2*i] / 32768.0), r = fabs(v[2*i+1] / 32768.0);
        if (l > m) m = l; if (r > m) m = r;
    }
    return m;
}
static double db(double x) { return 20.0 * log10(x > 1e-12 ? x : 1e-12); }

/* Goertzel magnitude at one bin — for the spectrum-neutrality check. */
static double toneMag(const std::vector<int16_t> &v, int from, int to, double hz) {
    const int N = to - from;
    const double w = 2.0 * M_PI * hz / SR;
    double cw = cos(w), sw = sin(w), c = 2.0 * cw;
    double s0 = 0, s1 = 0, s2 = 0;
    for (int i = 0; i < N; i++) {
        double x = v[2*(from+i)] / 32768.0;
        s0 = x + c * s1 - s2; s2 = s1; s1 = s0;
    }
    double re = s1 - s2 * cw, im = s2 * sw;
    return 2.0 * sqrt(re*re + im*im) / N;
}

/* ---- driving ---- */
struct Fx {
    audio_fx_api_v2_t *api;
    void *inst;
    Fx(audio_fx_api_v2_t *a) : api(a) { inst = a->create_instance(".", nullptr); }
    ~Fx() { if (inst) api->destroy_instance(inst); }
    void set(const char *k, double v) {
        char b[64]; snprintf(b, sizeof b, "%.6f", v);
        api->set_param(inst, k, b);
    }
    std::string get(const char *k) {
        char b[1024]; int n = api->get_param(inst, k, b, sizeof b);
        return n > 0 ? std::string(b, n) : std::string();
    }
    /* Process in 128-frame blocks, exactly as the host does. */
    void run(std::vector<int16_t> &v) {
        int frames = (int)v.size() / 2;
        for (int off = 0; off < frames; off += 128) {
            int n = frames - off > 128 ? 128 : frames - off;
            api->process_block(inst, v.data() + off * 2, n);
        }
    }
};

int main() {
    audio_fx_api_v2_t *api = move_audio_fx_init_v2(nullptr);
    ok(api != nullptr, "init returns an api");
    ok(api->api_version == AUDIO_FX_API_VERSION_2, "api_version is 2");
    ok(api->create_instance && api->process_block && api->set_param && api->get_param,
       "required entry points are non-null");

    /* --- 1. transparent while neutral -------------------------------------
     * Not "close to dry" — BIT-IDENTICAL. A stage that is off must not even
     * pay an int16 round-trip. */
    {
        Fx f(api);
        auto dry = hit(0.7f, 0.25f, SR / 2);
        auto wet = dry;
        f.run(wet);
        ok(memcmp(dry.data(), wet.data(), dry.size() * sizeof(int16_t)) == 0,
           "neutral is bit-identical to dry");
    }

    /* --- 2. the compressor can only ATTENUATE ------------------------------
     * The structural property Pop3 was chosen for, and the exact bug that got
     * Pressure4 removed (+17.7 dB of lift on a -48 dBFS sine). Checked at
     * every knob position, not just the top. */
    {
        auto in = sine(0.004f, 220.0f, SR);           /* about -48 dBFS */
        double inDb = db(rms(in, SR/2, SR));
        double worst = -99.0;
        for (int k = 0; k <= 10; k++) {
            Fx f(api);
            f.set("compress", k / 10.0);
            auto v = in; f.run(v);
            double lift = db(rms(v, SR/2, SR)) - inDb;
            if (lift > worst) worst = lift;
        }
        ok(worst < 1.0, "no low-level lift at any compress setting (worst %+.2f dB)", worst);
    }

    /* --- 3. the duck curve is monotonic and spread across the knob ---------
     * The 1.6 power law exists so the bottom stays subtle and the top gets
     * violent. A linear law measured -1.2 dB at knob 0.25 (already audible)
     * and ran out of range; a square law left the bottom half inert. */
    {
        double gr[5]; const double knob[5] = { 0.3, 0.5, 0.7, 0.9, 1.0 };
        auto in = hit(0.9f, 0.30f, SR / 2);
        double inRms = rms(in, 0, SR / 2);
        for (int i = 0; i < 5; i++) {
            Fx f(api);
            f.set("compress", knob[i]);
            auto v = in; f.run(v);
            gr[i] = db(rms(v, 0, SR / 2)) - db(inRms);
        }
        bool mono = true;
        for (int i = 1; i < 5; i++) if (gr[i] > gr[i-1] + 0.01) mono = false;
        ok(mono, "duck deepens monotonically across the knob (%.1f/%.1f/%.1f/%.1f/%.1f dB)",
           gr[0], gr[1], gr[2], gr[3], gr[4]);
        ok(gr[0] > -2.5, "bottom of the knob stays subtle (%.2f dB at 0.30)", gr[0]);
        ok(gr[4] < gr[0] - 4.0, "top of the knob has real range (%.1f dB at 1.00)", gr[4]);
    }

    /* --- 4. Attack shapes the ONSET and leaves the tail alone --------------
     * The stage this replaced applied a broadband gain: it moved the attack
     * 18.1 dB and the tail 3.0 dB in the SAME direction. Here the tail must
     * barely move while the onset moves a lot, in BOTH directions.
     *
     * ⚠ The hit is deliberately QUIET (-26 dBFS). The gain law is
     * exp2f(depth*t) with depth = +-2.6, i.e. +-15.6 dB and reciprocal by
     * construction — but measured on a 0.5-amplitude hit the boost side clips
     * against full scale and reads +6.7 / -13.7, which looks like a broken
     * asymmetric control and is really just the test hitting the rails. Headroom
     * is part of the measurement, not an incidental choice. */
    {
        auto in = hit(0.05f, 0.35f, SR);
        const int onsetTo = SR / 100;              /* first 10 ms */
        const int tailFrom = SR / 2, tailTo = 3 * SR / 4;
        double onset0 = db(peak(in, 0, onsetTo)), tail0 = db(rms(in, tailFrom, tailTo));
        double dOnUp, dTlUp, dOnDn, dTlDn;
        { Fx f(api); f.set("attack",  1.0); auto v = in; f.run(v);
          dOnUp = db(peak(v, 0, onsetTo)) - onset0; dTlUp = db(rms(v, tailFrom, tailTo)) - tail0; }
        { Fx f(api); f.set("attack", -1.0); auto v = in; f.run(v);
          dOnDn = db(peak(v, 0, onsetTo)) - onset0; dTlDn = db(rms(v, tailFrom, tailTo)) - tail0; }
        ok(dOnUp > 3.0,  "attack up sharpens the onset (%+.1f dB)", dOnUp);
        ok(dOnDn < -3.0, "attack down softens the onset (%+.1f dB)", dOnDn);
        ok(fabs(dTlUp) < 1.0 && fabs(dTlDn) < 1.0,
           "attack leaves the tail alone (%+.2f / %+.2f dB)", dTlUp, dTlDn);
        ok(fabs(dOnUp + dOnDn) < 2.0,
           "attack is symmetric within 2 dB (%+.1f up / %+.1f down)", dOnUp, dOnDn);
    }

    /* --- 5. Sustain shapes the TAIL and leaves the onset alone -------------
     * Quiet for the same headroom reason as the attack check above. */
    {
        auto in = hit(0.05f, 0.35f, SR);
        const int onsetTo = SR / 100;
        const int tailFrom = SR / 2, tailTo = 3 * SR / 4;
        double onset0 = db(peak(in, 0, onsetTo)), tail0 = db(rms(in, tailFrom, tailTo));
        double dOnUp, dTlUp, dOnDn, dTlDn;
        { Fx f(api); f.set("sustain",  1.0); auto v = in; f.run(v);
          dOnUp = db(peak(v, 0, onsetTo)) - onset0; dTlUp = db(rms(v, tailFrom, tailTo)) - tail0; }
        { Fx f(api); f.set("sustain", -1.0); auto v = in; f.run(v);
          dOnDn = db(peak(v, 0, onsetTo)) - onset0; dTlDn = db(rms(v, tailFrom, tailTo)) - tail0; }
        ok(dTlUp > 3.0,  "sustain up lengthens the tail (%+.1f dB)", dTlUp);
        ok(dTlDn < -3.0, "sustain down shortens the tail (%+.1f dB)", dTlDn);
        ok(fabs(dOnUp) < 1.0 && fabs(dOnDn) < 1.0,
           "sustain leaves the onset alone (%+.2f / %+.2f dB)", dOnUp, dOnDn);
    }

    /* --- 6. Crunch is spectrum-neutral -------------------------------------
     * An earlier version split at ~1.2 kHz and folded only the top, which is
     * EQ, not saturation, and audibly thinned the kick. A 60 Hz and a 6 kHz
     * tone must come out with the balance they went in with. */
    {
        std::vector<int16_t> in(SR * 2);
        for (int i = 0; i < SR; i++) {
            float s = 0.3f * sinf(2.0f*(float)M_PI*60.0f*i/SR)
                    + 0.3f * sinf(2.0f*(float)M_PI*6000.0f*i/SR);
            int16_t q = (int16_t)lrintf(s * 32767.0f);
            in[2*i] = q; in[2*i+1] = q;
        }
        double lo0 = db(toneMag(in, SR/4, SR, 60.0)), hi0 = db(toneMag(in, SR/4, SR, 6000.0));
        Fx f(api); f.set("crunch", 1.0);
        auto v = in; f.run(v);
        double lo1 = db(toneMag(v, SR/4, SR, 60.0)), hi1 = db(toneMag(v, SR/4, SR, 6000.0));
        double tilt = (hi1 - lo1) - (hi0 - lo0);
        ok(fabs(tilt) < 1.5, "crunch is spectrum-neutral (tilt %+.2f dB at full)", tilt);
    }

    /* --- 7. Mix is a real dry/wet ------------------------------------------
     * Mix 0 must be the dry signal, not "mostly dry". */
    {
        auto in = hit(0.6f, 0.25f, SR / 2);
        Fx f(api);
        f.set("compress", 1.0); f.set("crunch", 1.0); f.set("mix", 0.0);
        auto v = in; f.run(v);
        double err = db(rms(v, 0, SR/2)) - db(rms(in, 0, SR/2));
        ok(fabs(err) < 0.1, "mix=0 returns the dry signal (%+.3f dB)", err);

        Fx g(api);
        g.set("compress", 1.0); g.set("mix", 1.0);
        auto w = in; g.run(w);
        Fx h(api);
        h.set("compress", 1.0); h.set("mix", 0.5);
        auto x = in; h.run(x);
        double full = db(rms(w, 0, SR/2)), half = db(rms(x, 0, SR/2)), dry = db(rms(in, 0, SR/2));
        ok((half < dry + 0.05 && half > full - 0.05) || (half > dry - 0.05 && half < full + 0.05),
           "mix=0.5 lands between dry and fully wet (dry %.1f / half %.1f / wet %.1f dB)",
           dry, half, full);
    }

    /* --- 8. Output trim is exact -------------------------------------------
     * It is a level control, so it must be the level it claims, and it must
     * work with the rest of the stage neutral. */
    {
        auto in = sine(0.1f, 440.0f, SR / 2);
        double in0 = db(rms(in, 0, SR/2));
        { Fx f(api); f.set("output", 6.0);  auto v = in; f.run(v);
          ok(fabs(db(rms(v,0,SR/2)) - in0 - 6.0) < 0.1, "output +6 dB is +6 dB"); }
        { Fx f(api); f.set("output", -12.0); auto v = in; f.run(v);
          ok(fabs(db(rms(v,0,SR/2)) - in0 + 12.0) < 0.1, "output -12 dB is -12 dB"); }
    }

    /* --- 9. state round-trips ---------------------------------------------- */
    {
        Fx f(api);
        f.set("compress", 0.62); f.set("crunch", 0.31); f.set("attack", -0.4);
        f.set("sustain", 0.75);  f.set("mix", 0.8);     f.set("output", -3.5);
        std::string blob = f.get("state");
        ok(blob.size() > 10, "state serializes (%zu bytes)", blob.size());

        Fx g(api);
        g.api->set_param(g.inst, "state", blob.c_str());
        ok(fabs(atof(g.get("compress").c_str()) - 0.62) < 1e-4, "state restores compress");
        ok(fabs(atof(g.get("attack").c_str())   + 0.40) < 1e-4, "state restores bipolar attack");
        ok(fabs(atof(g.get("output").c_str())   + 3.50) < 1e-4, "state restores output dB");
        ok(g.get("state") == blob, "state round-trips byte-for-byte");
    }

    /* --- 10. every declared chain_param reads back -------------------------
     * A key the UI shows but the DSP cannot read is the classic silent break:
     * the knob reads zero and edits appear to do nothing. */
    {
        Fx f(api);
        const char *keys[] = { "compress","crunch","attack","sustain","mix","output" };
        bool all = true;
        for (const char *k : keys) if (f.get(k).empty()) { all = false; printf("      no readback: %s\n", k); }
        ok(all, "every declared param has get_param readback");
        char b[8];
        ok(f.api->get_param(f.inst, "nonexistent", b, sizeof b) == -1, "unknown key returns -1");
    }

    /* --- 11. out-of-range values are clamped, not propagated ---------------- */
    {
        Fx f(api);
        f.set("compress", 9.0); f.set("attack", -9.0); f.set("output", 99.0);
        ok(fabs(atof(f.get("compress").c_str()) - 1.0) < 1e-6, "compress clamps to 1");
        ok(fabs(atof(f.get("attack").c_str())   + 1.0) < 1e-6, "attack clamps to -1");
        ok(fabs(atof(f.get("output").c_str())  - 12.0) < 1e-6, "output clamps to +12 dB");
    }

    /* --- 12. nothing blows up ---------------------------------------------
     * Full everything, into silence, then a full-scale hit: no NaN, no
     * runaway makeup, no denormal stall. */
    {
        Fx f(api);
        f.set("compress", 1.0); f.set("crunch", 1.0);
        f.set("attack", 1.0);   f.set("sustain", 1.0); f.set("output", 12.0);
        std::vector<int16_t> quiet(SR * 2, 0);
        f.run(quiet);
        bool clean = true;
        for (size_t i = 0; i < quiet.size(); i++) if (quiet[i] != 0) clean = false;
        ok(clean, "silence in, silence out at full tilt");

        auto loud = hit(1.0f, 0.4f, SR);
        auto v = loud; f.run(v);
        bool finite = true;
        for (size_t i = 0; i < v.size(); i++) if (v[i] == -32768) finite = false;
        ok(finite, "full-scale hit at full tilt stays in range");
    }

    printf("\n%s (%d checks, %d failures)\n", g_fail ? "FAILURES" : "ALL PASS", g_pass + g_fail, g_fail);
    return g_fail ? 1 : 0;
}
