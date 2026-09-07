"""
Exercise the SRAM claim allocator over a plain array via ctypes.

Same build strategy as test_scanline_c.py: use SPIDISPLAY_ALLOCATOR_TEST_LIB if
set, otherwise compile sram_allocator_host.cpp on the fly, otherwise skip.
"""

import ctypes
import functools
import os
import shutil
import subprocess
import tempfile

import pytest

_HERE = os.path.dirname(__file__)
_INCLUDE = os.path.join(_HERE, "..", "driver")
_SOURCE = os.path.join(_HERE, "sram_allocator_host.cpp")


@functools.lru_cache(maxsize=1)
def _load_library():
    path = os.environ.get("SPIDISPLAY_ALLOCATOR_TEST_LIB")
    if not path:
        compiler = (os.environ.get("CXX") or shutil.which("c++")
                    or shutil.which("g++") or shutil.which("clang++"))
        if compiler is None:
            pytest.skip("no C++ compiler and SPIDISPLAY_ALLOCATOR_TEST_LIB unset")
        out_dir = tempfile.mkdtemp(prefix="spidisplay-")
        path = os.path.join(out_dir, "sram_allocator.so")
        subprocess.run(
            [compiler, "-shared", "-fPIC", "-O2", "-std=c++17",
             "-I", _INCLUDE, "-o", path, _SOURCE],
            check=True,
        )

    lib = ctypes.CDLL(path)
    lib.allocator_reset.restype = None
    lib.allocator_claim.restype = ctypes.c_longlong
    lib.allocator_claim.argtypes = [ctypes.c_size_t]
    lib.allocator_claim_low.restype = ctypes.c_longlong
    lib.allocator_claim_low.argtypes = [ctypes.c_size_t]
    lib.allocator_release.restype = None
    lib.allocator_release.argtypes = [ctypes.c_longlong]
    lib.allocator_release_low.restype = None
    lib.allocator_available.restype = ctypes.c_size_t
    lib.allocator_headroom.restype = ctypes.c_size_t
    lib.allocator_region_bytes.restype = ctypes.c_size_t
    lib.allocator_max_claims.restype = ctypes.c_int
    return lib


def test_claims_stack_from_the_top():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    first = lib.allocator_claim(101)   # rounds to 104
    assert first == region - 104
    assert lib.allocator_available() == first

    second = lib.allocator_claim(200)
    assert second == first - 200
    assert lib.allocator_available() == second


def test_release_and_out_of_order_reuse():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    top = lib.allocator_claim(400)
    middle = lib.allocator_claim(400)
    bottom = lib.allocator_claim(400)
    assert lib.allocator_available() == region - 1200

    # Freeing the middle opens a hole an equal-or-smaller claim lands in.
    lib.allocator_release(middle)
    assert lib.allocator_available() == bottom
    refill = lib.allocator_claim(400)
    assert refill == middle

    # A claim too big for the hole steps below the deepest live claim.
    lib.allocator_release(refill)
    big = lib.allocator_claim(600)
    assert big == bottom - 600

    lib.allocator_release(top)
    lib.allocator_release(bottom)
    lib.allocator_release(big)
    assert lib.allocator_available() == region


def test_double_and_unknown_release_are_no_ops():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    claim = lib.allocator_claim(64)
    lib.allocator_release(claim)
    lib.allocator_release(claim)          # second release of the same base
    lib.allocator_release(-1)             # null
    lib.allocator_release(claim + 4)      # never a claim base
    assert lib.allocator_available() == region


def test_no_fit_and_alignment():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    assert lib.allocator_claim(region + 4) == -1
    assert lib.allocator_claim(0) == -1

    # An unaligned request rounds up and lands 4-aligned.
    claim = lib.allocator_claim(7)
    assert claim % 4 == 0
    assert lib.allocator_available() == region - 8


def test_low_claims_stack_from_the_bottom():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    first = lib.allocator_claim_low(101)   # rounds to 104
    assert first == 0
    assert lib.allocator_available() == region - 104

    second = lib.allocator_claim_low(200)
    assert second == 104
    assert lib.allocator_available() == region - 304

    # An explicitly placed view is measured against the whole region still, since
    # naming an offset reaches over the low claims deliberately.
    assert lib.allocator_headroom() == region


def test_the_two_ends_grow_toward_each_other():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    low = lib.allocator_claim_low(400)
    high = lib.allocator_claim(600)
    assert low == 0
    assert high == region - 600
    assert lib.allocator_available() == region - 1000
    assert lib.allocator_headroom() == region - 600

    # Neither end can take the span the other holds.
    assert lib.allocator_claim(region - 900) == -1
    assert lib.allocator_claim_low(region - 900) == -1

    # And each fits what is genuinely left.
    assert lib.allocator_claim_low(region - 1000) == 400
    assert lib.allocator_available() == 0


def test_release_low_drops_only_the_canvases():
    lib = _load_library()
    lib.allocator_reset()
    region = lib.allocator_region_bytes()

    lib.allocator_claim_low(400)
    lib.allocator_claim_low(400)
    high = lib.allocator_claim(600)
    assert lib.allocator_available() == region - 1400

    lib.allocator_release_low()
    assert lib.allocator_available() == region - 600   # the workspace stays
    assert lib.allocator_claim_low(8) == 0             # and the bottom is free again

    lib.allocator_release(high)
    lib.allocator_release_low()
    assert lib.allocator_available() == region


def test_low_claim_refuses_a_full_table():
    lib = _load_library()
    lib.allocator_reset()
    max_claims = lib.allocator_max_claims()

    claims = [lib.allocator_claim_low(8) for _ in range(max_claims)]
    assert all(claim >= 0 for claim in claims)
    assert lib.allocator_claim_low(8) == -1
    assert lib.allocator_claim(8) == -1     # one table, shared by both ends

    lib.allocator_release_low()
    assert lib.allocator_claim_low(8) == 0


def test_table_exhaustion_fails_cleanly():
    lib = _load_library()
    lib.allocator_reset()
    max_claims = lib.allocator_max_claims()

    claims = [lib.allocator_claim(8) for _ in range(max_claims)]
    assert all(claim >= 0 for claim in claims)
    assert lib.allocator_claim(8) == -1   # table full, region far from full

    lib.allocator_release(claims[0])
    assert lib.allocator_claim(8) == claims[0]
