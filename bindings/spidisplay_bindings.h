// SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
//
// SPDX-License-Identifier: MIT
//
// What the module's three binding files share. spidisplay_bindings.c holds the module
// table, spidisplay_bindings.cpp the two types, and spidisplay.cpp the C-linkage calls
// reaching the driver's own state.

#pragma once

#include "py/runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

/***** The types and their module functions, from spidisplay_bindings.cpp *****/
extern const mp_obj_type_t SPIDisplayBus_type;
extern const mp_obj_type_t SPIDisplay_type;
MP_DECLARE_CONST_FUN_OBJ_KW(spidisplay_update_all_obj);
MP_DECLARE_CONST_FUN_OBJ_VAR_BETWEEN(spidisplay_te_phase_obj);

/***** The SRAM allocator, over the region spidisplay_bindings.c hands it *****/
// Where the region came from, for the refusal a first display raises when it is empty
enum spidisplay_region_source {
    SPIDISPLAY_REGION_FREE_SRAM,      // the SRAM the PSRAM-only GC heap leaves free
    SPIDISPLAY_REGION_HEAP,           // taken from the GC heap, which owns the SRAM
    SPIDISPLAY_REGION_HEAP_IN_PSRAM,  // the heap could only spare PSRAM, so nothing was taken
    SPIDISPLAY_REGION_HEAP_FAILED,    // the heap could not spare the size asked for
};
extern void spidisplay_sram_region(uint8_t **start, uint8_t **end);
extern enum spidisplay_region_source spidisplay_sram_source(void);
extern size_t spidisplay_heap_reserve_bytes(void);
extern void spidisplay_sram_rebind(void);
extern bool spidisplay_in_psram(const void *p);
extern size_t spidisplay_sram_available(void);
extern size_t spidisplay_sram_headroom(void);
extern long long spidisplay_sram_claim_low(size_t bytes);
extern void spidisplay_sram_release_low(void);

/***** The direct source width, for sizing a canvas from Python. picovector fixes its
       framebuffer format per build and spidisplay reads it through the same setting,
       so the value is that setting and spidisplay_bindings.cpp checks it against the
       driver's trait *****/
#ifndef PV_PIXEL_FORMAT
#define PV_PIXEL_FORMAT 1
#endif
#define SPIDISPLAY_PIXEL_BYTES (PV_PIXEL_FORMAT == 2 ? 2 : 4)

/***** The dual-core conversion setting *****/
extern int spidisplay_dual_convert(void);
extern void spidisplay_set_dual_convert(int enable);

#ifdef __cplusplus
}
#endif
