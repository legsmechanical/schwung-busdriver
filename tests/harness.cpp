/* harness.cpp — offline checks for Bus Driver, through the real
 * audio_fx_api_v2 surface.
 *
 * These assert against the MEASUREMENTS in docs/reference/measurements.md, not
 * against whatever the code happens to do. Where a section number is cited, the
 * expected value came from Ableton's device, not from this implementation.
 */
#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <cmath>
#include <vector>
#include <string>
#include "../shared/audio_fx_api_v2.h"
extern "C" audio_fx_api_v2_t *move_audio_fx_init_v2(const host_api_v1_t *host);

static int g_fail = 0, g_pass = 0;
static void ok(bool c, const char *fmt, ...) {
    char m[512]; va_list ap; va_start(ap, fmt);
    vsnprintf(m, sizeof m, fmt, ap); va_end(ap);
    if (c) { g_pass++; printf("ok:   %s\n", m); }
    else   { g_fail++; printf("FAIL: %s\n", m); }
}
static const int SR = 44100;

static std::vector<int16_t> sine(float amp, float hz, int n) {
    std::vector<int16_t> v(n * 2);
    for (int i = 0; i < n; i++) {
        int16_t q = (int16_t)lrintf(amp * sinf(2.f*(float)M_PI*hz*i/SR) * 32767.f);
        v[2*i] = q; v[2*i+1] = q;
    }
    return v;
}
static double rms(const std::vector<int16_t> &v) {
    double s = 0; for (size_t i = 0; i < v.size(); i++) { double x = v[i]/32768.0; s += x*x; }
    return sqrt(s / v.size());
}
static double db(double x) { return 20.0 * log10(x > 1e-12 ? x : 1e-12); }

struct Fx {
    audio_fx_api_v2_t *api; void *inst;
    Fx(audio_fx_api_v2_t *a) : api(a) { inst = a->create_instance(".", nullptr); }
    ~Fx() { if (inst) api->destroy_instance(inst); }
    void set(const char *k, double v) { char b[64]; snprintf(b,sizeof b,"%.6f",v); api->set_param(inst,k,b); }
    std::string get(const char *k) { char b[1024]; int n=api->get_param(inst,k,b,sizeof b); return n>0?std::string(b,n):std::string(); }
    void run(std::vector<int16_t> &v) {
        int f = (int)v.size()/2;
        for (int o = 0; o < f; o += 128) api->process_block(inst, v.data()+o*2, f-o>128?128:f-o);
    }
};

