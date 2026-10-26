"""Check real Ark parameter routing/load C functions; no device IO."""
from pathlib import Path
import os,re,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
text=(ROOT/'firmware/frame_film_ark/components/film_app/core/app_manager.c').read_text(encoding='utf-8')
def function(name):
    m=re.search(r'^(?:static )?(?:int|uint8_t) '+name+r'\([^;]*?\)\n\{',text,re.M)
    assert m,name
    depth=0
    for pos in range(text.index('{',m.start()),len(text)):
        if text[pos]=='{':depth+=1
        elif text[pos]=='}':
            depth-=1
            if not depth:return text[m.start():pos+1]+'\n'
    raise AssertionError(name)
source=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define APP_ID_MAX 3
#define APP_PARAM_GET_BUF_MAX 60
typedef struct {
 int id; uint8_t param_ch; void *state; uint16_t state_size; uint8_t state_ver;
 const void *state_default;
 void (*on_param_set)(const uint8_t*,uint8_t);
 uint8_t (*on_param_get)(uint8_t*,uint8_t);
 void (*on_enter)(void);
} app_entry_t;
typedef struct {uint16_t frame_ms;uint8_t mode;} state_t;
static state_t ram[APP_ID_MAX],saved[APP_ID_MAX];
static const state_t defaults={100,1};
static const app_entry_t *m_app_registry[APP_ID_MAX],*m_param_owner[256];
static uint8_t m_state_loaded[APP_ID_MAX];
static unsigned loads,saves,enters,responses;
static int missing,selected;
static uint8_t response_ch,response_len,response[60];
static int service_param_app_load(uint8_t id,void*out,uint16_t size,uint8_t ver){
 assert(size==sizeof(state_t)&&ver==1);loads++;
 if(missing)return -1;
 memcpy(out,&saved[id],size);return 0;
}
static int service_param_app_save(uint8_t id,const void*data,uint16_t size,uint8_t ver){
 assert(size==sizeof(state_t)&&ver==1);saves++;memcpy(&saved[id],data,size);return 0;
}
static void service_ble_send_resp(uint8_t ch,const uint8_t*data,uint8_t size){
 responses++;response_ch=ch;response_len=size;memcpy(response,data,size);
}
static void enter(void){enters++;}
static void set(const uint8_t*data,uint8_t size){assert(size==1);ram[selected].mode=data[0];}
static uint8_t get(uint8_t*out,uint8_t max){
 assert(max>=3);out[0]=ram[selected].frame_ms>>8;out[1]=ram[selected].frame_ms;out[2]=ram[selected].mode;return 3;
}
static int app_state_save_of(const app_entry_t*);
static int app_state_load_of(const app_entry_t*);
uint8_t app_manager_param_get(uint8_t,uint8_t*,uint8_t);
'''
for name in ('app_state_save_of','app_state_load_of','app_manager_param_get','app_param_ch_route'):
    source+=function(name)
source+=r'''
static void reset(void){
 memset(ram,0,sizeof(ram));memset(m_state_loaded,0,sizeof(m_state_loaded));
 for(int i=0;i<APP_ID_MAX;i++)saved[i]=(state_t){200,7};
 loads=saves=enters=responses=0;missing=0;
}
int main(void){
 app_entry_t entries[APP_ID_MAX];
 for(int i=0;i<APP_ID_MAX;i++){
  entries[i]=(app_entry_t){.id=i,.param_ch=(uint8_t)(0x45+i*2),
    .state=&ram[i],.state_size=sizeof(state_t),.state_ver=1,
    .state_default=&defaults,.on_param_set=set,.on_param_get=get,.on_enter=enter};
  m_app_registry[i]=&entries[i];m_param_owner[entries[i].param_ch]=&entries[i];
  m_param_owner[entries[i].param_ch+1]=&entries[i];
 }
 for(selected=0;selected<APP_ID_MAX;selected++){
  uint8_t ch=entries[selected].param_ch,mode=9;
  reset();assert(app_param_ch_route(ch+1,NULL,0)==1);
  assert(response_ch==ch+1&&response_len==3&&response[0]==0&&response[1]==200&&response[2]==7);
  assert(loads==1&&saves==0&&enters==0&&m_state_loaded[selected]);
  assert(app_param_ch_route(ch+1,NULL,0)==1);
  assert(loads==1&&saves==0&&enters==0&&responses==2);
  reset();assert(app_param_ch_route(ch,&mode,1)==1);
  assert(loads==1&&saves==1&&enters==0&&responses==0);
  assert(saved[selected].frame_ms==200&&saved[selected].mode==9);
  mode=8;assert(app_param_ch_route(ch,&mode,1)==1);
  assert(loads==1&&saves==2&&saved[selected].frame_ms==200&&saved[selected].mode==8);
  assert(app_param_ch_route(ch+1,NULL,0)==1&&response[1]==200&&response[2]==8);
  reset();missing=1;assert(app_param_ch_route(ch+1,NULL,0)==1);
  assert(response[1]==100&&response[2]==1&&loads==1&&saves==0);
  assert(app_param_ch_route(ch+1,NULL,0)==1&&loads==1&&saves==0&&enters==0);
 }
 assert(app_param_ch_route(0xff,NULL,0)==0);
 puts("PASS: cold/repeated GET 0x46/0x48/0x4A, no save/enter, SET preserved, defaults");
 return 0;
}
'''
out=ROOT/'.output/ark/param-get-20261026'
out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='host-',dir=out) as tmp:
    c=Path(tmp)/'check.c';c.write_text(source,encoding='utf-8')
    if os.name=='nt':
        path=c.as_posix();c_path='/mnt/'+path[0].lower()+path[2:]
        binary='/tmp/framefilm-param-'+Path(tmp).name
        compiler=['wsl','--exec','gcc'];runner=['wsl','--exec',binary]
    else:
        c_path=str(c);binary=str(Path(tmp)/'check');compiler=['gcc'];runner=[binary]
    try:
        subprocess.run(compiler+['-std=c11','-Wall','-Wextra','-Werror',c_path,'-o',binary],check=True)
        subprocess.run(runner,check=True)
    finally:
        if os.name=='nt':subprocess.run(['wsl','--exec','rm','-f',binary],check=False)
