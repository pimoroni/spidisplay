// SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
//
// SPDX-License-Identifier: MIT
//
// The spidisplay module table, and the module functions belonging to neither type.
// The Python surface is documented in README.md.

#include "py/runtime.h"
#include "py/objarray.h"

#include "spidisplay_bindings.h"

/***** The region the displays may claim *****/

// The linker's SRAM heap range. The rp2 port hands it to the GC unless the board put
// the whole heap in PSRAM, which is the one case that leaves it free.
extern uint8_t __GcHeapStart[];
extern uint8_t __GcHeapEnd[];

// Where the GC owns that range, the region is a block of the heap, held by a root
// pointer so the GC keeps it. The size is the build's default until reserve() sets
// one, kept as a small int beside it.
MP_REGISTER_ROOT_POINTER(uint8_t *spidisplay_heap_region);
MP_REGISTER_ROOT_POINTER(mp_obj_t spidisplay_heap_reserve);

static bool heap_owns_sram(void) {
    uint8_t *heap = MP_STATE_MEM(area).gc_alloc_table_start;
    return heap >= __GcHeapStart && heap < __GcHeapEnd;
}

size_t spidisplay_heap_reserve_bytes(void) {
    if (MP_STATE_VM(spidisplay_heap_reserve) != MP_OBJ_NULL) {
        return (size_t)MP_OBJ_SMALL_INT_VALUE(MP_STATE_VM(spidisplay_heap_reserve));
    }
    return SPIDISPLAY_HEAP_RESERVE_BYTES;
}

static enum spidisplay_region_source region_source = SPIDISPLAY_REGION_FREE_SRAM;

enum spidisplay_region_source spidisplay_sram_source(void) {
    return region_source;
}

void spidisplay_sram_region(uint8_t **start, uint8_t **end) {
    if (!heap_owns_sram()) {
        region_source = SPIDISPLAY_REGION_FREE_SRAM;
        *start = __GcHeapStart;
        *end = __GcHeapEnd;
        return;
    }

    size_t bytes = spidisplay_heap_reserve_bytes();
    if (MP_STATE_VM(spidisplay_heap_region) == NULL) {
        // No raise from here, the driver asking from inside a constructor
        uint8_t *block = m_malloc_maybe(bytes);
        if (block == NULL) {
            region_source = SPIDISPLAY_REGION_HEAP_FAILED;
        } else if (spidisplay_in_psram(block)) {
            // A split heap can hand out PSRAM, which would put the band ring behind
            // the XIP it exists to avoid
            m_free(block);
            region_source = SPIDISPLAY_REGION_HEAP_IN_PSRAM;
        } else {
            MP_STATE_VM(spidisplay_heap_region) = block;
            MP_STATE_VM(spidisplay_heap_reserve) = MP_OBJ_NEW_SMALL_INT(bytes);
            region_source = SPIDISPLAY_REGION_HEAP;
            spidisplay_sram_rebind();
        }
    }

    uint8_t *region = MP_STATE_VM(spidisplay_heap_region);
    *start = region;
    *end = region == NULL ? NULL : region + bytes;
}

