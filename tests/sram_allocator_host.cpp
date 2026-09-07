// SPDX-License-Identifier: MIT
//
// Host-only C-linkage wrapper around sram_allocator.hpp so ctypes
// (test_sram_allocator_c.py) can drive claim/release/available over a plain
// array. Not built into firmware.
//
//   c++ -shared -fPIC -O2 -std=c++17 -I driver -o sram_allocator.so tests/sram_allocator_host.cpp

#include <cstdint>

#include "sram_allocator.hpp"

using namespace spidisplay;

static constexpr size_t REGION_BYTES = 4096;
static uint8_t region[REGION_BYTES] __attribute__((aligned(4)));
static SRAMAllocator allocator;

// Offsets keep the Python side pointer-free: claims report their distance from
// the region base, -1 for a refused claim.
extern "C" void allocator_reset(void) {
    allocator = SRAMAllocator();
    allocator.init(region, region + REGION_BYTES);
}

extern "C" long long allocator_claim(size_t bytes) {
    uint8_t *base = allocator.claim_high(bytes);
    return base == nullptr ? -1 : (long long)(base - region);
}

extern "C" long long allocator_claim_low(size_t bytes) {
    uint8_t *base = allocator.claim_low(bytes);
    return base == nullptr ? -1 : (long long)(base - region);
}

extern "C" void allocator_release(long long offset) {
    allocator.release(offset < 0 ? nullptr : region + offset);
}

extern "C" void allocator_release_low(void) {
    allocator.release_low();
}

extern "C" size_t allocator_available(void) {
    return allocator.available();
}

extern "C" size_t allocator_headroom(void) {
    return allocator.headroom();
}

extern "C" size_t allocator_region_bytes(void) {
    return REGION_BYTES;
}

extern "C" int allocator_max_claims(void) {
    return SRAMAllocator::MAX_CLAIMS;
}
