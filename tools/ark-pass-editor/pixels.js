/* SPDX-License-Identifier: GPL-3.0-or-later */
(function (root) {
  'use strict';
  const palette = [[0, 0, 0], [255, 255, 255], [255, 255, 0], [255, 0, 0], [0, 0, 255], [41, 204, 20]];
  const codes = [0, 1, 2, 3, 5, 6];
  const bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  function encode(rgba, mode, hasAvatar) {
    if (rgba.length !== 440 * 608 * 4 || !['mono', 'grayscale', 'color'].includes(mode)) throw new Error('通行证像素或头像模式无效。');
    const color = mode === 'color';
    const bin = new Uint8Array(color ? 133776 : 33456);
    bin.set([70, 70, 85, 73, color ? 2 : 1, color ? 2 : 1, 184, 1, 96, 2]);
    for (let i = 0; i < 440 * 608; i++) {
      const k = i * 4, x = i % 440, y = Math.floor(i / 440);
      const inside = hasAvatar && x >= 20 && x < 148 && y >= 143 && y < 303;
      const luminance = .299 * rgba[k] + .587 * rgba[k + 1] + .114 * rgba[k + 2];
      let index = luminance < 160 ? 0 : 1;
      if (inside && color) {
        let distance = Infinity;
        palette.forEach((rgb, p) => {
          const r = rgba[k] - rgb[0], g = rgba[k + 1] - rgb[1], b = rgba[k + 2] - rgb[2];
          const d = .299 * r * r + .587 * g * g + .114 * b * b;
          if (d < distance) { distance = d; index = p; }
        });
      } else if (inside && mode === 'grayscale') {
        const threshold = (bayer[((y - 143) & 3) * 4 + ((x - 20) & 3)] + .5) * 255 / 16;
        index = luminance < threshold ? 0 : 1;
      }
      rgba[k] = palette[index][0]; rgba[k + 1] = palette[index][1]; rgba[k + 2] = palette[index][2]; rgba[k + 3] = 255;
      if (color) bin[16 + (i >> 1)] |= codes[index] << ((i & 1) ? 0 : 4);
      else if (index === 0) bin[16 + (i >> 3)] |= 0x80 >> (i & 7);
    }
    return bin;
  }
  const api = { encode };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PassportPixels = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
