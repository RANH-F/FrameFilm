#include "service_ble_name.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_mac.h"
#include "service_param.h"
#include "sys_cfg.h"
#include "sys_log.h"

#define BLE_NAME_PREFIX SYS_DEVICE_NAME "-"
#define BLE_NAME_PREFIX_LEN (sizeof(BLE_NAME_PREFIX) - 1)

/* 前缀 + 后缀必须正好等于广播名上限（不含结尾 NUL），改任一处都要同步 */
_Static_assert(BLE_NAME_PREFIX_LEN + SERVICE_BLE_NAME_SUFFIX_MAX == BLE_DEVICE_NAME_MAX_BYTES,
               "BLE name prefix/suffix size mismatch");

static char m_configured_name[BLE_DEVICE_NAME_MAX_BYTES + 1];

static bool suffix_valid(const uint8_t *bytes, size_t len)
{
    if(bytes == NULL || len <= 1 || len > SERVICE_BLE_NAME_SUFFIX_MAX + 1 || bytes[len - 1] != 0)
        return false;

    /* Validate UTF-8 scalar values and reject C0/C1 control characters. */
    for(size_t i = 0; i + 1 < len;)
    {
        uint32_t cp;
        uint8_t first = bytes[i++];
        size_t more;
        if(first < 0x80) { cp = first; more = 0; }
        else if(first >= 0xC2 && first <= 0xDF) { cp = first & 0x1F; more = 1; }
        else if(first >= 0xE0 && first <= 0xEF) { cp = first & 0x0F; more = 2; }
        else if(first >= 0xF0 && first <= 0xF4) { cp = first & 0x07; more = 3; }
        else return false;

        if(i + more > len - 1) return false;
        for(size_t j = 0; j < more; j++)
        {
            if((bytes[i] & 0xC0) != 0x80) return false;
            cp = (cp << 6) | (bytes[i++] & 0x3F);
        }
        if((more == 1 && cp < 0x80) || (more == 2 && cp < 0x800) ||
           (more == 3 && cp < 0x10000) || cp > 0x10FFFF ||
           (cp >= 0xD800 && cp <= 0xDFFF) || cp < 0x20 ||
           (cp >= 0x7F && cp <= 0x9F)) return false;
    }
    return true;
}

/* 返回有效后缀；未配置（空串）或存值非法时用蓝牙 MAC 派生并写回参数，作为默认名。 */
static const char *suffix_or_default(void)
{
    char *suffix = g_service_param.ble.ble_name;
    size_t stored = strnlen(suffix, sizeof(g_service_param.ble.ble_name)) + 1;
    if(suffix_valid((const uint8_t *)suffix, stored))
    {
        return suffix;
    }

    if(suffix[0] != '\0')
    {
        sys_logw("BLE_NAME", "stored name invalid, fallback to MAC");
    }

    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_BT);
    snprintf(suffix, sizeof(g_service_param.ble.ble_name), "%02X%02X%02X%02X%02X%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return suffix;
}

void service_ble_name_init(void)
{
    snprintf(m_configured_name, sizeof(m_configured_name), "%s%s",
             BLE_NAME_PREFIX, suffix_or_default());
}

const char *service_ble_name_get(void)
{
    return m_configured_name;
}

uint8_t service_ble_name_set(const uint8_t *suffix, size_t payload_len)
{
    if(!suffix_valid(suffix, payload_len)) return 1;

    memcpy(g_service_param.ble.ble_name, suffix, payload_len);
    g_service_param.ble.ble_name[payload_len - 1] = '\0'; /* suffix_valid 已保证末字节为 NUL */
    service_param_save();

    snprintf(m_configured_name, sizeof(m_configured_name), "%s%s",
             BLE_NAME_PREFIX, g_service_param.ble.ble_name);
    return 0;
}
