"""Compile real Ark IMAGE/open functions against small host interface fixtures.

Run: python tools/epd-profile/check_atomic_image_open.py
Windows requires WSL gcc; Linux uses native gcc. No firmware build or device IO.
"""
from pathlib import Path
import os
import re
import subprocess
root=Path(__file__).resolve().parents[2]
base=root/'firmware/frame_film_ark/components'
def read(p): return (base/p).read_text(encoding='utf8')
def clean(s):return re.sub(r'^#include.*$', '', s,flags=re.M)
def func(s,n):
 m=re.search(r'^(?:static )?(?:void|int|bool|uint8_t) '+n+r'\([^;]*?\)\n\{',s,re.M);assert m,n
 level=0
 for i in range(s.index('{',m.start()),len(s)):
  if s[i]=='{':level+=1
  if s[i]=='}':
   level-=1
   if level==0:return s[m.start():i+1]
preamble=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define sys_logw(...) ((void)0)
#define sys_logi(...) test_log(__VA_ARGS__)
static void test_log(const char *tag,const char *fmt,...){(void)tag;(void)fmt;}
#define APP_MANAGER_TAG "host"
typedef enum {INPUT_PRESS_NONE,INPUT_PRESS_SHORT,INPUT_PRESS_LONG,INPUT_PRESS_UP,INPUT_PRESS_DOWN} input_press_type_t;
typedef void app_ui_ops_t;
static char film_dir[64]="/tmp/ff-open-XXXXXX";
#define FILM_DIR film_dir
#define FILM_FILE_EXT ".film"
#define FILM_HEADER_SIZE 32
#define FILE_ID_NONE 0xffffffffu
#define SERVICE_PARAM_APP_DATA_MAX 128
#define BLE_FILM_TRANS_CH_APP_IMAGE_PARAM 0x45
#define BLE_FILM_TRANS_CH_CTRL_APP_SWITCH 0x4b
struct {struct {uint8_t sleep_mode;}sleep;}g_service_param;
'''
decls=r'''
static app_id_t m_current_app=APP_ID_MENU,m_last_guest_app;
static uint8_t m_app_running=1,m_boot_page,m_sleep_page,m_boot_ui_shown,m_boot_evt_pending;
static uint32_t m_tick_acc_ms;
static const app_entry_t *m_app_registry[APP_ID_MAX];
static bool boot_pending,not_ready;
static uint32_t shown[20],draws,loads,dir_changes;
static uint8_t response[2];
static char active_dir[64]="/tmp/other";
typedef struct {char filename[256];uint32_t file_size;}file_item_t;
static file_item_t files[6]={{"0.film",32},{"old.film",32},{"2.film",32},{"3.film",32},{"4.film",32},{"target.film",32}};
static struct {file_item_t *file_list;uint32_t file_count,current_file_id;}m_file_state={files,6,1};
static uint8_t m_list_ready=1;
static void file_list_lock(void){}
static void file_list_unlock(void){}
static void app_state_save(void);
static uint32_t service_file_get_count(void){return m_file_state.file_count;}
static uint32_t service_file_get_current_id(void){return m_file_state.current_file_id;}
static int service_file_find_id(const char*,uint32_t*);
static void service_film_display(uint32_t id){assert(draws<20);shown[draws++]=id;}
static app_id_t app_manager_get_current(void){return m_current_app;}
static bool app_manager_boot_advance_pending(void){return boot_pending;}
'''
stubs=r'''
static app_image_state_t stored;
static void app_state_save(void){if(m_current_app==APP_ID_IMAGE)stored=m_image;}
static int app_is_registered(app_id_t id){return id<APP_ID_MAX && m_app_registry[id];}
static int app_is_ui_layer(app_id_t id){return m_app_registry[id]->layer==APP_LAYER_UI;}
static void ui_core_resume(void){}
static void ui_core_page_exit(void){}
static void app_stop_current(void){}
static void app_menu_notice(const char*s){(void)s;}
static uint8_t service_file_is_list_ready(void){return m_list_ready;}
static const char*service_file_get_dir(void){return active_dir;}
static uint32_t service_file_set_dir_sync(const char*dir){
 if(strcmp(active_dir,dir)){dir_changes++;snprintf(active_dir,sizeof(active_dir),"%s",dir);m_file_state.current_file_id=0;}
 m_list_ready=!not_ready;return service_file_get_count();
}
static void app_state_load(void){m_image=stored;loads++;}
static void app_start_current(void){g_app_image_entry.on_enter();m_app_running=1;}
static void service_param_app_current_set(uint8_t id){(void)id;}
static void app_manager_notify_boot(void){app_event_t e={.type=APP_EVT_BOOT};g_app_image_entry.on_event(&e);}
static void service_ble_send_resp(uint8_t ch,const uint8_t*d,uint8_t n){assert(ch==0x4b && n==2);memcpy(response,d,2);}
'''
tests=r'''
static void reset(void){
 stored=(app_image_state_t){.play_mode=0,.auto_interval=10,.file_id=1};m_image=stored;
 m_current_app=APP_ID_MENU;m_app_running=1;
 m_boot_page=m_sleep_page=m_boot_ui_shown=m_boot_evt_pending=0;
 m_open_file_id=FILE_ID_NONE;m_skip_boot_advance=false;m_first_draw_pending=false;
 boot_pending=not_ready=false;m_file_state.file_count=6;m_file_state.current_file_id=1;m_list_ready=1;
 snprintf(active_dir,sizeof(active_dir),"/tmp/other");draws=loads=dir_changes=0;
 memset(m_app_registry,0,sizeof(m_app_registry));m_app_registry[0]=&g_app_image_entry;
}
static void list(uint8_t saved){app_event_t e={.type=APP_EVT_SYS,.cmd=SYS_EVT_FILE_LIST,.len=5};e.payload[4]=saved;g_app_image_entry.on_event(&e);}
static void open_name(uint8_t id,const char*n){
 app_event_t e={.type=APP_EVT_SYS,.cmd=SYS_EVT_BLE_APP_CMD};e.payload[0]=0x4b;e.payload[1]=id;
 e.len=strlen(n)+3;memcpy(e.payload+2,n,strlen(n)+1);request(&e);
}
int main(void){
 assert(mkdtemp(film_dir));char path[128];snprintf(path,sizeof(path),"%s/target.film",film_dir);
 FILE*f=fopen(path,"wb");assert(f);char zero[32]={0};assert(fwrite(zero,1,32,f)==32);fclose(f);
 reset();open_name(0,"target.film");
 assert(response[1]==0 && m_current_app==0 && loads==1 && draws==1 && shown[0]==5 && stored.file_id==5);
 list(0);list(0);assert(draws==1);
 reset();app_do_switch(0);assert(draws==1 && shown[0]==1);list(0);assert(draws==1);
 open_name(0,"target.film");assert(draws==2 && shown[1]==5 && loads==1);
 reset();open_name(0,"missing.film");
 assert(response[1]==2 && dir_changes==0 && draws==0 && m_current_app==APP_ID_MENU && stored.file_id==1 && m_file_state.current_file_id==1);
 reset();open_name(APP_ID_CLOCK,"target.film");assert(response[1]==1 && dir_changes==0);
 app_event_t bad={.type=APP_EVT_SYS,.cmd=SYS_EVT_BLE_APP_CMD,.len=5,.payload={0x4b,0,'a','b','c'}};
 request(&bad);assert(response[1]==1 && dir_changes==0);
 bad.payload[4]=bad.payload[2]=0;request(&bad);assert(response[1]==1 && draws==0);
 reset();m_sleep_page=1;open_name(0,"target.film");assert(response[1]==3 && m_open_file_id==FILE_ID_NONE);
 m_sleep_page=0;app_do_switch(0);assert(draws==1 && shown[0]==1);
 reset();m_boot_page=1;open_name(0,"target.film");assert(response[1]==3 && draws==0);
 reset();not_ready=true;open_name(0,"target.film");assert(response[1]==3 && m_current_app==APP_ID_MENU && stored.file_id==1 && m_open_file_id==FILE_ID_NONE);
 reset();m_current_app=0;m_file_state.file_count=0;g_app_image_entry.on_enter();assert(draws==0);
 m_file_state.file_count=6;list(0);list(0);assert(draws==1 && shown[0]==1);
 reset();m_current_app=0;g_app_image_entry.on_enter();list(1);assert(draws==1);
 m_file_state.current_file_id=5;app_event_t saved={.type=APP_EVT_SYS,.cmd=SYS_EVT_FILE_SAVED,.len=1,.payload={1}};
 g_app_image_entry.on_event(&saved);assert(draws==2 && shown[1]==5);
 reset();m_current_app=0;m_image.play_mode=1;g_service_param.sleep.sleep_mode=1;boot_pending=true;
 g_app_image_entry.on_enter();list(0);assert(draws==0);
 app_event_t boot={.type=APP_EVT_BOOT};g_app_image_entry.on_event(&boot);list(0);assert(draws==1 && shown[0]==2);
 unlink(path);rmdir(film_dir);puts("PASS: target/legacy/invalid/busy/late-list/duplicate-list/saved/boot");return 0;
}
'''
s=preamble+clean(read('film_app/inc/app_interface.h'))+clean(read('film_sys/inc/sys_event.h'))+clean(read('film_app/apps/image/app_image.h'))+decls+clean(read('film_app/apps/image/app_image.c'))+stubs
for name in ['service_file_has_film','service_file_find_id']:s+=func(read('film_service/src/service_file.c'),name)
manager=read('film_app/core/app_manager.c')
for name in ['app_do_switch_target','app_do_switch']:s+=func(manager,name)
handle=func(manager,'app_handle_event')
a=handle.index('    if(e->type == APP_EVT_SYS && e->cmd == SYS_EVT_BLE_APP_CMD &&')
b=handle.index('    /* \u5165\u7761\u540e',a)
s+='\nstatic void request(const app_event_t*e){\n'+handle[a:b]+'}\n'+tests
out=root/'.output/atomic_image_open_host.c'
out.parent.mkdir(exist_ok=True)
out.write_text(s,encoding='utf8')
if os.name == 'nt':
    win_path = out.as_posix()
    compiler = ['wsl', '--exec', 'gcc']
    c_path = '/mnt/' + win_path[0].lower() + win_path[2:]
    runner = ['wsl', '--exec', '/tmp/framefilm_atomic_image_open_test']
else:
    compiler = ['gcc']
    c_path = str(out)
    runner = ['/tmp/framefilm_atomic_image_open_test']
subprocess.run(compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', c_path,
                          '-o', '/tmp/framefilm_atomic_image_open_test'], check=True)
subprocess.run(runner, check=True)
