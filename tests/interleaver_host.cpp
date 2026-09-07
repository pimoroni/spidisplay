// Host-side mock for interleaver.hpp: displays with simulated convert and wire
// costs on a shared virtual clock, so the interleaver's scheduling can be
// measured against per-frame figures taken from two panels on hardware, without
// hardware. The wire drains converted rows continuously; a row converted after
// the wire ran dry counts the idle gap as stall, which is the seam-migration
// time on the panel.
//
// Build (see test_interleaver_c.py):
//   c++ -O2 -shared -fPIC -I ../driver interleaver_host.cpp -o interleaver.so

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <vector>

#include "interleaver.hpp"

namespace {

struct MockDisplay;

struct Sim {
    double now = 0.0;
    std::vector<MockDisplay *> displays;
    MockDisplay *last_converter = nullptr;
};

struct MockDisplay {
    Sim *sim = nullptr;

    // Parameters
    int rows = 0;
    int capacity_rows = 0;        // converted rows the workspace can hold
    double convert_us_per_row = 0;
    double wire_us_per_row = 0;
    double te_period_us = 0;      // 0 means TE never fires
    double te_high_us = 0;
    double te_phase_us = 0;       // first rising edge
    int band_rows_v = 1;          // mock rows queue singly, so 1 unless a spec says

    // Frame state, mirroring SPIDisplay's FrameState values
    int state = 0;                // 0 idle, 1 prepared, 2 armed, 3 streaming
    bool te_fired = false;
    double te_fire_t = -1;
    double armed_t = 0;
    double timeout_budget = 0;
    int rows_converted = 0;
    std::vector<double> drain_t;  // per queued row, when it leaves the wire
    double wire_free_t = 0;
    double stream_start = 0;

    // Results
    double write_start = 0;
    double stall_us = 0;
    double frame_us = 0;
    int te_timeouts = 0;
    int completed = 0;
    int convert_switches = 0;     // times this display took the convert slot over

    void prepare(int first_band_rows) {
        rows_converted = std::min(first_band_rows, rows);
        sim->now += rows_converted * convert_us_per_row;
        state = 1;
    }

    // Falling edges sit at phase + k*period + high. The rising-then-falling
    // wait fires on the first one at or after the arm, a line already high at
    // the arm still ending at that pulse's fall.
    static double first_fall_at_or_after(double t, double phase, double period,
                                         double high) {
        if (period <= 0) {
            return -1;
        }
        double k = std::ceil((t - phase - high) / period);
        if (k < 0) {
            k = 0;
        }
        return phase + k * period + high;
    }

    void arm(bool v_sync, uint32_t timeout_us) {
        if (state != 1) {
            return;
        }
        armed_t = sim->now;
        timeout_budget = (double)timeout_us;
        te_fired = !v_sync;
        te_fire_t = v_sync
            ? first_fall_at_or_after(sim->now, te_phase_us, te_period_us, te_high_us)
            : sim->now;
        state = 2;
    }

    bool poll_te() {
        if (state != 2) {
            return false;
        }
        if (te_fired) {
            return true;
        }
        if (te_fire_t >= 0 && sim->now >= te_fire_t) {
            te_fired = true;
            return true;
        }
        if (sim->now - armed_t >= timeout_budget) {
            ++te_timeouts;
            te_fired = true;
            return true;
        }
        return false;
    }

    int buffer_used() const {
        if (state < 3) {
            return rows_converted;   // nothing drains before the stream
        }
        int drained = 0;
        for (double t : drain_t) {
            drained += (t <= sim->now) ? 1 : 0;
        }
        return rows_converted - drained;
    }

    void queue_rows(int n) {
        double start = std::max(wire_free_t, sim->now);
        if (!drain_t.empty() && sim->now > wire_free_t) {
            stall_us += sim->now - wire_free_t;   // the wire sat idle this long
        }
        for (int i = 1; i <= n; ++i) {
            drain_t.push_back(start + i * wire_us_per_row);
        }
        wire_free_t = start + n * wire_us_per_row;
    }

    void start_stream() {
        if (state != 2 || !te_fired) {
            return;
        }
        write_start = sim->now;
        stream_start = sim->now;
        state = 3;
        // Everything converted ahead of the edge streams from the start.
        drain_t.clear();
        for (int i = 1; i <= rows_converted; ++i) {
            drain_t.push_back(sim->now + i * wire_us_per_row);
        }
        wire_free_t = sim->now + rows_converted * wire_us_per_row;
    }