// Runs on the module's first import each session, so after a soft reset has wiped the
// heap. A region taken from it last session went with the rest, so it is forgotten and
// the next screen takes another. Root pointers outlive the reset, so they cannot say so.
static mp_obj_t spidisplay___init__(void) {
    MP_STATE_VM(spidisplay_heap_region) = NULL;
    MP_STATE_VM(spidisplay_heap_reserve) = MP_OBJ_NULL;
    spidisplay_sram_rebind();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(spidisplay___init___obj, spidisplay___init__);

// reserve(bytes) sizes the region taken from the heap, before the first screen
static mp_obj_t spidisplay_reserve(mp_obj_t bytes_in) {
    mp_int_t bytes = mp_obj_get_int(bytes_in);
    if (bytes <= 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("the display region needs a positive size"));
    }
    if (!heap_owns_sram()) {
        mp_raise_ValueError(MP_ERROR_TEXT("this firmware's display region is the SRAM its heap leaves free, "
                                          "so its size is not chosen here"));
    }
    if (MP_STATE_VM(spidisplay_heap_region) != NULL) {
        mp_raise_ValueError(MP_ERROR_TEXT("the display region is already in use. "
                                          "Call reserve() before the first screen or buffer()"));
    }
    MP_STATE_VM(spidisplay_heap_reserve) = MP_OBJ_NEW_SMALL_INT(bytes);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(spidisplay_reserve_obj, spidisplay_reserve);

static uint8_t *sram_region_base(void) {
    uint8_t *start;
    uint8_t *end;
    spidisplay_sram_region(&start, &end);
    return start;
}

/***** Module functions *****/
static mp_obj_t spidisplay_buffer(size_t n_args, const mp_obj_t *args) {
    mp_int_t nbytes = mp_obj_get_int(args[0]);
    if (nbytes < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("a buffer needs a positive size"));
    }

    if (n_args > 1) {
        // An offset places the view by hand, so it is bounded but not claimed
        mp_int_t offset = mp_obj_get_int(args[1]);
        size_t headroom = spidisplay_sram_headroom();
        if (offset < 0 || (size_t)offset > headroom
            || (size_t)nbytes > headroom - (size_t)offset) {
            mp_raise_ValueError(MP_ERROR_TEXT("buffer does not fit the SRAM below the display workspaces"));
        }
        return mp_obj_new_memoryview('B' | MP_OBJ_ARRAY_TYPECODE_FLAG_RW,
                                     (size_t)nbytes, sram_region_base() + offset);
    }

    long long claimed = spidisplay_sram_claim_low((size_t)nbytes);
    if (claimed < 0) {
        mp_raise_ValueError(MP_ERROR_TEXT("buffer does not fit the SRAM left between the canvases and the display workspaces"));
    }
    return mp_obj_new_memoryview('B' | MP_OBJ_ARRAY_TYPECODE_FLAG_RW,
                                 (size_t)nbytes, sram_region_base() + claimed);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(spidisplay_buffer_obj, 1, 2, spidisplay_buffer);

static mp_obj_t spidisplay_buffer_size(void) {
    return mp_obj_new_int_from_uint(spidisplay_sram_available());
}
static MP_DEFINE_CONST_FUN_OBJ_0(spidisplay_buffer_size_obj, spidisplay_buffer_size);

static mp_obj_t spidisplay_release_buffers(void) {
    spidisplay_sram_release_low();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(spidisplay_release_buffers_obj, spidisplay_release_buffers);

static mp_obj_t spidisplay_dual_convert_obj_fn(size_t n_args, const mp_obj_t *args) {
    if (n_args > 0) {
        spidisplay_set_dual_convert(mp_obj_is_true(args[0]) ? 1 : 0);
    }
    return mp_obj_new_bool(spidisplay_dual_convert());
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(spidisplay_dual_convert_obj, 0, 1, spidisplay_dual_convert_obj_fn);

/***** Module *****/
static const mp_rom_map_elem_t spidisplay_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_spidisplay) },
    { MP_ROM_QSTR(MP_QSTR___init__), MP_ROM_PTR(&spidisplay___init___obj) },
    { MP_ROM_QSTR(MP_QSTR_SPIDisplayBus), MP_ROM_PTR(&SPIDisplayBus_type) },
    { MP_ROM_QSTR(MP_QSTR_SPIDisplay), MP_ROM_PTR(&SPIDisplay_type) },
    { MP_ROM_QSTR(MP_QSTR_buffer), MP_ROM_PTR(&spidisplay_buffer_obj) },
    { MP_ROM_QSTR(MP_QSTR_buffer_size), MP_ROM_PTR(&spidisplay_buffer_size_obj) },
    { MP_ROM_QSTR(MP_QSTR_release_buffers), MP_ROM_PTR(&spidisplay_release_buffers_obj) },
    { MP_ROM_QSTR(MP_QSTR_reserve), MP_ROM_PTR(&spidisplay_reserve_obj) },
    { MP_ROM_QSTR(MP_QSTR_dual_convert), MP_ROM_PTR(&spidisplay_dual_convert_obj) },
    { MP_ROM_QSTR(MP_QSTR_update_all), MP_ROM_PTR(&spidisplay_update_all_obj) },
    { MP_ROM_QSTR(MP_QSTR_te_phase), MP_ROM_PTR(&spidisplay_te_phase_obj) },
    { MP_ROM_QSTR(MP_QSTR_PIXEL_BYTES), MP_ROM_INT(SPIDISPLAY_PIXEL_BYTES) },
};
static MP_DEFINE_CONST_DICT(spidisplay_globals, spidisplay_globals_table);

const mp_obj_module_t spidisplay_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&spidisplay_globals,
};

MP_REGISTER_MODULE(MP_QSTR_spidisplay, spidisplay_user_cmodule);
