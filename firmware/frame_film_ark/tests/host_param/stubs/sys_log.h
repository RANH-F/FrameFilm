#pragma once
#define SYS_M_NVS_NAMESPACE "FRAMEFILM_NVS"
#define SYS_M_NVS_KEY_NAME "FILMKEY"
#define SYS_M_NVS_APP_NAMESPACE "FRAMEFILM_APP"
#define SYS_M_NVS_APP_KEY_PREFIX "app"
#define SYS_M_NVS_APP_KEY_CURRENT "current"
#define sys_loge(...) ((void)0)
#define sys_logw(...) ((void)0)
#define sys_logi(...) ((void)0)
#define SYS_ERROR_CHECK(x) ((void)(x))
#define ESP_ERROR_CHECK(x) test_esp_error_check(x)
void test_esp_error_check(int err);
