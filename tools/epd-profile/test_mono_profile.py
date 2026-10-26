"""Exercise the real PROFILE aggregate in a small native C harness."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "firmware/frame_film_ark/components/film_hal/src/hal_epd_370.c"

HARNESS = r'''
typedef unsigned int uint32_t;
typedef unsigned long long uint64_t;
typedef long long int64_t;
typedef unsigned long long size_t;
typedef int bool;
typedef int esp_err_t;
#define NULL ((void *)0)
#define true 1
#define false 0
#define ESP_OK 0
#define ESP_ERR_TIMEOUT 1
#define UINT32_MAX 4294967295U
#define PRId64 "lld"
#define PRIu64 "llu"
#define PRIu32 "u"
#define EPD_TAG "epd"
int _fltused;
static int logs;
/* Only hardware/runtime seams are stubbed: the production PROFILE and trace
 * state machines below are compiled verbatim. snprintf is format-checked;
 * serialization length is bounded separately by the Python assertion. */
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef int portMUX_TYPE;
#define DRAM_ATTR
#define IRAM_ATTR
#define portMUX_INITIALIZER_UNLOCKED 0
#define ESP_ERR_INVALID_STATE 2
#define ESP_INTR_FLAG_IRAM 1
#define GPIO_INTR_ANYEDGE 3
#define GPIO_INTR_DISABLE 0
#define EPD_BUSY_PIN 11
static int GPIO, gpio_level = 1, irq_installed, irq_removes, trace_logs;
static int registration_error, critical_depth;
static void (*gpio_handler)(void *);
static void critical_enter(portMUX_TYPE *mux) { (void)mux; critical_depth++; }
static void critical_exit(portMUX_TYPE *mux) { (void)mux; critical_depth--; }
#define portENTER_CRITICAL critical_enter
#define portEXIT_CRITICAL critical_exit
#define portENTER_CRITICAL_ISR critical_enter
#define portEXIT_CRITICAL_ISR critical_exit
static int gpio_ll_get_level(int *hw, int pin) { (void)hw; (void)pin; return gpio_level; }
static int gpio_install_isr_service(int flags) {
    (void)flags; return registration_error ? registration_error : ESP_ERR_INVALID_STATE;
}
static int gpio_set_intr_type(int pin, int type) { (void)pin; (void)type; return 0; }
static int gpio_isr_handler_add(int pin, void (*fn)(void *), void *arg) {
    (void)pin; (void)arg; gpio_handler=fn; irq_installed=1; return 0;
}
static int gpio_intr_disable(int pin) { (void)pin; return 0; }
static int gpio_isr_handler_remove(int pin) {
    (void)pin; gpio_handler=0; irq_installed=0; irq_removes++; return 0;
}
__attribute__((format(printf, 3, 4)))
static int snprintf(char *out, size_t cap, const char *format, ...) {
    (void)format; if(cap) out[0]=0; return 0;
}

static int64_t now_us;
static bool m_mono_session, m_ignore_busy;
static int64_t esp_timer_get_time(void) { return now_us; }
static void *memset(void *p, int c, size_t n) {
    unsigned char *b = p;
    while(n--) *b++ = (unsigned char)c;
    return p;
}
static int strcmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static void qsort(void *p, size_t n, size_t size, int (*cmp)(const void *, const void *)) {
    unsigned char *a = p;
    for(size_t i=0; i<n; i++) for(size_t j=i+1; j<n; j++)
        if(cmp(a+i*size, a+j*size)>0) for(size_t k=0;k<size;k++) {
            unsigned char t=a[i*size+k]; a[i*size+k]=a[j*size+k]; a[j*size+k]=t;
        }
}
__attribute__((format(printf, 2, 3)))
static void log_record(const char *tag, const char *format, ...) {
    (void)tag; if (!strcmp(format, "EPD_BUSY_TRACE %s")) trace_logs++; else logs++;
}
#define ESP_LOGI log_record
#define sys_logi log_record
static void epd_spectra_power_off(void) {}
'''
WRAPPER = r'''
#define CHECK(x) do { if (!(x)) return __LINE__; } while(0)
__declspec(dllexport) int run(void) {
    hal_epd_mono_session_begin();
    EPD_PROFILE_BEGIN("mono");
    m_profile.first_prepare=true; now_us=100;
    EPD_PROFILE_END();
    CHECK(logs==1 && m_profile_session.samples==0);
    for (int i=0;i<194;i++) {
        hal_epd_mono_session_begin(); /* repeated begin must preserve samples */
        now_us=1000+(int64_t)i*220000;
        EPD_PROFILE_BEGIN("mono");
        m_profile.stage_us[EPD_PROFILE_RAM]=60;
        m_profile.stage_us[EPD_PROFILE_REF]=120;
        m_profile.bytes=172801; m_profile.ram_bytes=172800;
        m_profile.ram_transactions=120; m_profile.stages=1;
        if(i==1 || i==193) EPD_PROFILE_ERROR(7);
        now_us+=200;
        EPD_PROFILE_END();
    }
    CHECK(logs==1 && m_profile_session.samples==192);
    CHECK(m_profile_session.successful==191 && m_profile_session.errors==2);
    CHECK(m_profile_session.dropped==2 && m_profile_session.interval_count==191);
    CHECK(m_profile_session.total_sum==191*200);
    CHECK(m_profile_session.phase_sum[EPD_PROFILE_OTHER]==191*20);
    CHECK(m_profile_session.ram_transactions_sum==191*120);
    CHECK(m_profile_session.intervals[0]==220000);
    hal_epd_mono_session_end();
    CHECK(logs==2 && m_profile_session.samples==0 && !m_mono_session);
    hal_epd_mono_session_end(); CHECK(logs==2);
    hal_epd_mono_session_begin();
    now_us+=1000; EPD_PROFILE_BEGIN("mono");
    m_profile.stage_us[EPD_PROFILE_PON]=10;
    now_us+=20; EPD_PROFILE_END();
    CHECK(logs==3 && m_profile_session.samples==0);
    hal_epd_mono_session_end(); CHECK(logs==3);
    hal_epd_mono_session_begin();
    now_us+=1000; EPD_PROFILE_BEGIN("mono");
    now_us+=20; EPD_PROFILE_END();
    CHECK(m_profile_session.samples==1);
    hal_epd_mono_session_end();
    CHECK(logs==4 && m_profile_session.samples==0);

    CHECK(trace_logs==3 && !irq_installed && critical_depth==0);
    /* Four complete frames plus next begin; timestamps and pin levels come
     * through the same production recorder used by both ISR and task markers. */
    hal_epd_mono_session_begin();
    epd_busy_trace_frame();
    CHECK(m_busy_trace.frame==1 && m_busy_trace.initial_level==1 && irq_installed);
    CHECK(m_busy_trace.count==1 && m_busy_trace.events[0].marker==1);
    now_us+=17; gpio_level=0; gpio_handler(0);
    CHECK(m_busy_trace.events[1].us==17 && m_busy_trace.events[1].marker==0);
    CHECK(m_busy_trace.events[1].level==0 && m_busy_trace.events[1].frame==1);
    for(int frame=2;frame<=5;frame++) epd_busy_trace_frame();
    CHECK(m_busy_trace.complete && !m_busy_trace.active && !irq_installed);
    CHECK(m_busy_trace.frame==5 && m_busy_trace.events[m_busy_trace.count-1].marker==1);
    CHECK(m_busy_trace.events[m_busy_trace.count-1].frame==5);
    hal_epd_mono_session_end();
    CHECK(trace_logs==4 && !m_busy_trace.session && m_busy_trace.count==0);
    hal_epd_mono_session_end(); CHECK(trace_logs==4);
    /* Overflow is bounded, explicit and cannot count as a complete capture. */
    hal_epd_mono_session_begin(); epd_busy_trace_frame();
    for(unsigned i=0;i<EPD_BUSY_TRACE_LIMIT;i++) epd_busy_trace_record(0);
    CHECK(m_busy_trace.count==EPD_BUSY_TRACE_LIMIT && m_busy_trace.overflow);
    CHECK(!m_busy_trace.active && !m_busy_trace.complete);
    hal_epd_mono_session_end();
    CHECK(trace_logs==5 && !irq_installed && m_busy_trace.count==0);
    /* Registration failure and cancellation before enough frames clean up. */
    registration_error=7;
    hal_epd_mono_session_begin(); epd_busy_trace_frame();
    CHECK(m_busy_trace.registration_err==7 && !m_busy_trace.active && !irq_installed);
    hal_epd_mono_session_end(); CHECK(trace_logs==6);
    registration_error=0;
    hal_epd_mono_session_begin(); epd_busy_trace_frame();
    hal_epd_mono_session_end();
    CHECK(trace_logs==7 && !irq_installed && !m_busy_trace.session);
    CHECK(irq_removes==4 && critical_depth==0);
    return 0;
}
'''

@unittest.skipUnless(os.name == "nt" and shutil.which("clang"), "requires Windows clang DLL toolchain")
class MonoProfileTest(unittest.TestCase):
    def test_bounded_aggregate_format_and_session_lifecycle(self):
        from test_mono_batch import extract_function
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("typedef enum {", source.index("/* Profiling owns"))
        end = source.index("#else", start)
        profile = source[start:end]
        calls = "\n".join(extract_function(source, decl) for decl in (
            "void hal_epd_mono_session_begin(void)", "void hal_epd_mono_session_end(void)"))
        # Four frame markers, five timestamps and every bounded event fit the
        # production buffer even at the integer type limits.
        import json
        maximum = dict(initial_level=1, registration_err=2147483647,
            overflow=True, capture_complete=False, origin_us=9223372036854775807,
            events=[[4294967295, 255, 255, 255]] * 80)
        self.assertLess(len(json.dumps(maximum, separators=(",", ":"))), 2560)
        with tempfile.TemporaryDirectory(prefix="ark-profile-host-") as folder:
            path = Path(folder)
            c_file = path / "profile.c"
            c_file.write_text(HARNESS + profile + calls + WRAPPER, encoding="utf-8")
            dll = path / "profile.dll"
            compiler = shutil.which("clang")
            if compiler is None:
                raise RuntimeError("clang is required")
            result = subprocess.run([compiler, "-shared", "-O0", "-fno-builtin",
                "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-fuse-ld=lld",
                "-nostdlib", "-Wl,/noentry", "-Wl,/nodefaultlib", str(c_file), "-o", str(dll)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            library = ctypes.CDLL(str(dll))
            try:
                self.assertEqual(library.run(), 0, "C CHECK line returned")
            finally:
                import _ctypes
                _ctypes.FreeLibrary(library._handle)

if __name__ == "__main__":
    unittest.main()
