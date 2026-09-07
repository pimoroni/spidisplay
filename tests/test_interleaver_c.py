"""
Drive interleaver.hpp through the host mock in interleaver_host.cpp with per-row
costs measured from two panels on hardware, and check the staging arithmetic
driving several displays at once rests on.

If SPIDISPLAY_INTERLEAVER_LIB points at a prebuilt shared library it is used
directly. Otherwise, when a C++ compiler is available, interleaver_host.cpp
is compiled on the fly; with neither the test skips.
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
_SOURCE = os.path.join(_HERE, "interleaver_host.cpp")

# Measured figures: wall row budget at 24MHz 16-bit frames, and per-screen
# convert costs (SRAM canvas, PSRAM rotation 0, PSRAM rotation 90).
WIRE_US = 131.3
CONVERT_SRAM = 37.8
CONVERT_PSRAM_R0 = 72.9
CONVERT_PSRAM_R90 = 86.9

# A 46fps refresh with the ~7% duty pulse the tear analysis assumes.
TE_PERIOD = 1e6 / 46
TE_HIGH = 0.07 * TE_PERIOD
TIMEOUT = 2 * TE_PERIOD


class InterleaveSpec(ctypes.Structure):
    _fields_ = [
        ("convert_us_per_row", ctypes.c_double),
        ("wire_us_per_row", ctypes.c_double),
        ("te_period_us", ctypes.c_double),
        ("te_high_us", ctypes.c_double),
        ("te_phase_us", ctypes.c_double),
        ("te_timeout_us", ctypes.c_double),
        ("rows", ctypes.c_int),
        ("first_band_rows", ctypes.c_int),
        ("capacity_rows", ctypes.c_int),
        ("v_sync", ctypes.c_int),
        ("band_rows", ctypes.c_int),
    ]


class InterleaveOut(ctypes.Structure):
    _fields_ = [
        ("write_start_us", ctypes.c_double),
        ("stall_us", ctypes.c_double),
        ("frame_us", ctypes.c_double),
        ("te_timeouts", ctypes.c_int),
        ("completed", ctypes.c_int),
        ("convert_switches", ctypes.c_int),
    ]


@functools.lru_cache(maxsize=1)
def _load_library():
    path = os.environ.get("SPIDISPLAY_INTERLEAVER_LIB")
    if not path:
        compiler = (os.environ.get("CXX") or shutil.which("c++")
                    or shutil.which("g++") or shutil.which("clang++"))
        if compiler is None:
            pytest.skip("no C++ compiler and SPIDISPLAY_INTERLEAVER_LIB unset")
        out_dir = tempfile.mkdtemp(prefix="spidisplay-interleaver-")
        path = os.path.join(out_dir, "interleaver.so")
        subprocess.run(
            [compiler, "-shared", "-fPIC", "-O2", "-std=c++17",
             "-I", _INCLUDE, "-o", path, _SOURCE],
            check=True,
        )

    lib = ctypes.CDLL(path)
    lib.interleave_run.restype = ctypes.c_int
    lib.interleave_run.argtypes = [
        ctypes.POINTER(InterleaveSpec), ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(InterleaveOut),
    ]
    return lib


def _spec(convert, rows=320, band=12, capacity=24, wire=WIRE_US,
          phase=5000.0, period=TE_PERIOD, v_sync=True, timeout=TIMEOUT):
    return InterleaveSpec(
        convert_us_per_row=convert, wire_us_per_row=wire,
        te_period_us=period, te_high_us=TE_HIGH, te_phase_us=phase,
        te_timeout_us=timeout, rows=rows, first_band_rows=band,
        capacity_rows=capacity, v_sync=1 if v_sync else 0, band_rows=1,
    )


def _run(specs, slice_rows=4, hysteresis_rows=-1):
    lib = _load_library()
    array = (InterleaveSpec * len(specs))(*specs)
    out = (InterleaveOut * len(specs))()
    assert lib.interleave_run(array, len(specs), slice_rows,
                              hysteresis_rows, out) == 0
    for entry in out:
        assert entry.completed == 1
    return list(out)


def test_sram_dual_is_wire_bound():
    """Both wires stream flat out from an SRAM canvas: no stalls, wire-time frames."""
    a, b = _run([_spec(CONVERT_SRAM, phase=5000.0),
                 _spec(CONVERT_SRAM, phase=8000.0)])
    assert a.stall_us == 0 and b.stall_us == 0
    for entry in (a, b):
        assert entry.frame_us == pytest.approx(320 * WIRE_US, rel=0.01)
    # The residual skew is the TE phase offset, never a frame time.
    assert abs(a.write_start_us - b.write_start_us) < TE_PERIOD


def test_psram_band_deep_buffers_stall():
    """Dual PSRAM at band-deep buffering misses the budget and the wire gaps."""
    a, b = _run([_spec(CONVERT_PSRAM_R0, phase=5000.0),
                 _spec(CONVERT_PSRAM_R0, phase=8000.0)])
    assert a.stall_us + b.stall_us > 1000


def test_psram_rotation0_staging_recovers():
    """~32 rows of head start absorb rotation 0's deficit; 48 covers it."""
    a, b = _run([_spec(CONVERT_PSRAM_R0, capacity=48, phase=12000.0),
                 _spec(CONVERT_PSRAM_R0, capacity=48, phase=15000.0)])
    assert a.stall_us + b.stall_us < 300


