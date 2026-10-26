/* Host-only deterministic dependencies; production functions are inserted by Python. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <stdarg.h>
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
#define pdMS_TO_TICKS(x) (x)
#define configASSERT(x) assert(x)
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_DMA 2
#define ESP_OK 0
#define WIFI_SERVICE_TAG "test"
#define WIFI_DIRECT_DOWNLOADING 1
#define WIFI_DIRECT_ERR_NONE 0
#define WIFI_DIRECT_ERR_HTTP 1
#define WIFI_DIRECT_ERR_SAVE 2
#define WIFI_DIRECT_ERR_CANCELLED 3
#define WIFI_DIRECT_ERR_RESOURCE 4
#define FILE_SAVE_WIFI 1
#define FILE_SAVE_BLE 2
#define FILM_HEADER_SIZE 32
#define CAPACITY 180000

typedef unsigned TickType_t;
typedef int BaseType_t;
typedef struct { void *items[3]; unsigned count; } queue_t;
typedef queue_t *QueueHandle_t;
typedef void *esp_http_client_handle_t;
typedef struct { const char *url; int timeout_ms; } esp_http_client_config_t;
typedef struct { char url[512], path[512]; bool file; } wifi_direct_args_t;
typedef struct {
 int owner; uint8_t *pdata; uint32_t data_len;
 void (*done)(void *,int,int64_t); void *context;
} file_msg_t;
static struct {
 int save_owner, save_failed, save_skip_relocate;
 void *save_file_handle;
 uint32_t save_file_size, save_written, save_header_len;
 char save_path[512]; uint8_t save_header[32];
} m_file_state;
static int m_save_result, m_save_done;
static file_msg_t jobs[3];
static unsigned job_count, peak_jobs, callbacks, free_calls, sem_gives;
static unsigned total_bytes, available_bytes, read_at, disk_at, read_calls, blocks;
static unsigned lengths[20], progress, commits, aborts, pool_allocs, pool_frees;
static int fail_block, reject_block, cancel_after, alloc_fail;
static uint8_t disk[CAPACITY];
static uint8_t *pool;
static int64_t now;
static void process_message(file_msg_t msg);
static uint8_t byte_at(unsigned i) { return (uint8_t)((i * 37 + i / 257) & 255); }
static void sys_logi(const char *tag, const char *fmt, ...) { (void)tag; (void)fmt; }
static int64_t esp_timer_get_time(void) { return ++now; }
static TickType_t xTaskGetTickCount(void) { return (unsigned)(now / 100); }
static bool wifi_direct_cancelled(void) { return cancel_after >= 0 && read_at >= (unsigned)cancel_after; }
static void wifi_direct_status(int state, int err, uint32_t got, uint32_t total) {
 (void)state; (void)err; assert(got <= total && got >= progress); progress=got;
}
static void *heap_caps_malloc(size_t size, int caps) {
 assert(size==3*16384 && caps==MALLOC_CAP_SPIRAM); pool_allocs++;
 if(alloc_fail) return NULL;
 pool=malloc(size); assert(pool); return pool;
}
static void heap_caps_free(void *p) {
 assert(p==pool && job_count==0); pool_frees++; free(p); pool=NULL;
}
static unsigned heap_caps_get_free_size(int caps) { (void)caps; return 100000; }
static unsigned heap_caps_get_largest_free_block(int caps) { (void)caps; return 100000; }
static void test_free(void *p) { free_calls++; free(p); }
#define free test_free
static int xSemaphoreGive(int sem) { (void)sem; sem_gives++; return 1; }
static bool file_has_suffix(const char *path,const char *suffix) {
 size_t a=strlen(path),b=strlen(suffix); return a>=b && !strcmp(path+a-b,suffix);
}
static void file_log_header(const char *s,const void *p,unsigned n) { (void)s;(void)p;(void)n; }
static size_t file_save_write_dma(void *handle, const uint8_t *p, size_t len, uint32_t offset) {
 assert(handle && offset==disk_at && disk_at+len<=CAPACITY);
 unsigned block=disk_at/16384;
 size_t written=(fail_block==(int)block) ? len/2 : len;
 for(size_t i=0;i<len;i++) assert(p[i]==byte_at(offset+(unsigned)i));
 memcpy(disk+disk_at,p,written); disk_at+=(unsigned)written; return written;
}
/* REAL_FILE_BRANCH */
static void complete_one(void) {
 assert(job_count); file_msg_t msg=jobs[0];
 memmove(jobs,jobs+1,(--job_count)*sizeof(*jobs));
 /* The actual file-task branch must not free borrowed memory or touch sync state. */
 unsigned before_free=free_calls,before_sem=sem_gives; int result=m_save_result;
 process_message(msg); callbacks++;
 assert(free_calls==before_free && sem_gives==before_sem && m_save_result==result);
}
static QueueHandle_t xQueueCreate(unsigned count,size_t size) {
 assert(count==3 && size==sizeof(void*)); return calloc(1,sizeof(queue_t));
}
static int xQueueSend(QueueHandle_t q,const void *item,TickType_t wait) {
 (void)wait; assert(q->count<3); q->items[q->count++]=*(void *const *)item; return pdPASS;
}
static int xQueueReceive(QueueHandle_t q,void *item,TickType_t wait) {
 if(!q->count && wait && job_count) complete_one();
 if(!q->count) return 0;
 *(void**)item=q->items[0]; memmove(q->items,q->items+1,(--q->count)*sizeof(void*)); return pdPASS;
}
static void vQueueDelete(QueueHandle_t q) { assert(!q->count && !job_count); free(q); }
static int service_file_save_data_async(int owner,uint8_t *p,uint32_t len,
                                        void(*done)(void*,int,int64_t),void *ctx) {
 assert(owner==FILE_SAVE_WIFI && done && job_count<3 && pool);
 assert(p>=pool && p+len<=pool+3*16384 && len>0 && len<=16384);
 for(unsigned i=0;i<job_count;i++) assert(jobs[i].pdata!=p);
 if(reject_block==(int)blocks) return -1;
 lengths[blocks++]=len;
 jobs[job_count++]=(file_msg_t){owner,p,len,done,ctx};
 if(job_count>peak_jobs) peak_jobs=job_count;
 return 0;
}
static int service_file_save_start_to(int owner,const char *path,uint32_t total) {
 m_file_state.save_owner=owner; m_file_state.save_file_size=total;
 m_file_state.save_file_handle=&disk; m_file_state.save_skip_relocate=1;
 memcpy(m_file_state.save_path,path,strlen(path)+1); return 0;
}
static int service_file_save_start(int owner,const char *path,uint32_t total) {
 int result=service_file_save_start_to(owner,path,total); m_file_state.save_skip_relocate=0; return result;
}
static int service_file_save_stop(int owner,int relocate) {
 (void)owner;(void)relocate; assert(job_count==0 && !pool);
 assert(disk_at==total_bytes && !m_file_state.save_failed); commits++; return 0;
}
static void service_file_save_abort(int owner) { (void)owner; assert(job_count==0 && !pool); aborts++; }
static esp_http_client_handle_t esp_http_client_init(const esp_http_client_config_t *cfg) { assert(cfg->url); return &disk; }
static int esp_http_client_open(void *c,int n) { (void)c;(void)n;return ESP_OK; }
static int64_t esp_http_client_fetch_headers(void *c) { (void)c;return total_bytes; }
static int esp_http_client_get_status_code(void *c) { (void)c;return 200; }
static int esp_http_client_read(void *c,char *out,int want) {
 (void)c;read_calls++; if(read_at==available_bytes) return 0;
 unsigned n=1+(read_calls*113)%1600;
 if(n>(unsigned)want)n=(unsigned)want;
 if(n>available_bytes-read_at)n=available_bytes-read_at;
 for(unsigned i=0;i<n;i++)out[i]=(char)byte_at(read_at+i);
 read_at+=n;return (int)n;
}
static void esp_http_client_close(void *c) { (void)c;assert(!job_count); }
static void esp_http_client_cleanup(void *c) { (void)c; }
static size_t strlcpy(char *dst,const char *src,size_t n) {
 size_t len=strlen(src);if(n){size_t copy=len<n-1?len:n-1;memcpy(dst,src,copy);dst[copy]=0;}return len;
}
/* REAL_WIFI */
static void reset(unsigned n) {
 assert(!pool && !job_count);
 memset(&m_file_state,0,sizeof(m_file_state)); memset(disk,0,sizeof(disk));
 total_bytes=available_bytes=n; read_at=disk_at=read_calls=blocks=progress=commits=aborts=0;
 peak_jobs=callbacks=free_calls=sem_gives=pool_allocs=pool_frees=0;
 fail_block=reject_block=cancel_after=-1;alloc_fail=0;m_save_result=73;now=0;
}
static uint8_t run(bool film) {
 wifi_direct_args_t args={.url="http://test/file.film",.path="/sdcard/test.bin",.file=!film};
 uint32_t received=0,total=0;
 uint8_t result=wifi_direct_download(&args,&received,&total);
 assert(total==total_bytes && received==progress && !job_count && !pool);
 assert(callbacks==blocks && pool_allocs==1 && pool_frees==(unsigned)!alloc_fail);
 return result;
}
int main(void) {
 reset(5*16384+713);assert(run(false)==0);
 assert(peak_jobs==3 && blocks==6 && lengths[5]==713 && read_calls>blocks*5);
 assert(commits==1 && !aborts && disk_at==total_bytes && progress==total_bytes);
 for(unsigned i=0;i<disk_at;i++)assert(disk[i]==byte_at(i));
 for(unsigned i=0;i<5;i++)assert(lengths[i]==16384);
 reset(16384+31);assert(run(true)==0 && commits==1 && blocks==2 && lengths[1]==31);
 assert(m_file_state.save_header_len==32);
 for(unsigned i=0;i<32;i++)assert(m_file_state.save_header[i]==byte_at(i));
 reset(5*16384+713);fail_block=1;assert(run(false)==WIFI_DIRECT_ERR_SAVE && !commits && aborts==1);
 reset(5*16384+713);cancel_after=3*16384+100;assert(run(false)==WIFI_DIRECT_ERR_CANCELLED && !commits && aborts==1);
 assert(callbacks>=3);
 reset(5*16384+713);available_bytes=3*16384+99;assert(run(false)==WIFI_DIRECT_ERR_HTTP && !commits && aborts==1);
 assert(callbacks==3 && disk_at==3*16384);
 reset(5*16384+713);reject_block=2;assert(run(false)==WIFI_DIRECT_ERR_SAVE && !commits && aborts==1 && callbacks==2);
 reset(99);alloc_fail=1;assert(run(false)==WIFI_DIRECT_ERR_RESOURCE && !commits && aborts==1);
 /* Existing BLE ownership: actual synchronous branch frees even after write failure. */
 for(int fail=0;fail<2;fail++) {
  reset(17);service_file_save_start_to(FILE_SAVE_BLE,"test.bin",17);fail_block=fail?0:-1;
  uint8_t *p=malloc(17);for(unsigned i=0;i<17;i++)p[i]=byte_at(i);
  process_message((file_msg_t){.owner=FILE_SAVE_BLE,.pdata=p,.data_len=17});
  assert(free_calls==1 && sem_gives==1 && m_save_result==(fail?-1:0));
 }
 puts("PASS: real HTTP/file-task C; short reads, ordered 16KiB blocks/tail, 3 borrowed slots, delayed callbacks/drain, write failure/cancel/truncation/enqueue/resource failure abort, BLE sync free");
 return 0;
}

