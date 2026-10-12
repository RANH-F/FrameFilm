#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "service_ble_name.h"
#include "service_param.h"
#include "esp_mac.h"

/* 参数层桩：g_service_param 即参数 blob，service_param_save() 记录最近一次落盘结果 */
ServiceParam_Def_t g_service_param;
static char saved_suffix[SERVICE_BLE_NAME_SUFFIX_MAX + 1];

void service_param_save(void)
{
    memcpy(saved_suffix, g_service_param.ble.ble_name, sizeof(saved_suffix));
}

/* 模拟重启：nvs_init() 把落盘的参数 blob 读回 g_service_param */
static void emulate_reboot(void)
{
    memcpy(g_service_param.ble.ble_name, saved_suffix, sizeof(g_service_param.ble.ble_name));
}

void esp_read_mac(uint8_t mac[6], int type)
{
    const uint8_t address[6] = {0x01, 0x23, 0x45, 0x67, 0x89, 0xAB};
    assert(type == ESP_MAC_BT);
    memcpy(mac, address, sizeof(address));
}

static void expect_invalid(const uint8_t *bytes, size_t length)
{
    char before_name[30];
    char before_suffix[SERVICE_BLE_NAME_SUFFIX_MAX + 1];
    memcpy(before_name, service_ble_name_get(), strlen(service_ble_name_get()) + 1);
    memcpy(before_suffix, g_service_param.ble.ble_name, sizeof(before_suffix));
    assert(service_ble_name_set(bytes, length) == 1);
    assert(strcmp(service_ble_name_get(), before_name) == 0);
    assert(memcmp(g_service_param.ble.ble_name, before_suffix, sizeof(before_suffix)) == 0);
}

int main(void)
{
    /* 参数里未配置后缀 -> 用蓝牙 MAC 派生默认名 */
    service_ble_name_init();
    assert(strcmp(service_ble_name_get(), "FRAMEFILMARK-0123456789AB") == 0);

    /* 16 字节上限后缀：写进参数并落盘，模拟重启后仍生效 */
    const uint8_t max_suffix[] = "1234567890123456";
    assert(service_ble_name_set(max_suffix, sizeof(max_suffix)) == 0);
    assert(strcmp(g_service_param.ble.ble_name, "1234567890123456") == 0);
    assert(strcmp(saved_suffix, "1234567890123456") == 0);
    assert(strcmp(service_ble_name_get(), "FRAMEFILMARK-1234567890123456") == 0);
    emulate_reboot();
    service_ble_name_init();
    assert(strcmp(service_ble_name_get(), "FRAMEFILMARK-1234567890123456") == 0);

    /* UTF-8 后缀 */
    const uint8_t chinese[] = "中文设备";
    assert(service_ble_name_set(chinese, sizeof(chinese)) == 0);
    assert(strcmp(service_ble_name_get(), "FRAMEFILMARK-中文设备") == 0);
    emulate_reboot();
    service_ble_name_init();
    assert(strcmp(service_ble_name_get(), "FRAMEFILMARK-中文设备") == 0);

    /* 非法输入：状态 1，且不改动参数与当前名 */
    const uint8_t empty[] = {0};
    const uint8_t embedded_nul[] = {'A', 0, 'B', 0};
    const uint8_t bad_utf8[] = {0xC3, 0x28, 0};
    const uint8_t c1_control[] = {0xC2, 0x80, 0};
    const uint8_t too_long[] = "12345678901234567";
    expect_invalid(empty, sizeof(empty));
    expect_invalid(embedded_nul, sizeof(embedded_nul));
    expect_invalid(bad_utf8, sizeof(bad_utf8));
    expect_invalid(c1_control, sizeof(c1_control));
    expect_invalid(too_long, sizeof(too_long));

    puts("service_ble_name host test passed");
    return 0;
}
