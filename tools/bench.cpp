/* bench.cpp — CPU cost on the device, as a percentage of one core.
 *
 * Run ON THE MOVE, not on the Mac: the CM4's Cortex-A72 has very different
 * transcendental costs from Apple Silicon, and this module leans on log10, pow,
 * sin, exp2 and tanh. A Mac measurement would be reassuring and wrong.
 *
 * Usage: bench [seconds]
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <ctime>
#include <vector>
#include "../shared/audio_fx_api_v2.h"
extern "C" audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host);

static double now() {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static void run_case(audio_fx_api_v2_t *api, const char *label,
                     const char **kv, int nkv, double seconds) {
    void *inst = api->create_instance(".", nullptr);
    for (int i = 0; i < nkv; i += 2) api->set_param(inst, kv[i], kv[i+1]);
    const int N = 128;
    std::vector<int16_t> buf(N * 2);
    for (int i = 0; i < N; i++) {
        float v = 0.3f * sinf(2.f * 3.14159265f * 90.f * i / 44100.f);
        buf[2*i] = buf[2*i+1] = (int16_t)lrintf(v * 32767.f);
    }
    const long blocks = (long)(seconds * 44100.0 / N);
    double t0 = now();
    for (long b = 0; b < blocks; b++) api->process_block(inst, buf.data(), N);
    double el = now() - t0;
    api->destroy_instance(inst);
    printf("  %-28s %7.3f%% of one core   (%.1f s audio in %.3f s)\n",
           label, 100.0 * el / seconds, seconds, el);
}

int main(int argc, char **argv) {
    double secs = argc > 1 ? atof(argv[1]) : 10.0;
    audio_fx_api_v2_t *api = move_audio_fx_init_v2(nullptr);
    printf("Bus Driver CPU, %.0f s of audio per case, 128-frame blocks @ 44100\n\n", secs);
    const char *bypass[] = {"drywet","0"};
    const char *neutral[] = {};
    const char *soft[]  = {"drive","1.0","drive_type","0"};
    const char *med[]   = {"drive","1.0","drive_type","1"};
    const char *hard[]  = {"drive","1.0","drive_type","2"};
    const char *comp[]  = {"comp","1"};
    const char *tr[]    = {"transients","1.0"};
    const char *boom[]  = {"boom","1.0"};
    const char *damp[]  = {"damp","2000"};
    const char *all[]   = {"drive","1.0","drive_type","0","crunch","1.0","comp","1",
                           "transients","1.0","boom","1.0","damp","2000"};
    run_case(api, "bypass (drywet 0)",   bypass, 2, secs);
    run_case(api, "defaults",            neutral, 0, secs);
    run_case(api, "+ drive soft 1.0",    soft, 4, secs);
    run_case(api, "+ drive med 1.0",     med, 4, secs);
    run_case(api, "+ drive hard 1.0",    hard, 4, secs);
    run_case(api, "+ compress",          comp, 2, secs);
    run_case(api, "+ transients 1.0",    tr, 2, secs);
    run_case(api, "+ boom 1.0",          boom, 2, secs);
    run_case(api, "+ damp 2 kHz",        damp, 2, secs);
    run_case(api, "EVERYTHING ON",       all, 14, secs);
    return 0;
}
