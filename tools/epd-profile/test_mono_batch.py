"""Compare the real mono writer against the frozen pre-batching C implementation.

Run with: python -m unittest discover -s tools/epd-profile -p test_mono_batch.py
Requires clang on Windows, or a native C compiler on POSIX. Only SPI and profiling
are stubbed; both encoders and both writer loops execute as C, including NULL.
"""
import ctypes
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "firmware/frame_film_ark/components/film_hal/src/hal_epd_370.c"
MONO_BYTES = 720 * 480 // 8
RAM_BYTES = MONO_BYTES * 4


def extract_function(source, declaration):
    start = source.index(declaration + "\n{")
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HARNESS = r"""
typedef unsigned char uint8_t;
typedef unsigned int uint32_t;
#define NULL ((void *)0)
#define DMA_ATTR
#define EPD_WIDTH 720
#define EPD_HEIGHT 480
#define EPD_INPUT_LINE (EPD_WIDTH / 2)
#define EPD_MONO_LINE (EPD_WIDTH / 8)
#define EPD_MONO_BYTES (EPD_WIDTH * EPD_HEIGHT / 8)
#define EPD_MONO_BATCH_LINES 4
#define MONO_CODE_BIT_WHITE 1
#define DTM1 0x10
#define BUSY_TIMEOUT_INIT_MS 15000
#define EPD_PROFILE_STAGE_BEGIN(x)
#define EPD_PROFILE_STAGE_END(x)
#define EPD_BUSY_TRACE(x)
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif
EXPORT uint8_t m_mono_prev[EPD_MONO_BYTES];
EXPORT uint8_t trace[EPD_MONO_BYTES * 4];
EXPORT uint32_t lengths[EPD_HEIGHT];
EXPORT uint32_t transactions, written, commands, waits, invalid;
static void EPD_W21_WriteCMD(uint8_t command) {
    commands++;
    if (command != DTM1) invalid++;
}
static void epd_wait_busy(uint32_t timeout) {
    waits++;
    if (timeout != BUSY_TIMEOUT_INIT_MS) invalid++;
}
static void EPD_W21_WriteDATA_Bulk(const uint8_t *data, uint32_t len) {
    if (transactions >= EPD_HEIGHT || written + len > sizeof(trace)) {
        invalid++;
        return;
    }
    lengths[transactions++] = len;
    for (uint32_t i = 0; i < len; i++) trace[written++] = data[i];
}
"""
WRAPPER = r"""
EXPORT void run(const uint8_t *bitmap, const uint8_t *initial, int legacy) {
    for (uint32_t i = 0; i < EPD_MONO_BYTES; i++) m_mono_prev[i] = initial[i];
    transactions = written = commands = waits = invalid = 0;
    if (legacy) legacy_epd_spectra_mono_write(bitmap);
    else epd_spectra_mono_write(bitmap);
}
"""


class MonoBatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = DRIVER.read_text(encoding="utf-8")
        declarations = [
            "static uint8_t epd_spectra_reverse_bits(uint8_t x)",
            "static uint8_t epd_spectra_mono_code_byte(uint8_t bitmap_byte)",
            "static void epd_spectra_mono_write(const uint8_t *mono_bitmap)",
        ]
        current = "\n".join(extract_function(source, d) for d in declarations)
        legacy = Path(__file__).with_name("mono_legacy_fixture.c").read_text(encoding="utf-8")
        for name in ("epd_spectra_reverse_bits", "epd_spectra_mono_code_byte", "epd_spectra_mono_write"):
            legacy = legacy.replace(name, "legacy_" + name)
        cls.temp = tempfile.TemporaryDirectory(prefix="framefilm-mono-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        path = Path(cls.temp.name)
        c_file = path / "mono_test.c"
        c_file.write_text(HARNESS + legacy + current + WRAPPER, encoding="utf-8")
        dll = path / ("mono_test.dll" if os.name == "nt" else "mono_test.so")
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            raise RuntimeError("A native C compiler is required for the real-writer comparison")
        args = [compiler, "-shared", "-O0", "-fno-builtin", "-Wall", "-Wextra", "-Werror"]
        if os.name == "nt":
            args += ["-fuse-ld=lld", "-nostdlib", "-Wl,/noentry", "-Wl,/nodefaultlib"]
        else:
            args += ["-fPIC"]
        result = subprocess.run(args + [str(c_file), "-o", str(dll)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.dll = ctypes.CDLL(str(dll))
        cls.dll.run.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
        # ctypes unloads late on Windows; unload before deleting the temporary DLL.
        if os.name == "nt":
            import _ctypes
            cls.addClassCleanup(_ctypes.FreeLibrary, cls.dll._handle)

    def invoke(self, bitmap, initial, legacy):
        buf_type = ctypes.c_ubyte * MONO_BYTES
        source = None if bitmap is None else buf_type.from_buffer_copy(bitmap)
        self.dll.run(source, buf_type.from_buffer_copy(initial), legacy)
        scalar = lambda name: ctypes.c_uint.in_dll(self.dll, name).value
        self.assertEqual(scalar("invalid"), 0)
        self.assertEqual(scalar("commands"), 1)
        self.assertEqual(scalar("waits"), 1)
        self.assertEqual(scalar("written"), RAM_BYTES)
        count = scalar("transactions")
        self.assertEqual(count, 480 if legacy else 120)
        lengths = list((ctypes.c_uint * 480).in_dll(self.dll, "lengths"))[:count]
        self.assertEqual(lengths, [360 if legacy else 1440] * count)
        stream = bytes((ctypes.c_ubyte * RAM_BYTES).in_dll(self.dll, "trace"))
        prev = bytes(buf_type.in_dll(self.dll, "m_mono_prev"))
        return stream, prev

    def compare(self, bitmap, initial):
        old = self.invoke(bitmap, initial, True)
        new = self.invoke(bitmap, initial, False)
        self.assertEqual(new, old)
        return new

    def test_all_four_old_new_pixel_combinations(self):
        observed = set()
        for previous in (0, 255):
            for bitmap in (0, 255):
                with self.subTest(previous=previous, bitmap=bitmap):
                    stream, prev = self.compare(bytes([bitmap]) * MONO_BYTES, bytes([previous]) * MONO_BYTES)
                    observed.update(stream)
                    self.assertEqual(prev, bytes([255 - bitmap]) * MONO_BYTES)
        self.assertEqual(observed, {0x00, 0x11, 0x22, 0x33})

    def test_mixed_pixels_row_batch_frame_edges_and_following_frame(self):
        rng = random.Random(7737671)
        bitmap = bytearray(rng.randbytes(MONO_BYTES))
        initial = rng.randbytes(MONO_BYTES)
        for i, value in zip((0, 89, 90, 359, 360, MONO_BYTES - 1), (0x80, 1, 0xAA, 0x55, 0x81, 0xFE)):
            bitmap[i] = value
        _, prev = self.compare(bitmap, initial)
        self.compare(rng.randbytes(MONO_BYTES), prev)

    def test_every_old_byte_and_raw_input_byte_pair(self):
        # Exercise all 65536 pairs through the real old/new C writer loops.
        # Two full-sized frames preserve complete stream and prev assertions,
        # including the padded tail and normal row/batch boundaries.
        for start in range(0, 65536, MONO_BYTES):
            pairs = [i if i < 65536 else 0
                     for i in range(start, start + MONO_BYTES)]
            initial = bytes(i >> 8 for i in pairs)
            bitmap = bytes(i & 255 for i in pairs)
            with self.subTest(first_pair=start):
                self.compare(bitmap, initial)

    def test_null_white_clear_matches_zero_bitmap(self):
        initial = random.Random(123).randbytes(MONO_BYTES)
        cleared = self.compare(None, initial)
        self.assertEqual(cleared, self.invoke(bytes(MONO_BYTES), initial, False))
        self.assertEqual(cleared[1], bytes([255]) * MONO_BYTES)


if __name__ == "__main__":
    unittest.main()