    bool step(int max_rows) {
        bool advanced = false;
        if ((state == 2 || state == 3) && max_rows > 0 && rows_converted < rows) {
            int room = capacity_rows - buffer_used();
            int c = std::min(std::min(max_rows, room), rows - rows_converted);
            if (c > 0) {
                if (sim->last_converter != this) {
                    sim->last_converter = this;
                    ++convert_switches;
                }
                sim->now += c * convert_us_per_row;
                rows_converted += c;
                if (state == 3) {
                    queue_rows(c);
                }
                advanced = true;
            }
        }
        if (state == 3 && rows_converted == rows && sim->now >= wire_free_t) {
            frame_us = wire_free_t - stream_start;
            completed = 1;
            state = 0;
            advanced = true;
        }
        return advanced;
    }

    bool wants_convert() const {
        if (state != 2 && state != 3) {
            return false;
        }
        return rows_converted < rows && buffer_used() < capacity_rows;
    }

    bool done() const { return state == 0; }

    bool busy() const { return state == 3 && sim->now < wire_free_t; }

    int band_rows() const { return band_rows_v; }

    int staged_rows() const { return buffer_used(); }

    int stage_capacity_rows() const { return capacity_rows; }

    int stage_free_rows() const {
        int free_rows = capacity_rows - buffer_used();
        int remaining = rows - rows_converted;
        if (free_rows > remaining) {
            free_rows = remaining;
        }
        return free_rows < 0 ? 0 : free_rows;
    }

    bool convert_done() const { return rows_converted >= rows; }

    uint32_t deadline_us() const {
        if (state != 3 || sim->now >= wire_free_t) {
            return 0;
        }
        return (uint32_t)(wire_free_t - sim->now);
    }

    double next_event() const {
        double best = -1;
        auto consider = [&](double t) {
            if (t > sim->now && (best < 0 || t < best)) {
                best = t;
            }
        };
        if (state == 2 && !te_fired) {
            if (te_fire_t >= 0) {
                consider(te_fire_t);
            }
            consider(armed_t + timeout_budget);
        }
        if (state == 3) {
            consider(wire_free_t);
            for (double t : drain_t) {
                consider(t);   // buffer room frees a row at a time
            }
        }
        return best;
    }

    void idle_wait() {
        double best = -1;
        for (MockDisplay *d : sim->displays) {
            double t = d->next_event();
            if (t > 0 && (best < 0 || t < best)) {
                best = t;
            }
        }
        sim->now = best > 0 ? best : sim->now + 1.0;
    }
};

}  // namespace

extern "C" {

// Field order keeps the doubles first so the layout carries no padding and the
// ctypes mirror in test_interleaver_c.py stays a plain field list.
struct InterleaveSpec {
    double convert_us_per_row;
    double wire_us_per_row;
    double te_period_us;
    double te_high_us;
    double te_phase_us;
    double te_timeout_us;
    int rows;
    int first_band_rows;
    int capacity_rows;
    int v_sync;
    int band_rows;                // 0 falls back to 1
};

struct InterleaveOut {
    double write_start_us;
    double stall_us;
    double frame_us;
    int te_timeouts;
    int completed;
    int convert_switches;
};

// Prepare and interleave n mock displays; v_sync and the timeout come from
// specs[0]. Returns 0, or -1 for a bad count.
int interleave_run(const InterleaveSpec *specs, int n, int slice_rows,
                   int hysteresis_rows, InterleaveOut *out) {
    if (n < 1 || n > 8) {
        return -1;
    }

    Sim sim;
    std::vector<MockDisplay> displays((size_t)n);
    std::vector<MockDisplay *> ptrs((size_t)n);
    for (int i = 0; i < n; ++i) {
        MockDisplay &d = displays[(size_t)i];
        d.sim = &sim;
        d.rows = specs[i].rows;
        d.capacity_rows = specs[i].capacity_rows;
        d.convert_us_per_row = specs[i].convert_us_per_row;
        d.wire_us_per_row = specs[i].wire_us_per_row;
        d.te_period_us = specs[i].te_period_us;
        d.te_high_us = specs[i].te_high_us;
        d.te_phase_us = specs[i].te_phase_us;
        d.band_rows_v = specs[i].band_rows > 0 ? specs[i].band_rows : 1;
        sim.displays.push_back(&d);
        ptrs[(size_t)i] = &d;
    }

    for (int i = 0; i < n; ++i) {
        displays[(size_t)i].prepare(specs[i].first_band_rows);
    }

    spidisplay::interleave(ptrs.data(), n, specs[0].v_sync != 0,
                           (uint32_t)specs[0].te_timeout_us, slice_rows,
                           hysteresis_rows);

    for (int i = 0; i < n; ++i) {
        const MockDisplay &d = displays[(size_t)i];
        out[i].write_start_us = d.write_start;
        out[i].stall_us = d.stall_us;
        out[i].frame_us = d.frame_us;
        out[i].te_timeouts = d.te_timeouts;
        out[i].completed = d.completed;
        out[i].convert_switches = d.convert_switches;
    }
    return 0;
}

}  // extern "C"
