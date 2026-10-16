#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

/* Compile the production migration with a minimal NVS implementation. */
#include "../../components/film_service/src/service_param.c"

/* Recorded v5 layout: pack(4), sys at 2, sleep at 6, network at 10,
 * ble_enable at 492, and two trailing padding bytes. */
_Static_assert(offsetof(service_param_v5_t, sys) == 2, "v5 sys offset");
_Static_assert(offsetof(service_param_v5_t, sleep) == 6, "v5 sleep offset");
_Static_assert(offsetof(service_param_v5_t, network) == 10, "v5 network offset");
_Static_assert(offsetof(service_param_v5_t, ble_enable) == 492, "v5 BLE offset");
_Static_assert(sizeof(service_param_v5_t) == 494, "v5 blob size");

static uint8_t persisted[sizeof(ServiceParam_Def_t) + 8];
static size_t persisted_size;
static uint8_t staged[sizeof(ServiceParam_Def_t)];
static size_t staged_size;
static char old_name[32];
static int commits;
static int fail_commit;
static jmp_buf fatal_jump;

void test_esp_error_check(int err)
{
    if(err != ESP_OK) longjmp(fatal_jump, 1);
}

esp_err_t nvs_flash_init(void) { return ESP_OK; }
esp_err_t nvs_flash_erase(void) { return ESP_OK; }
esp_err_t nvs_open(const char *ns, int mode, nvs_handle_t *handle)
{
    (void)ns; (void)mode;
    *handle = 1;
    return ESP_OK;
}
void nvs_close(nvs_handle_t handle) { (void)handle; }
esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *data, size_t *size)
{
    (void)handle; (void)key;
    if(!persisted_size) return ESP_ERR_NVS_NOT_FOUND;
    if(data == NULL) { *size = persisted_size; return ESP_OK; }
    if(*size < persisted_size) { *size = persisted_size; return ESP_ERR_NVS_INVALID_LENGTH; }
    memcpy(data, persisted, persisted_size);
    *size = persisted_size;
    return ESP_OK;
}
esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key, const void *data, size_t size)
{
    (void)handle; (void)key;
    assert(size <= sizeof(staged));
    memcpy(staged, data, size);
    staged_size = size;
    return ESP_OK;
}
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *data, size_t *size)
{
    (void)handle;
    assert(strcmp(key, "ble_name") == 0);
    if(!old_name[0]) return ESP_ERR_NVS_NOT_FOUND;
    size_t len = strlen(old_name) + 1;
    if(*size < len) { *size = len; return ESP_ERR_NVS_INVALID_LENGTH; }
    memcpy(data, old_name, len);
    *size = len;
    return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t handle)
{
    (void)handle;
    ++commits;
    if(fail_commit) return 99;
    if(staged_size) { memcpy(persisted, staged, staged_size); persisted_size = staged_size; }
    staged_size = 0;
    return ESP_OK;
}
esp_err_t nvs_erase_key(nvs_handle_t handle, const char *key)
{ (void)handle; (void)key; return ESP_ERR_NVS_NOT_FOUND; }
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value)
{ (void)handle; (void)key; (void)value; return ESP_ERR_NVS_NOT_FOUND; }
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value)
{ (void)handle; (void)key; (void)value; return ESP_OK; }
int esp_read_mac(uint8_t mac[6], int type)
{ (void)mac; (void)type; assert(0 && "fixture supplies device ID"); return ESP_OK; }

static void clear_case(void)
{
    memset(persisted, 0, sizeof(persisted));
    persisted_size = staged_size = 0;
    memset(old_name, 0, sizeof(old_name));
    memset(&g_service_param, 0, sizeof(g_service_param));
    commits = fail_commit = 0;
}

static void seed_v5(void)
{
    service_param_v5_t old = {0};
    old.param_ver = 5;
    old.sys.factory_flag = SERVICE_FACTORY_DEFAULT_FLAG;
    old.sys.led_mode = 2;
    old.sys.tz_min = 480;
    old.sleep.sleep_mode = 0;
    old.sleep.sleep_auto = 1;
    old.sleep.sleep_time = 123;
    old.network.wifi_enable = 1;
    old.network.film_heartbeat_interval = 37;
    strcpy(old.network.wifi_ssid, "office-wifi");
    strcpy(old.network.wifi_password, "secret-pass");
    strcpy(old.network.film_api_url, "https://example.test/film");
    strcpy(old.network.film_heartbeat_url, "https://example.test/ping");
    strcpy(old.network.film_device_id, "existing-device");
    strcpy(old.network.film_token, "existing-token");
    old.ble_enable = 0;
    memcpy(persisted, &old, sizeof(old));
    persisted_size = sizeof(old);
}

static void assert_v5_fields_preserved(void)
{
    assert(g_service_param.param_ver == SERVICE_PARAM_VER);
    assert(g_service_param.sys.factory_flag == SERVICE_FACTORY_DEFAULT_FLAG);
    assert(g_service_param.sys.led_mode == 2);
    assert(g_service_param.sys.tz_min == 480);
    assert(g_service_param.sleep.sleep_mode == 0);
    assert(g_service_param.sleep.sleep_auto == 1);
    assert(g_service_param.sleep.sleep_time == 123);
    assert(g_service_param.network.wifi_enable == 1);
    assert(g_service_param.network.film_heartbeat_interval == 37);
    assert(strcmp(g_service_param.network.wifi_ssid, "office-wifi") == 0);
    assert(strcmp(g_service_param.network.wifi_password, "secret-pass") == 0);
    assert(strcmp(g_service_param.network.film_api_url, "https://example.test/film") == 0);
    assert(strcmp(g_service_param.network.film_heartbeat_url, "https://example.test/ping") == 0);
    assert(strcmp(g_service_param.network.film_device_id, "existing-device") == 0);
    assert(strcmp(g_service_param.network.film_token, "existing-token") == 0);
    assert(g_service_param.ble.ble_enable == 0);
}

int main(void)
{
    clear_case();
    seed_v5();
    strcpy(old_name, "Ark-custom");
    service_param_init();
    assert_v5_fields_preserved();
    assert(strcmp(g_service_param.ble.ble_name, "Ark-custom") == 0);
    assert(persisted_size == sizeof(ServiceParam_Def_t));
    assert(commits == 1);

    /* Once v6 is stored, a normal load does not migrate or overwrite it. */
    memset(&g_service_param, 0, sizeof(g_service_param));
    commits = 0;
    service_param_init();
    assert_v5_fields_preserved();
    assert(strcmp(g_service_param.ble.ble_name, "Ark-custom") == 0);
    assert(commits == 0);

    clear_case();
    seed_v5();
    service_param_init();
    assert_v5_fields_preserved();
    assert(g_service_param.ble.ble_name[0] == '\0');

    clear_case();
    seed_v5();
    fail_commit = 1;
    assert(setjmp(fatal_jump) == 0 ? (service_param_init(), 0) : 1);
    assert(persisted_size == sizeof(service_param_v5_t));
    assert(persisted[0] == 5);

    clear_case();
    seed_v5();
    persisted_size -= 1; /* Unexpected old blob length follows the default path. */
    nvs_init();
    assert(g_service_param.param_ver == SERVICE_PARAM_VER);
    assert(g_service_param.network.wifi_enable == 0);
    assert(commits == 1);

    clear_case();
    seed_v5();
    persisted[0] = 4; /* Known length with unknown version also defaults. */
    nvs_init();
    assert(g_service_param.network.wifi_enable == 0);
    assert(commits == 1);

    puts("host_param: v5 migration, name, v6 load, failed commit, fallback OK");
    return 0;
}
