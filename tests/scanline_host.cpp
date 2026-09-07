// SPDX-License-Identifier: MIT
//
// Host-only C-linkage wrapper around scanline.hpp so ctypes (test_scanline_c.py)
// can drive the kernel and compare it byte-for-byte with tests/reference.py.
// Not built into firmware; the spidisplay module binds the same selector.
//
//   c++ -shared -fPIC -O2 -std=c++17 -I driver -o scanline.so tests/scanline_host.cpp

#include <algorithm>
#include <cstdint>

// No core1 here, so ask emit_rows() to run the halves in sequence instead. Without
// this the firmware's single-core path is one call and the split that a board with
// a core1 worker takes would go unchecked.
#define SPIDISPLAY_SPLIT_SERIAL 1

#include "column_cache.hpp"
#include "scanline.hpp"

using namespace spidisplay;

extern "C" void scanline_convert(uint8_t *out, const uint8_t *src,
                                 int src_w, int src_h, int src_stride,
                                 int dst_w, int dst_h,
                                 int rotation, int mirror, int dbl,
                                 uint32_t bg, int fmt,
                                 int centred_x, int off_x, int centred_y, int off_y,
                                 int tile_x, int tile_y,
                                 const uint8_t *palette, int palette_len) {
    Transform t = {rotation, mirror != 0};
    bool indexed = palette != nullptr;
    Descriptor d = make_descriptor(src, src_w, src_h, dst_w, dst_h,
                                   packed_row_bytes(fmt, dst_w), t, dbl != 0,
                                   centred_x != 0, off_x, centred_y != 0, off_y,
                                   tile_x != 0, tile_y != 0,
                                   tile_x == 2, tile_y == 2, bg,
                                   src_stride,
                                   indexed ? Indexed8::bytes : RGBA8888::bytes);
    // Through the same table preparation the firmware's prepare() uses, so the
    // clamp, the zero-filled tail and the composite are all under test.
    uint8_t table[PALETTE_BYTES];
    if (indexed) {
        prepare_palette(table, palette, (size_t)palette_len, d.bg_r, d.bg_g, d.bg_b);
        d.palette = table;
    }
    ConvertFn convert = select_convert(fmt, indexed);
    convert(d, out, 0, dst_h);
}

// Banded conversion through the column cache, matching the firmware's band loop
// (spidisplay.cpp) minus the SPI/DMA. cache_capacity is in bytes and models the
// per-display claim (cache_columns * dst_w * 4 in firmware); passing less than
// a window needs exercises the same per-window fallback.
//
// split is the firmware's dual_convert setting: on, each row range the cache
// emits is halved, which on device sends the second half to core1 and here runs
// both halves in sequence. Either way the output must be identical.
//
// slow is whether the source is reached over XIP, which decides both whether the
// cache engages at all and whether rows read straight from the source may be
// split. Passing it covers the split on the cached descriptor and on the source's
// own, an SRAM canvas being the second.
static constexpr int MAX_CACHE_BYTES = 320 * 24 * 4;
static uint32_t cache_storage[MAX_CACHE_BYTES / 4];

extern "C" void scanline_convert_cached(uint8_t *out, const uint8_t *src,
                                        int src_w, int src_h, int src_stride,
                                        int dst_w, int dst_h,
                                        int rotation, int mirror, int dbl,
                                        uint32_t bg, int fmt,
                                        int centred_x, int off_x, int centred_y, int off_y,
                                        int tile_x, int tile_y,
                                        const uint8_t *palette, int palette_len,
                                        int band_lines, int cache_columns, int cache_capacity,
                                        int split, int slow) {
    dual_convert = split != 0;
    Transform t = {rotation, mirror != 0};
    bool indexed = palette != nullptr;
    Descriptor d = make_descriptor(src, src_w, src_h, dst_w, dst_h,
                                   packed_row_bytes(fmt, dst_w), t, dbl != 0,
                                   centred_x != 0, off_x, centred_y != 0, off_y,
                                   tile_x != 0, tile_y != 0,
                                   tile_x == 2, tile_y == 2, bg,
                                   src_stride,
                                   indexed ? Indexed8::bytes : RGBA8888::bytes);
    uint8_t table[PALETTE_BYTES];
    if (indexed) {
        prepare_palette(table, palette, (size_t)palette_len, d.bg_r, d.bg_g, d.bg_b);
        d.palette = table;
    }
    ConvertFn convert = select_convert(fmt, indexed);

    ColumnCache cache(cache_storage, std::min(cache_capacity, MAX_CACHE_BYTES),
                      cache_columns);
    cache.begin(d, convert, slow != 0);
    for (int row = 0; row < dst_h; row += band_lines) {
        int rows = std::min(band_lines, dst_h - row);
        cache.convert(out + (size_t)row * d.dst_row_bytes, row, rows);
    }
}