def test_psram_rotation90_needs_deeper_staging():
    """Rotation 90 needs ~78 rows staged; 96 is clean where 48 is not."""
    shallow = _run([_spec(CONVERT_PSRAM_R90, capacity=48, phase=12000.0),
                    _spec(CONVERT_PSRAM_R90, capacity=48, phase=15000.0)])
    deep = _run([_spec(CONVERT_PSRAM_R90, capacity=96, phase=16000.0),
                 _spec(CONVERT_PSRAM_R90, capacity=96, phase=19000.0)])
    assert shallow[0].stall_us + shallow[1].stall_us > 1000
    assert deep[0].stall_us + deep[1].stall_us < 300


def test_te_silence_times_out_and_streams():
    """A TE that never fires starts the frame at the timeout and counts it."""
    a, b = _run([_spec(CONVERT_SRAM, period=0.0),
                 _spec(CONVERT_SRAM, period=0.0)])
    for entry in (a, b):
        assert entry.te_timeouts == 1
        assert entry.frame_us == pytest.approx(320 * WIRE_US, rel=0.01)


def test_mismatched_panels_coexist():
    """A 240-row and a 320-row panel at different wire rates both stay clean."""
    a, b = _run([_spec(CONVERT_SRAM, rows=240, phase=5000.0),
                 _spec(CONVERT_SRAM, rows=320, wire=142.5, phase=8000.0)])
    assert a.stall_us == 0 and b.stall_us == 0
    assert a.frame_us == pytest.approx(240 * WIRE_US, rel=0.01)
    assert b.frame_us == pytest.approx(320 * 142.5, rel=0.01)


def test_single_display_interleave():
    """n=1 is a valid interleave: one display, no stalls, wire-bound frame."""
    (a,) = _run([_spec(CONVERT_SRAM)])
    assert a.stall_us == 0
    assert a.frame_us == pytest.approx(320 * WIRE_US, rel=0.01)


def test_sticky_bursts_not_alternation():
    """The convert slot moves in bursts, tens of takeovers, not one per slice."""
    a, b = _run([_spec(CONVERT_PSRAM_R90, capacity=96, phase=16000.0),
                 _spec(CONVERT_PSRAM_R90, capacity=96, phase=19000.0)])
    switches = a.convert_switches + b.convert_switches
    assert 1 < switches < 60


def test_sticky_no_starvation():
    """Bursting on one display never starves the other's wire past the seam."""
    a, b = _run([_spec(CONVERT_PSRAM_R90, capacity=96, phase=16000.0),
                 _spec(CONVERT_PSRAM_R90, capacity=96, phase=19000.0)])
    assert a.stall_us + b.stall_us < 300


def test_mismatched_rings_share_the_slot():
    """Different ring depths take the auto hysteresis each from their own ring."""
    a, b = _run([_spec(CONVERT_SRAM, capacity=48, phase=5000.0),
                 _spec(CONVERT_SRAM, capacity=96, phase=8000.0)])
    assert a.stall_us == 0 and b.stall_us == 0