int main() {
    audio_fx_api_v2_t *api = move_audio_fx_init_v2(nullptr);
    ok(api && api->api_version == AUDIO_FX_API_VERSION_2, "api v2");

    /* §14: DryWet = 0 is the ONLY true bypass, and it must NULL. */
    { Fx f(api); f.set("drywet", 0.0);
      auto d = sine(0.5f, 220.f, SR/4); auto w = d; f.run(w);
      ok(memcmp(d.data(), w.data(), d.size()*2) == 0, "drywet=0 is bit-identical to dry"); }

    /* §2/§4: the device at DEFAULTS is NOT transparent — it applies gain and
     * saturates. Measured +3.04 dB on the held-out validation material. Getting
     * this wrong cost 3 dB on every preset in the first validation run. */
    { Fx f(api); auto d = sine(0.2f, 220.f, SR/4); auto w = d; f.run(w);
      double g = db(rms(w)) - db(rms(d));
      ok(g > 2.0 && g < 5.0, "defaults apply the always-on gain (%.2f dB)", g);
      ok(memcmp(d.data(), w.data(), d.size()*2) != 0, "defaults are NOT a bypass"); }

    /* §13: Output is an exact linear gain, POST the nonlinearity. Reference is
     * the device at output 0 dB, NOT the raw input — the device is not
     * transparent, so comparing to the input would fold the saturation in. */
    { auto in = sine(0.05f, 220.f, SR/4);
      Fx ref(api); auto r = in; ref.run(r); double r0 = db(rms(r));
      { Fx f(api); f.set("output", 3.0);  auto v=in; f.run(v);
        ok(fabs(db(rms(v))-r0-3.0) < 0.05, "output +3 dB is exact (%.3f)", db(rms(v))-r0); }
      { Fx f(api); f.set("output",-12.0); auto v=in; f.run(v);
        ok(fabs(db(rms(v))-r0+12.0) < 0.05, "output -12 dB is exact (%.3f)", db(rms(v))-r0); } }

    /* §19: Damp's -3 dB corner IS the parameter value in Hz. */
    { auto lo = sine(0.05f, 100.f, SR/2), hi = sine(0.05f, 2000.f, SR/2);
      Fx a(api); a.set("damp", 2000.0); auto v = hi; a.run(v);
      /* 19000, not 20000: 20 kHz trips the neutral bypass, so the reference
       * would skip the shaper that the test cell runs through. */
      Fx b(api); b.set("damp", 19000.0); auto r = hi; b.run(r);
      double drop = db(rms(v)) - db(rms(r));
      ok(fabs(drop + 3.0) < 1.5, "damp at 2 kHz is -3 dB at 2 kHz (%.2f dB)", drop);
      Fx c(api); c.set("damp", 2000.0); auto l = lo; c.run(l);
      Fx e(api); e.set("damp", 19000.0); auto lr = lo; e.run(lr);
      ok(fabs(db(rms(l)) - db(rms(lr))) < 0.6, "damp leaves 100 Hz alone"); }

    /* §37: the shapers are odd — evens measured 18-20 dB below odds. */
    { Fx f(api); f.set("drive", 1.0); f.set("drive_type", 2);
      auto v = sine(0.5f, 200.f, SR/2); f.run(v);
      double pos=0, neg=0;
      for (size_t i=0;i<v.size();i+=2){ double x=v[i]/32768.0; if(x>0)pos+=x; else neg-=x; }
      ok(fabs(pos-neg)/(pos+neg) < 0.05, "hard drive stays odd-symmetric"); }

    /* §17/§36: the compressor reduces gain at high level and not at low. */
    { auto quiet = sine(0.002f, 220.f, SR/2), loud = sine(0.7f, 220.f, SR/2);
      Fx a(api); a.set("comp", 1.0); auto q = quiet; a.run(q);
      Fx b(api); auto q0 = quiet; b.run(q0);
      Fx c(api); c.set("comp", 1.0); auto L = loud; c.run(L);
      Fx d(api); auto L0 = loud; d.run(L0);
      double gq = db(rms(q))-db(rms(q0)), gl = db(rms(L))-db(rms(L0));
      ok(gq > 6.0, "compressor makes up gain when quiet (%.1f dB)", gq);
      ok(gl < gq - 5.0, "compressor reduces gain when loud (%.1f vs %.1f dB)", gl, gq); }

    /* every declared param reads back, or its knob shows zero on device */
    { Fx f(api);
      const char *keys[] = {"drive","drive_type","crunch","damp","transients","comp",
                            "boom","boom_freq","boom_decay","trim","drywet","output"};
      bool all = true;
      for (auto k : keys) if (f.get(k).empty()) { all=false; printf("      no readback: %s\n", k); }
      ok(all, "every declared param has get_param readback");
      char b[8]; ok(f.api->get_param(f.inst,"nope",b,sizeof b) == -1, "unknown key returns -1"); }

    /* state round-trips */
    { Fx f(api); f.set("drive",0.62); f.set("crunch",0.31); f.set("damp",3000);
      f.set("transients",-0.4); f.set("boom",0.5); f.set("output",-3.5);
      std::string s = f.get("state");
      Fx g(api); g.api->set_param(g.inst,"state",s.c_str());
      ok(g.get("state") == s, "state round-trips byte-for-byte"); }

    /* nothing blows up */
    { Fx f(api); f.set("drive",1.0); f.set("drive_type",1); f.set("crunch",1.0);
      f.set("comp",1.0); f.set("boom",1.0); f.set("transients",1.0); f.set("output",3.0);
      std::vector<int16_t> quiet(SR*2, 0); f.run(quiet);
      bool clean=true; for (auto s : quiet) if (s!=0) clean=false;
      ok(clean, "silence in, silence out at full tilt");
      auto loud = sine(1.0f, 90.f, SR); auto v=loud; f.run(v);
      bool fin=true; for (auto s : v) if (s==-32768) fin=false;
      ok(fin, "full-scale input at full tilt stays in range"); }

    printf("\n%s (%d checks, %d failures)\n", g_fail?"FAILURES":"ALL PASS", g_pass+g_fail, g_fail);
    return g_fail ? 1 : 0;
}
