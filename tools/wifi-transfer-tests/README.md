# WiFi direct HTTP pipeline host check

Run from the repository root:

```text
python tools/wifi-transfer-tests/check_pipeline.py
```

Requires Python 3 and a native `clang` on PATH; `--cc` accepts its full path.
The script extracts the current production pipeline helpers, `wifi_direct_download`,
and the `MSG_FILE_SAVE_DATA` switch branch at run time, compiles them with
`-std=c11 -Wall -Wextra -Werror`, executes assertions, then removes temporary files.
It does not keep a separate copy of the pipeline algorithm.

`host_stubs.c` supplies HTTP, heap, file IO, queue and clock dependencies. HTTP
returns variable short reads; queued file messages remain pending until the
producer waits, so a normal transfer must use all three slots and drain them
before freeing the pool or committing. Disk writes execute the real file-task
branch, including callback and synchronous-buffer ownership behavior.

Covered cases: ordered full blocks and final tail, film header, saved-byte
progress, delayed completion and slot reuse, write failure, cancellation after
queued writes, truncated HTTP body, enqueue failure, PSRAM allocation failure,
and synchronous BLE buffer freeing on success and write failure.

This is deterministic host verification. It does not validate ESP-IDF task
scheduling, HTTP transport timing, SDMMC DMA, physical storage recovery, device
throughput or BLE radio behavior.
