#include "app_typography.h"

/* LVGL owns the built-in Unscii8 font; only this private copy has a fallback. */
static lv_font_t m_unscii8_with_fallback;
static uint8_t m_font_ready;

const lv_font_t *app_font_small_text(const char *text)
{
    if(app_language_get() != APP_LANGUAGE_EN) return &ui_font_14;
    if(text == NULL) return &lv_font_unscii_8;

    uint8_t has_symbol = 0;
    for(const unsigned char *p = (const unsigned char *)text; *p != 0; ++p)
    {
        if(*p >= 0xE3) return &ui_font_14; /* CJK and its punctuation in UTF-8. */
        if(*p >= 0x80) has_symbol = 1;
    }
    if(!has_symbol) return &lv_font_unscii_8;

    if(!m_font_ready)
    {
        m_unscii8_with_fallback = lv_font_unscii_8;
        m_unscii8_with_fallback.fallback = &ui_font_14;
        m_font_ready = 1;
    }
    return &m_unscii8_with_fallback;
}
