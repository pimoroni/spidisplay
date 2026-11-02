// SPDX-FileCopyrightText: 2026 Christopher Parrott for Pimoroni Ltd
//
// SPDX-License-Identifier: MIT
//
// An allocator for claiming regions of free SRAM between the GC heap symbols.
//
// Claims can be taken from either end of the free SRAM, by claim_high() and
// claim_low(). In spidisplay each bus takes the workspace its displays share from
// the high end, through a SharedClaim, and canvases come from the low end, so the
// two sets grow towards each other. The free SRAM between high and low is always one
// contiguous span, and neither end fragments the other.
//
// Note, the two ends are released differently. A high claim has an owner whose
// destructor knows its base and releases that one claim, whereas a canvas is
// handed out as a view that nothing destroys, so the low claims can only be
// dropped together, when the screens that drew to them go.
//
// The allocator itself must not allocate, so the number of claims is capped at
// MAX_CLAIMS, with attempts above that failing cleanly.

#pragma once

#include <cstddef>
#include <cstdint>

namespace spidisplay {

class SRAMAllocator {
public:
    static constexpr int MAX_CLAIMS = 16;   // Sixteen seems to be enough to
                                            // cover the displays and canvases
                                            // an RP2350 board can drive at once.

    // Take the region to hand out, which must be set before any claim is made.
    void init(uint8_t *region_start, uint8_t *region_end) {
        start = region_start;
        end = region_end;
    }

    // Claim at least `bytes` from the highest free addresses. Returns nullptr if it
    // will not fit or if MAX_CLAIMS is reached.
    uint8_t *claim_high(size_t bytes) {
        if (start == nullptr || bytes == 0) {
            return nullptr;    // No region to claim from, or nothing asked for
        }

        Claim *slot = free_slot();
        if (slot == nullptr) {
            return nullptr;    // The claim table is full
        }

        // Round the size up to a whole number of 4-byte words
        bytes = (bytes + 3) & ~(size_t)3;
        if (bytes > (size_t)(end - start)) {
            return nullptr;    // Larger than the whole region, so it can never fit
        }

        // Start hard against the high end, then walk down past any live claim the
        // block overlaps. There are at most MAX_CLAIMS of them, so rescanning
        // after each move costs almost nothing.
        uint8_t *base = align_down(end - bytes);
        bool moved = true;
        while (moved) {
            if (base < start) {
                return nullptr;    // Walked outside the region, no room left
            }
            moved = false;
            for (const Claim &other : claims) {
                if (other.base != nullptr
                        && base < other.base + other.bytes
                        && other.base < base + bytes) {
                    base = align_down(other.base - bytes);
                    moved = true;
                }
            }
        }

        // Record the claim, tagged with the end it came from
        slot->base = base;
        slot->bytes = bytes;
        slot->low = false;
        return base;
    }

    // The same from the lowest free addresses, which is what marks a canvas as a
    // claim that only release_low() gives back.
    uint8_t *claim_low(size_t bytes) {
        if (start == nullptr || bytes == 0) {
            return nullptr;    // No region to claim from, or nothing asked for
        }

        Claim *slot = free_slot();
        if (slot == nullptr) {
            return nullptr;    // The claim table is full
        }

        // Round the size up to a whole number of 4-byte words
        bytes = (bytes + 3) & ~(size_t)3;
        if (bytes > (size_t)(end - start)) {
            return nullptr;    // Larger than the whole region, so it can never fit
        }

        // Start hard against the low end, then walk up, mirroring claim_high().
        uint8_t *base = align_up(start);
        bool moved = true;
        while (moved) {
            if (base + bytes > end) {
                return nullptr;    // Walked outside the region, no room left
            }
            moved = false;
            for (const Claim &other : claims) {
                if (other.base != nullptr
                        && base < other.base + other.bytes
                        && other.base < base + bytes) {
                    base = align_up(other.base + other.bytes);
                    moved = true;
                }
            }
        }

        // Record the claim, tagged with the end it came from
        slot->base = base;
        slot->bytes = bytes;
        slot->low = true;
        return base;
    }

    // Drop every low claim at once, so canvases come back when the screens that
    // drew to them do.
    void release_low() {
        for (Claim &candidate : claims) {
            if (candidate.base != nullptr && candidate.low) {
                candidate.base = nullptr;
                candidate.bytes = 0;
                candidate.low = false;
            }
        }
    }

