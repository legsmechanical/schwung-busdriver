/* drumbus_module.cpp — Drum Bus, a Schwung audio_fx module.
 *
 * The glue stage from schwung-dr32, peeled off so it can sit on any track
 * rather than only over a kit. The DSP is dsp/drumbus.h, lifted whole; this
 * file is only the host contract: audio_fx v2, stereo interleaved int16
 * in-place at 44100 Hz, stringly set_param/get_param, and a state blob so a
 * slot survives a reboot.
 *
 * MIT licensed (see LICENSE).
 */
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <new>

#include "../shared/audio_fx_api_v2.h"
#include "../dsp/drumbus.h"

#define DB_SAMPLE_RATE   44100.0f
/* The host runs 128-frame blocks; the stage is block-based, so anything larger
 * is chunked rather than assumed. */
#define DB_MAX_BLOCK     512

static const host_api_v1_t *g_host = nullptr;

static void db_log(const char *msg) {
    if (g_host && g_host->log) g_host->log(msg);
}

/* ---- parameters -----------------------------------------------------------
 *
 * Compress / Crunch are 0..1. Attack / Sustain are BIPOLAR -1..+1 with 0
 * neutral — the stage itself takes them that way and re-centres internally.
 * Mix is a dry/wet blend over the whole stage (so it is parallel compression,
 * not a bypass fader). Output is a trim in dB, applied last.
 */
struct params_t {
    float compress = 0.0f;
    float crunch   = 0.0f;
    float attack   = 0.0f;   /* -1..+1 */
    float sustain  = 0.0f;   /* -1..+1 */
    float mix      = 1.0f;
    float outputDb = 0.0f;   /* -24..+12 */
};

struct db_t {
    drumbus::DrumBuss bus;
    params_t p;
    bool  neutral = true;    /* every stage control at rest */
    float mix     = 1.0f;
    float scratchL[DB_MAX_BLOCK];
    float scratchR[DB_MAX_BLOCK];
    float wet[DB_MAX_BLOCK * 2];
    float dry[DB_MAX_BLOCK * 2];
};

static float clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

/* Push the param set into the stage and recompute the bypass flag.
 *
 * The tolerances match the stage's own atkOn/susOn gates (+-0.005 about
 * centre); a control inside its own dead zone must also read as neutral here,
 * or the module would run a stage that has been told to do nothing. */
static void db_apply(db_t *I) {
    params_t &p = I->p;
    I->bus.setParams(p.compress, p.crunch,
                     0.5f + 0.5f * p.attack, 0.5f + 0.5f * p.sustain);
    I->bus.outGain = powf(10.0f, p.outputDb / 20.0f);
    I->mix = clampf(p.mix, 0.0f, 1.0f);
    I->neutral = (p.compress <= 0.001f) && (p.crunch <= 0.001f) &&
                 (fabsf(p.attack) <= 0.005f) && (fabsf(p.sustain) <= 0.005f);
}

/* ---- lifecycle ---- */
static void *db_create(const char *module_dir, const char *config_json) {
    (void)module_dir; (void)config_json;
    db_t *I = new (std::nothrow) db_t();
    if (!I) return nullptr;
    I->bus.setSampleRate(DB_SAMPLE_RATE);
    I->bus.reset();
    db_apply(I);
    db_log("Drum Bus: instance created");
    return I;
}

static void db_destroy(void *inst) { delete (db_t *)inst; }

/* ---- audio ----------------------------------------------------------------
 *
 * Bypassed entirely while neutral — actually skipped, not "runs and does
 * nothing" — so an untouched Drum Bus is bit-transparent and costs one bool
 * test per block. That is also why the int16 round-trip below is not taken in
 * the neutral case: converting to float and back is not free of error, and a
 * transparent stage should be transparent to the sample.
 */
static void db_process(void *inst, int16_t *audio, int frames) {
    db_t *I = (db_t *)inst;
    if (!I || frames <= 0) return;

    const float outGain = I->bus.outGain;
    if (I->neutral) {
        /* Output trim still applies: it is a level control, not part of the
         * glue, and someone may want only that. */
        if (outGain == 1.0f) return;
        for (int i = 0; i < frames * 2; i++) {
            float v = (audio[i] / 32768.0f) * outGain;
            v = clampf(v, -1.0f, 1.0f);
            audio[i] = (int16_t)lrintf(v * 32767.0f);
        }
        return;
    }

    for (int off = 0; off < frames; off += DB_MAX_BLOCK) {
        const int n = (frames - off > DB_MAX_BLOCK) ? DB_MAX_BLOCK : (frames - off);
        int16_t *blk = audio + off * 2;

        for (int i = 0; i < n * 2; i++) I->wet[i] = blk[i] / 32768.0f;

        /* Parallel path: only keep the unprocessed copy when it is going to be
         * blended back in. At mix = 1 this is a plain in-place run. */
        const float mix = I->mix;
        if (mix < 0.999f) memcpy(I->dry, I->wet, sizeof(float) * 2 * (size_t)n);

        I->bus.processBlock(I->wet, n, I->scratchL, I->scratchR);

        if (mix < 0.999f) {
            for (int i = 0; i < n * 2; i++)
                I->wet[i] = I->dry[i] + (I->wet[i] - I->dry[i]) * mix;
        }

        for (int i = 0; i < n * 2; i++) {
            float v = clampf(I->wet[i], -1.0f, 1.0f);
            blk[i] = (int16_t)lrintf(v * 32767.0f);
        }
    }
}

