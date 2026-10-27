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
static int registration_error, critical_depth, recent_logs, power_off_violations;
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
    (void)tag; if (!strcmp(format, "EPD_BUSY_TRACE %s")) trace_logs++;
    else if (!strcmp(format, "EPD_MONO_RECENT %s")) recent_logs++; else logs++;
}
#define ESP_LOGI log_record
#define sys_logi log_record
static void epd_spectra_power_off(void) {
    if (irq_installed) power_off_violations++;
}
'''
WRAPPER = r'''

#define CHECK(x) do { if (!(x)) return __LINE__; } while(0)
__declspec(dllexport) int run(void) {
    hal_epd_mono_session_begin();
    EPD_PROFILE_BEGIN("mono");
    m_profile.first_prepare=true; now_us=100;
    EPD_PROFILE_END();
    CHECK(logs==1 && m_profile_session.samples==0 && m_mono_recent.calls==1);
    for (int i=0;i<194;i++) {
        hal_epd_mono_session_begin(); /* repeated begin preserves both rings */
        now_us=1000+(int64_t)i*220000;
        EPD_PROFILE_BEGIN("mono");
        CHECK(m_profile.call_id==(uint32_t)i+2);
        m_profile.stage_us[EPD_PROFILE_RAM]=60;
        m_profile.stage_us[EPD_PROFILE_REF]=i==192 ? 10 : 120;
        m_profile.bytes=172801; m_profile.ram_bytes=172800;
        m_profile.ram_transactions=120; m_profile.stages=1;
        if(i==1 || i==193) EPD_PROFILE_ERROR(7);
        EPD_BUSY_TRACE(2); EPD_BUSY_TRACE(3); EPD_BUSY_TRACE(9);
        EPD_BUSY_TRACE(4); EPD_BUSY_TRACE(5);
        if (gpio_handler) { now_us+=17; gpio_level=0; gpio_handler(0); }
        EPD_BUSY_TRACE(6);
        if (gpio_handler) { now_us+=120; gpio_level=1; gpio_handler(0); }
        EPD_BUSY_TRACE(7); EPD_BUSY_TRACE(8);
        now_us=1000+(int64_t)i*220000+200;
        EPD_PROFILE_END();
    }
    CHECK(logs==1 && m_profile_session.samples==192);
    CHECK(m_profile_session.successful==191 && m_profile_session.errors==2);
    CHECK(m_profile_session.dropped==2 && m_profile_session.interval_count==191);
    CHECK(m_profile_session.total_sum==191*200);
    CHECK(m_profile_session.phase_sum[EPD_PROFILE_OTHER]==191*20);
    CHECK(m_profile_session.ram_transactions_sum==191*120);
    CHECK(m_profile_session.intervals[0]==220000);
    CHECK(m_mono_recent.calls==195 && m_mono_recent.count==8);
    CHECK(m_mono_recent.steady_count==194 && m_mono_recent.successful==192);
    CHECK(m_mono_recent.errors==2 && m_mono_recent.call_errors==2);
    CHECK(m_mono_recent.total_sum_us==192*200);
    CHECK(m_mono_recent.phase_sum[EPD_PROFILE_RAM]==192*60);
    CHECK(m_mono_recent.phase_sum[EPD_PROFILE_REF]==191*120+10);
    CHECK(m_mono_recent.min_ref_frame==194 && m_mono_recent.min_ref_us==10);
    CHECK(m_mono_recent.min_ref_started_us==1000+(int64_t)192*220000);
    CHECK(m_mono_recent.first_started_us==1000);
    CHECK(m_mono_recent.last_started_us==1000+(int64_t)193*220000);
    for(unsigned i=0;i<8;i++) {
        const unsigned j=(m_mono_recent.next+8-m_mono_recent.count+i)%8;
        CHECK(m_mono_recent.recent[j].frame==188+i);
    }
    CHECK(m_busy_trace.complete && m_busy_trace.active && irq_installed);
    CHECK(!m_busy_trace.overflow && m_busy_trace.frame==195);
    CHECK(m_busy_trace.events[0].frame==3 && m_busy_trace.events[0].marker==1);
    CHECK(m_busy_trace.events[6].marker==0 && m_busy_trace.events[6].us==17);
    CHECK(m_busy_trace.events[m_busy_trace.count-1].frame==7);
    for(unsigned back=0;back<4;back++) {
        const unsigned j=(m_busy_trace.tail_head+5-back)%5;
        CHECK(m_busy_trace.tail[j].frame==195-back);
        CHECK(m_busy_trace.tail[j].complete && !m_busy_trace.tail[j].overflow);
    }
    /* An in-flight fifth slot cannot evict one of the four completed calls. */
    now_us+=1000; EPD_PROFILE_BEGIN("mono");
    CHECK(m_profile.call_id==196);
    CHECK(!m_busy_trace.tail[m_busy_trace.tail_head].complete);
    for(unsigned back=1;back<=4;back++) {
        const unsigned j=(m_busy_trace.tail_head+5-back)%5;
        CHECK(m_busy_trace.tail[j].frame==196-back && m_busy_trace.tail[j].complete);
    }
    const int previous_trace_logs=trace_logs;
    EPD_PROFILE_SESSION_STOP();
    CHECK(!irq_installed && !m_busy_trace.active && trace_logs==previous_trace_logs);
    const int64_t stopped=m_busy_trace.end_us;
    const unsigned count=m_busy_trace.tail[m_busy_trace.tail_head].count;
    now_us+=99; gpio_level=0; epd_busy_trace_record(0);
    CHECK(m_busy_trace.tail[m_busy_trace.tail_head].count==count);
    EPD_PROFILE_SESSION_STOP(); CHECK(m_busy_trace.end_us==stopped);
    hal_epd_mono_session_end();
    CHECK(logs==2 && trace_logs==2 && recent_logs==1 && !m_mono_session);
    CHECK(m_profile_session.samples==0 && !m_busy_trace.session && !m_mono_recent.calls);
    hal_epd_mono_session_end(); CHECK(logs==2 && trace_logs==2 && recent_logs==1);

    /* Per-frame overflow is explicit, and never prevents later tail capture. */
    hal_epd_mono_session_begin(); epd_busy_trace_frame(300);
    for(unsigned i=0;i<EPD_BUSY_TRACE_LIMIT;i++) epd_busy_trace_record(0);
    CHECK(m_busy_trace.overflow && m_busy_trace.active);
    CHECK(m_busy_trace.tail[m_busy_trace.tail_head].overflow);
    CHECK(m_busy_trace.tail[m_busy_trace.tail_head].count==20);
    epd_busy_trace_call_end(300);
    epd_busy_trace_frame(301);
    CHECK(!m_busy_trace.tail[m_busy_trace.tail_head].overflow);
    CHECK(m_busy_trace.tail[m_busy_trace.tail_head].count==1);
    epd_busy_trace_call_end(301);
    hal_epd_mono_session_end();
    CHECK(trace_logs==4 && recent_logs==2 && !irq_installed);

    /* GPIO failure is reported, while all-session metrics retain error detail. */
    registration_error=7;
    hal_epd_mono_session_begin();
    m_profile_session.samples=1;
    now_us+=1000; EPD_PROFILE_BEGIN("mono");
    CHECK(m_busy_trace.registration_err==7 && !m_busy_trace.active && !irq_installed);
    EPD_PROFILE_TIMEOUT(); EPD_PROFILE_SPI(7,0,false);
    now_us+=20; EPD_PROFILE_END();
    CHECK(m_mono_recent.call_errors==1 && m_mono_recent.call_timeouts==1);
    CHECK(m_mono_recent.call_spi_errors==1 && m_mono_recent.errors==1);
    hal_epd_mono_session_end();
    CHECK(trace_logs==6 && recent_logs==3);
    registration_error=0;

    /* Call ids no longer wrap at 255; a short session remains incomplete. */
    hal_epd_mono_session_begin(); m_mono_recent.calls=65535;
    m_profile_session.samples=1;
    now_us+=1000; EPD_PROFILE_BEGIN("mono");
    CHECK(m_profile.call_id==65536 && m_busy_trace.frame==65536);
    now_us+=20; EPD_PROFILE_END();
    CHECK(!m_busy_trace.complete && m_busy_trace.tail[m_busy_trace.tail_head].complete);
    hal_epd_mono_session_end();
    CHECK(trace_logs==8 && recent_logs==4 && !irq_installed);
    CHECK(power_off_violations==0 && critical_depth==0);
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
        # Worst-width numeric values fit each shared 4096-byte END buffer.
        # Combined diagnostics + the unchanged summary remain below 3s UART.
        import json
        u32, i64 = 4294967295, 9223372036854775807
        early = dict(window="early", initial_level=1, registration_err=u32,
            overflow=False, capture_complete=False, origin_us=i64,
            events=[[u32, u32, 255, 255]] * 80)
        tail = dict(window="tail", initial_level=1, registration_err=u32,
            overflow=False, capture_complete=False, origin_us=i64,
            end_us=i64, end_level=1, partial_frame=u32, partial_overflow=False,
            frames=[dict(frame=u32, initial_level=1, overflow=False,
                         events=[[i64, 255, 255]] * 20)] * 4)
        recent = dict(unit="us", calls_seen=u32, errors=u32, timeouts=u32,
            spi_errors=u32, calls=[[u32, i64, i64, i64, i64, u32,
                                   False, False, u32, u32]] * 8,
            steady=dict(count=u32, ok_count=u32, errors=u32, timeouts=u32,
                spi_errors=u32, first_started_us=i64, last_started_us=i64,
                total_sum_us=i64, phase_sum_us=[i64] * 7, min_ref_us=i64,
                min_ref_frame=u32, min_ref_started_us=i64))
        sizes = [len(json.dumps(x, separators=(",", ":")))
                 for x in (early, tail, recent)]
        self.assertTrue(all(n < 4096 for n in sizes), sizes)
        self.assertLess((sum(sizes) + 1600) * 10 / 115200, 3)
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
