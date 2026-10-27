"""Compile real Ark HTTP pipeline/file-task branches with deterministic host IO stubs.
Run: python tools/wifi-transfer-tests/check_pipeline.py [--cc /path/to/clang]
No ESP-IDF build or device IO; scheduling is deliberately deferred until wait/drain.
"""
from pathlib import Path
import argparse, re, shutil, subprocess, tempfile
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'firmware/frame_film_ark/components/film_service/src'

def function(text, name):
    match = re.search(r'^static uint8_t ' + name + r'\([^;]*?\)\s*\{', text, re.M)
    assert match, name
    start = text.index('{', match.start())
    depth = 0
    for end in range(start, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if not depth:
            return text[match.start():end + 1] + '\n'
    raise AssertionError(name)

wifi = (BASE / 'service_wifi.c').read_text(encoding='utf-8')
file = (BASE / 'service_file.c').read_text(encoding='utf-8')
helpers = wifi[wifi.index('#define WIFI_DIRECT_SLOT_COUNT'):wifi.index('static uint8_t wifi_direct_download')]
branch = file[file.index('case MSG_FILE_SAVE_DATA:'):file.index('case MSG_FILE_SAVE_STOP:')]
branch = branch[branch.index('{'):branch.rfind('}') + 1]
# Execute the exact switch branch; its break targets this one-iteration loop.
branch = 'static void process_message(file_msg_t msg) { do ' + branch + ' while(0); }\n'
harness = (Path(__file__).with_name('host_stubs.c')).read_text(encoding='utf-8')
source = harness.replace('/* REAL_FILE_BRANCH */', branch).replace('/* REAL_WIFI */', helpers + function(wifi, 'wifi_direct_download'))
parser = argparse.ArgumentParser()
parser.add_argument('--cc', default=shutil.which('clang'))
args = parser.parse_args()
if not args.cc:
    parser.error('clang is required; pass --cc')
with tempfile.TemporaryDirectory(prefix='framefilm-wifi-') as tmp:
    c = Path(tmp) / 'check.c'
    binary = Path(tmp) / 'check.exe'
    c.write_text(source, encoding='utf-8')
    subprocess.run([args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
