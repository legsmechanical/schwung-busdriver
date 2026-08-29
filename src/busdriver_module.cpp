/* busdriver_module.cpp — Bus Driver, a Schwung audio_fx module.
 *
 * A model of Ableton Live 12's Drum Buss, built from measurement rather than
 * from its documentation. Every law is cited to a section of
 * docs/reference/measurements.md at the point of use in dsp/drumbuss.h.
 *
 * This file is only the host contract: audio_fx v2, stereo interleaved int16
 * in-place at 44100 Hz, stringly set_param/get_param, and a state blob.
 *
 * MIT licensed (see LICENSE).
 */
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <new>

#include "../shared/audio_fx_api_v2.h"
#include "../dsp/drumbuss.h"

#define BD_SAMPLE_RATE 44100.0f
#define BD_MAX_BLOCK   512

static const host_api_v1_t *g_host = nullptr;
static void bd_log(const char *m) { if (g_host && g_host->log) g_host->log(m); }

struct bd_t {
    drumbuss::DrumBuss d;
    float buf[BD_MAX_BLOCK * 2];
};

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

/* Ranges are Live's own, read out of its stock .adv presets (measurements §1).
 * Trim and Output are LINEAR gains there, not dB, so they are exposed here in
 * dB for a usable control and converted on the way in. */
struct field_t { const char *key; float lo, hi; };
static const field_t kFields[] = {
    { "comp",       0.0f,     1.0f },      /* a TOGGLE — Live's is a bool */
    { "drive",      0.0f,     1.0f },
    { "drive_type", 0.0f,     2.0f },      /* 0 soft (a folder), 1 med, 2 hard */
    { "crunch",     0.0f,     1.0f },
    { "damp",     500.0f, 20000.0f },      /* Hz, and it IS the -3 dB corner */
    { "transients",-1.0f,     1.0f },
    { "boom",       0.0f,     1.0f },
    { "boom_freq", 30.0f,    90.0f },      /* Hz */
    { "boom_decay", 0.0f,     1.0f },
    { "trim",     -70.0f,     0.0f },      /* dB */
    { "output",   -40.0f,     3.0f },      /* dB */
    { "drywet",     0.0f,     1.0f },
    { nullptr, 0.0f, 0.0f }
};

static float *slot(bd_t *I, const char *key) {
    drumbuss::Params &p = I->d.p;
    static float scratch;
    if (!strcmp(key, "comp"))       { scratch = p.comp ? 1.0f : 0.0f; return &scratch; }
    if (!strcmp(key, "drive"))       return &p.drive;
    if (!strcmp(key, "crunch"))      return &p.crunch;
    if (!strcmp(key, "damp"))        return &p.dampHz;
    if (!strcmp(key, "transients"))  return &p.trans;
    if (!strcmp(key, "boom"))        return &p.boom;
    if (!strcmp(key, "boom_freq"))   return &p.boomHz;
    if (!strcmp(key, "boom_decay"))  return &p.boomDecay;
    if (!strcmp(key, "drywet"))      return &p.dryWet;
    return nullptr;
}

static void bd_set(bd_t *I, const char *key, float v) {
    drumbuss::Params &p = I->d.p;
    if (!strcmp(key, "comp"))            p.comp = v >= 0.5f;
    else if (!strcmp(key, "drive_type")) p.driveType = (int)lrintf(clampf(v, 0, 2));
    else if (!strcmp(key, "trim"))       p.trim    = powf(10.0f, clampf(v, -70, 0) / 20.0f);
    else if (!strcmp(key, "output"))     p.outGain = powf(10.0f, clampf(v, -40, 3) / 20.0f);
    /* Hidden fitting handles (leading underscore, not in chain_params): these
     * let tools/fit_transients.py drive the law end to end. Baked values live in
     * dsp/drumbuss.h; these exist so a fit does not need a recompile per trial. */
    else if (!strcmp(key, "_tr_up"))    { I->d.trans.upScale = v; }
    else if (!strcmp(key, "_tr_upexp")) { I->d.trans.upExp   = v; }
    else if (!strcmp(key, "_tr_dn"))    { I->d.trans.dnScale = v; }
    else if (!strcmp(key, "_tr_us"))    { I->d.trans.upSus   = v; }
    else if (!strcmp(key, "_tr_dnexp")) { I->d.trans.dnExp   = v; }
    else if (!strcmp(key, "_tr_fast"))  { I->d.trans.msFast  = v; I->d.trans.setSampleRate(I->d.sr); }
    else if (!strcmp(key, "_tr_rel"))   { I->d.trans.msRel   = v; I->d.trans.setSampleRate(I->d.sr); }
    else if (!strcmp(key, "_tr_slow"))  { I->d.trans.msSlow  = v; I->d.trans.setSampleRate(I->d.sr); }
    else {
        float *s = slot(I, key);
        if (!s) return;
        for (const field_t *f = kFields; f->key; f++)
            if (!strcmp(f->key, key)) { *s = clampf(v, f->lo, f->hi); break; }
    }
    I->d.applyAll();
}