    // Drop the one claim that starts at `base`. A nullptr or unrecognised base
    // does nothing, so releasing the same claim twice is safe.
    void release(const uint8_t *base) {
        if (base == nullptr) {
            return;
        }
        for (Claim &candidate : claims) {
            if (candidate.base == base) {
                candidate.base = nullptr;
                candidate.bytes = 0;
                return;
            }
        }
    }

    // How much free SRAM is left between the high and low claims.
    size_t available() const {
        if (start == nullptr) {
            return 0;
        }
        const uint8_t *floor = start;
        const uint8_t *ceiling = end;
        for (const Claim &candidate : claims) {
            if (candidate.base == nullptr) {
                continue;
            }
            if (candidate.low) {
                if (candidate.base + candidate.bytes > floor) {
                    floor = candidate.base + candidate.bytes;
                }
            } else if (candidate.base < ceiling) {
                ceiling = candidate.base;
            }
        }
        return ceiling > floor ? (size_t)(ceiling - floor) : 0;
    }

    // How much room a buffer placed by hand has, counted from the start of the region
    // up to the lowest high claim. Naming an offset says where to start, so this span
    // deliberately reaches over any low claims in the way.
    size_t headroom() const {
        if (start == nullptr) {
            return 0;
        }
        const uint8_t *ceiling = end;
        for (const Claim &candidate : claims) {
            if (candidate.base != nullptr && !candidate.low
                    && candidate.base < ceiling) {
                ceiling = candidate.base;
            }
        }
        return (size_t)(ceiling - start);
    }

    // Where a claim_low() base sits, as an offset from the start of the region.
    size_t low_offset(const uint8_t *base) const {
        return (size_t)(base - start);
    }

private:
    struct Claim {
        uint8_t *base = nullptr;
        size_t bytes = 0;
        bool low = false;       // Whether this is a claim from the low end,
                                // so only release_low() drops it
    };

    Claim *free_slot() {
        for (Claim &candidate : claims) {
            if (candidate.base == nullptr) {
                return &candidate;
            }
        }
        return nullptr;
    }

    static uint8_t *align_down(uint8_t *p) {
        return (uint8_t *)((uintptr_t)p & ~(uintptr_t)3);
    }

    static uint8_t *align_up(uint8_t *p) {
        return (uint8_t *)(((uintptr_t)p + 3) & ~(uintptr_t)3);
    }

    Claim claims[MAX_CLAIMS] = {};
    uint8_t *start = nullptr;
    uint8_t *end = nullptr;
};

// A high claim several users share, sized to the largest need any of them has joined
// with and held until the last one leaves. Growing moves the claim, so a user takes
// base() afresh each time it starts to use it.
class SharedClaim {
public:
    // Join with a need of `bytes`, growing the claim where it is smaller. Returns false
    // with the claim unchanged if the larger one does not fit.
    bool join(SRAMAllocator &allocator, size_t bytes) {
        if (bytes > held_bytes) {
            uint8_t *old_base = claim_base;
            allocator.release(old_base);
            uint8_t *grown = allocator.claim_high(bytes);
            if (grown == nullptr) {
                // The old block's own space is free again, so taking it back cannot fail
                if (old_base != nullptr) {
                    claim_base = allocator.claim_high(held_bytes);
                }
                return false;
            }
            claim_base = grown;
            held_bytes = bytes;
        }
        ++user_count;
        return true;
    }

    // Leave, the last user out releasing the claim
    void leave(SRAMAllocator &allocator) {
        if (user_count > 0 && --user_count == 0) {
            drop(allocator);
        }
    }

    // Release the claim whatever its users, any still joined finding no base
    void drop(SRAMAllocator &allocator) {
        allocator.release(claim_base);
        claim_base = nullptr;
        held_bytes = 0;
        user_count = 0;
    }

    uint8_t *base() const { return claim_base; }
    size_t bytes() const { return held_bytes; }
    int users() const { return user_count; }

private:
    uint8_t *claim_base = nullptr;
    size_t held_bytes = 0;      // The largest need joined with, as asked for
    int user_count = 0;
};

}  // namespace spidisplay
