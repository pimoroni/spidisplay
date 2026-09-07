# The spidisplay MicroPython module: a display transform and its DMA transport.
#
# A consumer puts this directory on the module path and calls
# find_package(SPIDISPLAY CONFIG REQUIRED). See README.md for what the module does.

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

# Half of each row range converts on core1, through the worker picovector's
# rasteriser owns (pv_core1_run/pv_core1_join). That worker only exists when
# picovector is built with PV_DUAL_CORE, so the consumer must set that variable
# before this find_package; without it, conversion stays on one core and nothing
# else changes.
if(PV_DUAL_CORE)
    target_compile_definitions(usermod_spidisplay INTERFACE SPIDISPLAY_PV_CORE1=1)
endif()

target_link_libraries(usermod INTERFACE usermod_spidisplay)