/* ---- params ---- */
struct field_t { const char *key; float *slot; float lo, hi; };

static field_t *db_fields(db_t *I, field_t *tbl) {
    params_t &p = I->p;
    tbl[0] = { "compress", &p.compress,  0.0f,  1.0f };
    tbl[1] = { "crunch",   &p.crunch,    0.0f,  1.0f };
    tbl[2] = { "attack",   &p.attack,   -1.0f,  1.0f };
    tbl[3] = { "sustain",  &p.sustain,  -1.0f,  1.0f };
    tbl[4] = { "mix",      &p.mix,       0.0f,  1.0f };
    tbl[5] = { "output",   &p.outputDb, -24.0f, 12.0f };
    tbl[6] = { nullptr,    nullptr,      0.0f,  0.0f };
    return tbl;
}

/* The state blob is the same key=value list the host sets, so a preset written
 * by one build reads on the next even if a param is added: unknown keys are
 * ignored and missing ones keep their default. */
static int db_write_state(db_t *I, char *buf, int n) {
    field_t tbl[8]; db_fields(I, tbl);
    int off = 0;
    for (int i = 0; tbl[i].key; i++) {
        int w = snprintf(buf + off, (size_t)(n - off), "%s%s=%.6f",
                         i ? ";" : "", tbl[i].key, (double)*tbl[i].slot);
        if (w < 0 || w >= n - off) return -1;
        off += w;
    }
    return off;
}

static void db_read_state(db_t *I, const char *val) {
    field_t tbl[8]; db_fields(I, tbl);
    const char *s = val;
    while (s && *s) {
        const char *eq = strchr(s, '=');
        const char *semi = strchr(s, ';');
        if (!eq || (semi && eq > semi)) { if (!semi) break; s = semi + 1; continue; }
        const size_t klen = (size_t)(eq - s);
        for (int i = 0; tbl[i].key; i++) {
            if (strlen(tbl[i].key) == klen && strncmp(s, tbl[i].key, klen) == 0) {
                *tbl[i].slot = clampf((float)atof(eq + 1), tbl[i].lo, tbl[i].hi);
                break;
            }
        }
        if (!semi) break;
        s = semi + 1;
    }
    db_apply(I);
}

static void db_set_param(void *inst, const char *key, const char *val) {
    db_t *I = (db_t *)inst;
    if (!I || !key || !val) return;

    if (strcmp(key, "state") == 0) { db_read_state(I, val); return; }

    field_t tbl[8]; db_fields(I, tbl);
    for (int i = 0; tbl[i].key; i++) {
        if (strcmp(key, tbl[i].key) == 0) {
            *tbl[i].slot = clampf((float)atof(val), tbl[i].lo, tbl[i].hi);
            db_apply(I);
            return;
        }
    }
}

/* Readback for every key the UI displays. Without it every knob reads zero and
 * edits appear to do nothing. */
static int db_get_param(void *inst, const char *key, char *buf, int n) {
    db_t *I = (db_t *)inst;
    if (!I || !key || !buf || n <= 0) return -1;

    if (strcmp(key, "state") == 0) return db_write_state(I, buf, n);

    field_t tbl[8]; db_fields(I, tbl);
    for (int i = 0; tbl[i].key; i++) {
        if (strcmp(key, tbl[i].key) == 0) {
            int w = snprintf(buf, (size_t)n, "%.6f", (double)*tbl[i].slot);
            return (w > 0 && w < n) ? w : -1;
        }
    }
    return -1;
}

/* ---- entry point ---- */
static audio_fx_api_v2_t g_api;
extern "C" {

audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host) {
    g_host = host;
    memset(&g_api, 0, sizeof(g_api));
    g_api.api_version      = AUDIO_FX_API_VERSION_2;
    g_api.create_instance  = db_create;
    g_api.destroy_instance = db_destroy;
    g_api.process_block    = db_process;
    g_api.set_param        = db_set_param;
    g_api.get_param        = db_get_param;
    g_api.on_midi          = nullptr;   /* no MIDI surface */
    db_log("Drum Bus initialized");
    return &g_api;
}

} /* extern "C" */
