/* render.cpp — push a WAV through OUR module and write the result.
 *
 * Deliberately drives the real audio_fx_api_v2 surface in 128-frame blocks,
 * exactly as the chain host does, so a fit can never be an artefact of a
 * test-only code path.
 *
 * ⚠ The host contract is int16 in/out while Live renders float. That step is
 * REAL — it is what the Move will do — so it is not bypassed here. But it means
 * our render carries a quantisation floor Live's does not, and the analysis has
 * to attribute that to the contract rather than to a modelling error.
 *
 * Usage: render <in.wav> <out.wav> [key=value ...]
 */
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <vector>
#include <string>

#include "../shared/audio_fx_api_v2.h"
extern "C" audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host);

struct Wav { int rate = 0, ch = 0, bits = 0; bool isFloat = false;
             std::vector<float> l, r; };

static uint32_t rd32(const unsigned char *p) {
    return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t rd16(const unsigned char *p) { return p[0] | (p[1] << 8); }

static bool read_wav(const char *path, Wav &w) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return false; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    std::vector<unsigned char> b(sz);
    if (fread(b.data(), 1, sz, f) != (size_t)sz) { fclose(f); return false; }
    fclose(f);
    if (memcmp(b.data(), "RIFF", 4) || memcmp(b.data() + 8, "WAVE", 4)) return false;

    long pos = 12; long dataOff = -1; uint32_t dataLen = 0;
    while (pos + 8 <= sz) {
        const unsigned char *c = b.data() + pos;
        uint32_t len = rd32(c + 4);
        if (!memcmp(c, "fmt ", 4)) {
            uint16_t fmt = rd16(c + 8);
            w.ch   = rd16(c + 10);
            w.rate = rd32(c + 12);
            w.bits = rd16(c + 22);
            w.isFloat = (fmt == 3);
        } else if (!memcmp(c, "data", 4)) { dataOff = pos + 8; dataLen = len; }
        pos += 8 + len + (len & 1);
    }
    if (dataOff < 0 || w.ch < 1) return false;

    const int bytes = w.bits / 8;
    const size_t frames = dataLen / (bytes * w.ch);
    w.l.resize(frames); w.r.resize(frames);
    const unsigned char *d = b.data() + dataOff;
    for (size_t i = 0; i < frames; i++) {
        for (int c = 0; c < w.ch; c++) {
            const unsigned char *s = d + (i * w.ch + c) * bytes;
            float v = 0.0f;
            if (w.isFloat && w.bits == 32) { uint32_t u = rd32(s); memcpy(&v, &u, 4); }
            else if (w.bits == 16) { v = (int16_t)rd16(s) / 32768.0f; }
            else if (w.bits == 24) {
                int32_t u = (s[0] << 8) | (s[1] << 16) | ((int32_t)s[2] << 24);
                v = (u >> 8) / 8388608.0f;
            } else if (w.bits == 32) { v = (int32_t)rd32(s) / 2147483648.0f; }
            if (c == 0) w.l[i] = v;
            if (c == 1 || w.ch == 1) w.r[i] = v;
        }
    }
    return true;
}

static void put32(FILE *f, uint32_t v) { fputc(v & 255, f); fputc((v >> 8) & 255, f);
                                          fputc((v >> 16) & 255, f); fputc((v >> 24) & 255, f); }
static void put16(FILE *f, uint16_t v) { fputc(v & 255, f); fputc((v >> 8) & 255, f); }

static bool write_wav_f32(const char *path, const std::vector<float> &l,
                          const std::vector<float> &r, int rate) {
    FILE *f = fopen(path, "wb");
    if (!f) return false;
    uint32_t dataLen = (uint32_t)(l.size() * 2 * 4);
    fwrite("RIFF", 1, 4, f); put32(f, 36 + dataLen); fwrite("WAVE", 1, 4, f);
    fwrite("fmt ", 1, 4, f); put32(f, 16); put16(f, 3); put16(f, 2);
    put32(f, rate); put32(f, rate * 8); put16(f, 8); put16(f, 32);
    fwrite("data", 1, 4, f); put32(f, dataLen);
    for (size_t i = 0; i < l.size(); i++) { fwrite(&l[i], 4, 1, f); fwrite(&r[i], 4, 1, f); }
    fclose(f);
    return true;
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: render <in.wav> <out.wav> [key=value ...]\n"); return 2; }

    Wav in;
    if (!read_wav(argv[1], in)) { fprintf(stderr, "bad wav: %s\n", argv[1]); return 1; }
    if (in.rate != 44100)
        fprintf(stderr, "WARNING: input is %d Hz, the Move runs 44100 — every "
                        "time constant and filter corner will be off by %.1f%%\n",
                in.rate, 100.0 * (44100.0 / in.rate - 1.0));

    audio_fx_api_v2_t *api = move_audio_fx_init_v2(nullptr);
    void *inst = api->create_instance(".", nullptr);
    if (!inst) { fprintf(stderr, "create_instance failed\n"); return 1; }

    for (int i = 3; i < argc; i++) {
        std::string kv(argv[i]);
        size_t eq = kv.find('=');
        if (eq == std::string::npos) { fprintf(stderr, "bad param: %s\n", argv[i]); return 2; }
        std::string k = kv.substr(0, eq), v = kv.substr(eq + 1);
        api->set_param(inst, k.c_str(), v.c_str());
        char back[128];
        int n = api->get_param(inst, k.c_str(), back, sizeof back);
        /* A key the module does not know is silently ignored by set_param, which
         * would render an unmodified signal that looks like a real measurement. */
        if (n <= 0) { fprintf(stderr, "ERROR: '%s' has no readback — unknown key?\n", k.c_str()); return 1; }
        fprintf(stderr, "  %-12s -> %s\n", k.c_str(), std::string(back, n).c_str());
    }

    const size_t frames = in.l.size();
    std::vector<int16_t> buf(frames * 2);
    for (size_t i = 0; i < frames; i++) {
        float l = in.l[i] < -1.0f ? -1.0f : (in.l[i] > 1.0f ? 1.0f : in.l[i]);
        float r = in.r[i] < -1.0f ? -1.0f : (in.r[i] > 1.0f ? 1.0f : in.r[i]);
        buf[2 * i]     = (int16_t)lrintf(l * 32767.0f);
        buf[2 * i + 1] = (int16_t)lrintf(r * 32767.0f);
    }
    for (size_t off = 0; off < frames; off += 128) {
        int n = (int)((frames - off > 128) ? 128 : (frames - off));
        api->process_block(inst, buf.data() + off * 2, n);
    }
    std::vector<float> ol(frames), orr(frames);
    for (size_t i = 0; i < frames; i++) {
        ol[i]  = buf[2 * i]     / 32768.0f;
        orr[i] = buf[2 * i + 1] / 32768.0f;
    }
    api->destroy_instance(inst);

    if (!write_wav_f32(argv[2], ol, orr, in.rate)) { fprintf(stderr, "write failed\n"); return 1; }
    fprintf(stderr, "wrote %s  (%zu frames @ %d Hz)\n", argv[2], frames, in.rate);
    return 0;
}