static float bd_get(bd_t *I, const char *key, bool *ok) {
    drumbuss::Params &p = I->d.p;
    *ok = true;
    if (!strcmp(key, "comp"))       return p.comp ? 1.0f : 0.0f;
    if (!strcmp(key, "drive_type")) return (float)p.driveType;
    if (!strcmp(key, "trim"))       return 20.0f * log10f(p.trim   > 1e-6f ? p.trim   : 1e-6f);
    if (!strcmp(key, "output"))     return 20.0f * log10f(p.outGain> 1e-6f ? p.outGain: 1e-6f);
    float *s = slot(I, key);
    if (s) return *s;
    *ok = false;
    return 0.0f;
}

static void *bd_create(const char *dir, const char *cfg) {
    (void)dir; (void)cfg;
    bd_t *I = new (std::nothrow) bd_t();
    if (!I) return nullptr;
    I->d.setSampleRate(BD_SAMPLE_RATE);
    I->d.reset();
    bd_log("Bus Driver: instance created");
    return I;
}
static void bd_destroy(void *inst) { delete (bd_t *)inst; }

static void bd_process(void *inst, int16_t *audio, int frames) {
    bd_t *I = (bd_t *)inst;
    if (!I || frames <= 0) return;
    /* Bypass BEFORE the int16 round trip. The DSP's own neutral() check happens
     * after conversion, and float->int16 is not the identity, so a neutral
     * device would otherwise not be bit-transparent. */
    if (I->d.neutral() && I->d.p.outGain == 1.0f) return;
    for (int off = 0; off < frames; off += BD_MAX_BLOCK) {
        const int n = (frames - off > BD_MAX_BLOCK) ? BD_MAX_BLOCK : (frames - off);
        int16_t *blk = audio + off * 2;
        for (int i = 0; i < n * 2; i++) I->buf[i] = blk[i] / 32768.0f;
        I->d.process(I->buf, n);
        for (int i = 0; i < n * 2; i++) {
            float v = clampf(I->buf[i], -1.0f, 1.0f);
            blk[i] = (int16_t)lrintf(v * 32767.0f);
        }
    }
}

static int bd_write_state(bd_t *I, char *buf, int n) {
    int off = 0;
    for (const field_t *f = kFields; f->key; f++) {
        bool ok; float v = bd_get(I, f->key, &ok);
        int w = snprintf(buf + off, (size_t)(n - off), "%s%s=%.6f",
                         off ? ";" : "", f->key, (double)v);
        if (w < 0 || w >= n - off) return -1;
        off += w;
    }
    return off;
}

static void bd_read_state(bd_t *I, const char *val) {
    const char *s = val;
    while (s && *s) {
        const char *eq = strchr(s, '='), *semi = strchr(s, ';');
        if (!eq || (semi && eq > semi)) { if (!semi) break; s = semi + 1; continue; }
        char key[32];
        size_t klen = (size_t)(eq - s);
        if (klen < sizeof key) {
            memcpy(key, s, klen); key[klen] = 0;
            bd_set(I, key, (float)atof(eq + 1));
        }
        if (!semi) break;
        s = semi + 1;
    }
}

static void bd_set_param(void *inst, const char *key, const char *val) {
    bd_t *I = (bd_t *)inst;
    if (!I || !key || !val) return;
    if (!strcmp(key, "state")) { bd_read_state(I, val); return; }
    bd_set(I, key, (float)atof(val));
}

static int bd_get_param(void *inst, const char *key, char *buf, int n) {
    bd_t *I = (bd_t *)inst;
    if (!I || !key || !buf || n <= 0) return -1;
    if (!strcmp(key, "state")) return bd_write_state(I, buf, n);
    if (key[0] == '_') {          /* fitting handles read back so a typo is loud */
        float v = 0.0f;
        if (!strcmp(key,"_tr_up")) v = I->d.trans.upScale;
        else if (!strcmp(key,"_tr_upexp")) v = I->d.trans.upExp;
        else if (!strcmp(key,"_tr_dn")) v = I->d.trans.dnScale;
        else if (!strcmp(key,"_tr_us")) v = I->d.trans.upSus;
        else if (!strcmp(key,"_tr_dnexp")) v = I->d.trans.dnExp;
        else if (!strcmp(key,"_tr_fast")) v = I->d.trans.msFast;
        else if (!strcmp(key,"_tr_rel")) v = I->d.trans.msRel;
        else if (!strcmp(key,"_tr_slow")) v = I->d.trans.msSlow;
        else return -1;
        int w = snprintf(buf, (size_t)n, "%.6f", (double)v);
        return (w > 0 && w < n) ? w : -1;
    }
    bool ok; float v = bd_get(I, key, &ok);
    if (!ok) return -1;
    int w = snprintf(buf, (size_t)n, "%.6f", (double)v);
    return (w > 0 && w < n) ? w : -1;
}

static audio_fx_api_v2_t g_api;
extern "C" {
audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host) {
    g_host = host;
    memset(&g_api, 0, sizeof g_api);
    g_api.api_version      = AUDIO_FX_API_VERSION_2;
    g_api.create_instance  = bd_create;
    g_api.destroy_instance = bd_destroy;
    g_api.process_block    = bd_process;
    g_api.set_param        = bd_set_param;
    g_api.get_param        = bd_get_param;
    g_api.on_midi          = nullptr;
    bd_log("Bus Driver initialized");
    return &g_api;
}
}
