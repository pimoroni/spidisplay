# The spidisplay MicroPython module: a display transform and its DMA transport.
#
# A consumer puts this directory on the module path and calls
# find_package(SPIDISPLAY CONFIG REQUIRED). See docs/driver.md for what the module
# does and what a host firmware must set.

add_library(usermod_spidisplay INTERFACE)

target_sources(usermod_spidisplay INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/driver/spidisplay.cpp
    ${CMAKE_CURRENT_LIST_DIR}/bindings/spidisplay_bindings.cpp
    ${CMAKE_CURRENT_LIST_DIR}/bindings/spidisplay_bindings.c
)

target_include_directories(usermod_spidisplay INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/driver
    ${CMAKE_CURRENT_LIST_DIR}/bindings
)

target_link_libraries(usermod_spidisplay INTERFACE
    hardware_spi
    hardware_dma
)

# The display region taken from the GC heap where that heap owns the SRAM. 40KB holds
# one panel, and spidisplay.reserve() resizes it before the first screen. A firmware
# whose heap lives in PSRAM has the free SRAM instead and never reads this.
if(NOT DEFINED SPIDISPLAY_HEAP_RESERVE_BYTES)
    set(SPIDISPLAY_HEAP_RESERVE_BYTES 40960)
endif()
target_compile_definitions(usermod_spidisplay INTERFACE
    SPIDISPLAY_HEAP_RESERVE_BYTES=${SPIDISPLAY_HEAP_RESERVE_BYTES}
)

# Half of each row range converts on core1, through the worker picovector's
# rasteriser owns (pv_core1_run/pv_core1_join). That worker only exists when
# picovector is built with PV_DUAL_CORE, so the consumer must set that variable
# before this find_package; without it, conversion stays on one core and nothing
# else changes.
if(PV_DUAL_CORE)
    target_compile_definitions(usermod_spidisplay INTERFACE SPIDISPLAY_PV_CORE1=1)
endif()

# The framebuffer format picovector is built for, 1 for RGBA8888 (the default) or 2 for
# RGBA4444. The consumer sets it once before both find_package calls, so the two
# libraries read the same width.
if(DEFINED PV_PIXEL_FORMAT)
    target_compile_definitions(usermod_spidisplay INTERFACE
        PV_PIXEL_FORMAT=${PV_PIXEL_FORMAT}
    )
endif()

target_link_libraries(usermod INTERFACE usermod_spidisplay)
