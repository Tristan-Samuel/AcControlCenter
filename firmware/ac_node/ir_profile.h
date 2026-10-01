#pragma once
/*
 * IR codes for the classroom AC. Fill these from serial learn mode:
 *   Hold BOOT (GPIO 0) for 3 seconds at reset, then press remote buttons.
 * Paste the dumped raw arrays here. Frequency is typically 38 kHz.
 *
 * SET_TEMP is indexed by Celsius 16..30. Missing slots fall back to
 * sending POWER_ON only; the server still tracks the last setpoint.
 */

#include <stdint.h>

#ifndef IR_KHZ
#define IR_KHZ 38
#endif

#ifndef IR_SET_TEMP_MIN_C
#define IR_SET_TEMP_MIN_C 16
#endif
#ifndef IR_SET_TEMP_MAX_C
#define IR_SET_TEMP_MAX_C 30
#endif

// Placeholder NEC-like 32-bit codes. Replace after learning.
#ifndef IR_CODE_POWER_ON
#define IR_CODE_POWER_ON 0x10AF8877UL
#endif
#ifndef IR_CODE_POWER_OFF
#define IR_CODE_POWER_OFF 0x10AF906FUL
#endif

// Optional raw fallbacks (microseconds). Length 0 means "use 32-bit code".
static const uint16_t kRawPowerOn[1] = {0};
static const uint16_t kRawPowerOff[1] = {0};

inline const uint16_t *rawPowerOn() { return kRawPowerOn; }
inline size_t rawPowerOnLen() { return 0; }
inline const uint16_t *rawPowerOff() { return kRawPowerOff; }
inline size_t rawPowerOffLen() { return 0; }

// Per-degree raw buffers. Empty = skip (POWER_ON + protocol temp if you add it).
inline const uint16_t *rawSetTemp(int celsius, size_t *len) {
  (void)celsius;
  *len = 0;
  return nullptr;
}

inline uint32_t necCodeForSetTemp(int celsius) {
  if (celsius < IR_SET_TEMP_MIN_C || celsius > IR_SET_TEMP_MAX_C) {
    return 0;
  }
  // Placeholder: increment from a base. Replace with learned codes.
  return 0x10AF0000UL | (uint32_t)(celsius & 0xFF);
}
