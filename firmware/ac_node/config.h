#pragma once
// Defaults: leave Wi-Fi blank to use the AC-Node captive portal.

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif

#ifndef SERVER_URL
#define SERVER_URL "http://10.0.0.5:5000"
#endif

#ifndef ENROLL_TOKEN
#define ENROLL_TOKEN ""
#endif

#ifndef DEVICE_API_KEY
#define DEVICE_API_KEY ""
#endif

#ifndef HEARTBEAT_MS
#define HEARTBEAT_MS 10000
#endif

#ifndef PIN_IR_TX
#define PIN_IR_TX 4
#endif
#ifndef PIN_IR_RX
#define PIN_IR_RX 15
#endif
#ifndef PIN_DOOR
#define PIN_DOOR 16
#endif
#ifndef PIN_BUZZER
#define PIN_BUZZER 18
#endif
#ifndef PIN_DHT
#define PIN_DHT 17
#endif

#ifndef PIN_WINDOW_1
#define PIN_WINDOW_1 19
#endif

#ifndef USE_DHT
#define USE_DHT 0
#endif

#ifndef LEARN_HOLD_MS
#define LEARN_HOLD_MS 3000
#endif

#define FIRMWARE_INFO "ac_node/1.0"
