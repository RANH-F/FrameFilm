/* Frozen pre-batching implementation from 7737671. Used as the byte-stream oracle. */

static uint8_t epd_spectra_reverse_bits(uint8_t x)
{
    x = (uint8_t)((x >> 4) | (x << 4));
    x = (uint8_t)(((x >> 2) & 0x33) | ((x << 2) & 0xCC));
    return (uint8_t)(((x >> 1) & 0x55) | ((x << 1) & 0xAA));
}

static uint8_t epd_spectra_mono_code_byte(uint8_t bitmap_byte)
{
    uint8_t v = epd_spectra_reverse_bits(bitmap_byte);

    if (MONO_CODE_BIT_WHITE)
    {
        v = (uint8_t)~v;
    }

    return v;
}

static void epd_spectra_mono_write(const uint8_t *mono_bitmap)
{
    EPD_PROFILE_STAGE_BEGIN(RAM);
    uint8_t line[EPD_INPUT_LINE];

    EPD_W21_WriteCMD(DTM1);   // 0x10
    epd_wait_busy(BUSY_TIMEOUT_INIT_MS);
    for (int row = 0; row < EPD_HEIGHT; row++)
    {
        const uint8_t *src = mono_bitmap ? (mono_bitmap + row * EPD_MONO_LINE) : NULL;
        uint8_t *prev = m_mono_prev + row * EPD_MONO_LINE;
        for (int x = 0; x < EPD_MONO_LINE; x++)
        {
            uint8_t old = prev[x];
            uint8_t next = epd_spectra_mono_code_byte(src ? src[x] : 0x00);
            prev[x] = next;   // 更新上一帧（码位域）
            for (int j = 0; j < 4; j++)
            {
                line[x * 4 + j] = (uint8_t)(((old << 5) & 0x20) | ((next << 4) & 0x10)
                                            | (old & 2) | ((next >> 1) & 1));
                old >>= 2;
                next >>= 2;
            }
        }
        EPD_W21_WriteDATA_Bulk(line, EPD_INPUT_LINE);
    }
    EPD_PROFILE_STAGE_END(RAM);
}
