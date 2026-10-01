/*
 * Classroom ESP32 node for AC Control Center.
 *
 * Libraries (Arduino Library Manager):
 *   IRremoteESP8266, ArduinoJson, WiFiManager
 *
 * Copy config.h.example to config.h. First boot opens a WiFi AP named
 * AC-Node-XXXX so you can enter school Wi-Fi, SERVER_URL, and enroll token.
 * The board enrolls by MAC; assign it to a room in the admin UI.
 *
 * Hold BOOT (GPIO 0) for 3s at reset to dump IR captures to Serial (115200).
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiManager.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <IRrecv.h>
#include <IRutils.h>

#include "config.h"
#include "ir_profile.h"

#if USE_DHT
#include <DHT.h>
DHT dht(PIN_DHT, DHT22);
#endif

static const uint16_t kCaptureBuffer = 1024;
static const uint8_t kTimeout = 50;

IRsend irsend(PIN_IR_TX);
IRrecv irrecv(PIN_IR_RX, kCaptureBuffer, kTimeout, true);
decode_results irResult;
Preferences prefs;

String gServerUrl;
String gApiKey;
String gEnrollToken;
String gMac;
String gAcState = "off";
String gDoorState = "closed";
float gSetTempC = 20.0;
float gAmbientC = 22.0;
bool gBuzz = false;
bool gLearnMode = false;

unsigned long lastHeartbeat = 0;
int lastDoorLevel = HIGH;

String normalizeMac(const String &raw) {
  String hex;
  for (size_t i = 0; i < raw.length(); i++) {
    char c = raw.charAt(i);
    if (isxdigit(c)) {
      hex += (char)toupper(c);
    }
  }
  if (hex.length() != 12) {
    return raw;
  }
  String out;
  for (int i = 0; i < 12; i += 2) {
    if (i) {
      out += ':';
    }
    out += hex.substring(i, i + 2);
  }
  return out;
}

String doorStateFromPin() {
  int level = digitalRead(PIN_DOOR);
  return level == HIGH ? "opened" : "closed";
}

void setBuzz(bool on) {
  gBuzz = on;
  digitalWrite(PIN_BUZZER, on ? HIGH : LOW);
}

void sendNecOrRaw(uint32_t nec, const uint16_t *raw, size_t rawLen) {
  if (raw && rawLen > 0) {
    irsend.sendRaw(raw, rawLen, IR_KHZ);
    return;
  }
  if (nec) {
    irsend.sendNEC(nec);
  }
}

void executeCommand(const String &command) {
  Serial.printf("IR command: %s\n", command.c_str());
  if (command == "POWER_ON") {
    sendNecOrRaw(IR_CODE_POWER_ON, rawPowerOn(), rawPowerOnLen());
    delay(200);
    size_t len = 0;
    const uint16_t *raw = rawSetTemp((int)lroundf(gSetTempC), &len);
    sendNecOrRaw(necCodeForSetTemp((int)lroundf(gSetTempC)), raw, len);
    gAcState = "on";
  } else if (command == "POWER_OFF") {
    sendNecOrRaw(IR_CODE_POWER_OFF, rawPowerOff(), rawPowerOffLen());
    gAcState = "off";
  } else if (command.startsWith("SET_TEMP_")) {
    int temp = command.substring(9).toInt();
    gSetTempC = (float)temp;
    size_t len = 0;
    const uint16_t *raw = rawSetTemp(temp, &len);
    sendNecOrRaw(necCodeForSetTemp(temp), raw, len);
  }
}

bool httpPost(const String &path, const String &body, const char *extraHeader,
              const char *extraValue, String &response, int &code) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  HTTPClient http;
  String url = gServerUrl + path;
  http.begin(url);
  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  if (gApiKey.length()) {
    http.addHeader("X-API-Key", gApiKey);
  }
  http.addHeader("X-Device-Mac", gMac);
  if (extraHeader && extraValue) {
    http.addHeader(extraHeader, extraValue);
  }
  code = http.POST(body);
  response = http.getString();
  http.end();
  return code > 0;
}

void applyHeartbeatResponse(const String &response) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, response);
  if (err) {
    Serial.printf("JSON parse error: %s\n", err.c_str());
    return;
  }
  if (doc["set_temperature_c"].is<float>() || doc["set_temperature_c"].is<int>()) {
    gSetTempC = doc["set_temperature_c"].as<float>();
  }
  setBuzz(doc["buzz"] | false);
  if (doc["ac_state"].is<const char *>()) {
    gAcState = doc["ac_state"].as<String>();
  }
  JsonArray commands = doc["commands"].as<JsonArray>();
  if (!commands.isNull()) {
    for (JsonVariant v : commands) {
      executeCommand(v.as<String>());
    }
  }
}

String statusBody(const char *irEvent) {
  JsonDocument doc;
  doc["mac"] = gMac;
  doc["door_state"] = gDoorState;
  doc["window_state"] = "closed";
  doc["ac_state"] = gAcState;
  doc["temperature_c"] = gAmbientC;
  if (irEvent && irEvent[0]) {
    doc["ir_event"] = irEvent;
  }
  String out;
  serializeJson(doc, out);
  return out;
}

void heartbeat(const char *irEvent = nullptr) {
  gDoorState = doorStateFromPin();
#if USE_DHT
  float reading = dht.readTemperature();
  if (!isnan(reading)) {
    gAmbientC = reading;
  }
#endif
  String body = statusBody(irEvent);
  String response;
  int code = 0;
  if (!httpPost("/api/v1/heartbeat", body, nullptr, nullptr, response, code)) {
    Serial.println("Heartbeat failed (offline). Fail closed: not sending local ON.");
    return;
  }
  if (code == 401) {
    Serial.println("API key rejected. Re-enroll or rotate the key.");
    return;
  }
  if (code != 200) {
    Serial.printf("Heartbeat HTTP %d: %s\n", code, response.c_str());
    return;
  }
  applyHeartbeatResponse(response);
  lastHeartbeat = millis();
}

bool enrollOnce() {
  JsonDocument doc;
  doc["mac"] = gMac;
  doc["firmware"] = FIRMWARE_INFO;
  if (gEnrollToken.length()) {
    doc["enroll_token"] = gEnrollToken;
  }
  String body;
  serializeJson(doc, body);
  String response;
  int code = 0;
  const char *hdr = gEnrollToken.length() ? "X-Enroll-Token" : nullptr;
  const char *val = gEnrollToken.length() ? gEnrollToken.c_str() : nullptr;
  if (!httpPost("/api/v1/enroll", body, hdr, val, response, code)) {
    Serial.println("Enroll request failed");
    return false;
  }
  if (code != 200) {
    Serial.printf("Enroll HTTP %d: %s\n", code, response.c_str());
    return false;
  }
  JsonDocument reply;
  if (deserializeJson(reply, response)) {
    return false;
  }
  if (reply["assigned"] != true) {
    Serial.println("Waiting for admin to assign this MAC…");
    return false;
  }
  if (reply["api_key"].is<const char *>()) {
    String key = reply["api_key"].as<String>();
    if (key.length()) {
      gApiKey = key;
      prefs.putString("api_key", gApiKey);
      Serial.println("Stored API key from enroll.");
    }
  }
  return gApiKey.length() > 0;
}

void dumpLearnCapture() {
  if (!irrecv.decode(&irResult)) {
    return;
  }
  Serial.println("--- IR capture ---");
  Serial.print(resultToHumanReadableBasic(&irResult));
  Serial.println(resultToSourceCode(&irResult));
  irrecv.resume();
}

void maybeLearnMode() {
  pinMode(0, INPUT_PULLUP);
  unsigned long start = millis();
  while (digitalRead(0) == LOW && (millis() - start) < LEARN_HOLD_MS) {
    delay(20);
  }
  if (digitalRead(0) == LOW) {
    gLearnMode = true;
    Serial.println("LEARN MODE: press remote buttons. Reset to exit.");
  }
}

void saveWifiManagerParams(WiFiManager &wm, WiFiManagerParameter &server,
                           WiFiManagerParameter &token, WiFiManagerParameter &key) {
  gServerUrl = server.getValue();
  gEnrollToken = token.getValue();
  String keyVal = key.getValue();
  if (gServerUrl.length()) {
    prefs.putString("server_url", gServerUrl);
  }
  prefs.putString("enroll_token", gEnrollToken);
  if (keyVal.length()) {
    gApiKey = keyVal;
    prefs.putString("api_key", gApiKey);
  }
}

void connectWifi() {
  prefs.begin("ac", false);
  gServerUrl = prefs.getString("server_url", SERVER_URL);
  gApiKey = prefs.getString("api_key", DEVICE_API_KEY);
  gEnrollToken = prefs.getString("enroll_token", ENROLL_TOKEN);

  WiFi.mode(WIFI_STA);
  gMac = normalizeMac(WiFi.macAddress());
  Serial.printf("MAC %s\n", gMac.c_str());

  if (strlen(WIFI_SSID) > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
      delay(250);
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
    WiFiManager wm;
    WiFiManagerParameter pServer("server", "Server URL", gServerUrl.c_str(), 80);
    WiFiManagerParameter pToken("enroll", "Enroll token", gEnrollToken.c_str(), 64);
    WiFiManagerParameter pKey("apikey", "API key (optional)", gApiKey.c_str(), 80);
    wm.addParameter(&pServer);
    wm.addParameter(&pToken);
    wm.addParameter(&pKey);
    String ap = "AC-Node-" + gMac.substring(12);
    if (!wm.autoConnect(ap.c_str())) {
      Serial.println("WiFiManager failed; rebooting");
      delay(2000);
      ESP.restart();
    }
    saveWifiManagerParams(wm, pServer, pToken, pKey);
  }
  Serial.printf("WiFi %s  server %s\n", WiFi.localIP().toString().c_str(), gServerUrl.c_str());
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PIN_DOOR, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  pinMode(PIN_WINDOW_1, INPUT_PULLUP);
#if USE_DHT
  dht.begin();
#endif
  irsend.begin();
  irrecv.enableIRIn();
  maybeLearnMode();
  connectWifi();
  lastDoorLevel = digitalRead(PIN_DOOR);
  gDoorState = doorStateFromPin();

  if (!gLearnMode && gApiKey.length() == 0) {
    Serial.println("No API key yet; polling enroll.");
    for (int i = 0; i < 30 && gApiKey.length() == 0; i++) {
      if (enrollOnce()) {
        break;
      }
      delay(5000);
    }
  }
  if (!gLearnMode) {
    heartbeat();
  }
}

void loop() {
  if (gLearnMode) {
    dumpLearnCapture();
    delay(50);
    return;
  }

  int door = digitalRead(PIN_DOOR);
  if (door != lastDoorLevel) {
    delay(50);
    door = digitalRead(PIN_DOOR);
    if (door != lastDoorLevel) {
      lastDoorLevel = door;
      gDoorState = doorStateFromPin();
      Serial.printf("Door -> %s\n", gDoorState.c_str());
      heartbeat();
    }
  }

  if (irrecv.decode(&irResult)) {
    String decoded = typeToString(irResult.decode_type);
    Serial.printf("IR RX %s\n", decoded.c_str());
    const char *event = "POWER";
    if (gAcState == "on" && irResult.decode_type == decode_type_t::UNKNOWN) {
      event = "POWER";
    }
    irrecv.resume();
    heartbeat(event);
  }

  if (gApiKey.length() == 0 && millis() - lastHeartbeat > 5000) {
    enrollOnce();
    lastHeartbeat = millis();
  }

  if (millis() - lastHeartbeat >= HEARTBEAT_MS) {
    heartbeat();
  }

  if (gApiKey.length() == 0 && WiFi.status() == WL_CONNECTED) {
    delay(200);
  }
}
