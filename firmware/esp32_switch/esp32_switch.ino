/*
  Luna ESP32 Switch Controller  -  up to 4 x MG90 micro servos flicking mechanical light / fan switches
  ---------------------------------------------------------------------------------------------------
  * Joins your 2.4 GHz Wi-Fi (non-blocking, reconnects by itself)
  * REST API on port 80 (built-in WebServer, no async library needed)
        GET  /api/info        -> {"name","fw","servos","ip"}
        GET  /api/status      -> {"ok":true,"rssi":-55,"uptime":123,"servos":[{"id":0,"state":"off","busy":false,"neutral":90},...]}
        POST /api/servo       <- {"servo_id":0,"action":"on"|"off","angle":45}      -> 200 {"ok":true,...}
        POST /api/calibrate   <- {"servo_id":0,"neutral":92}                         (stored in flash)
  * mDNS name  esp32-switch.local   (+ service _luna-switch._tcp so Luna can auto-discover the node)
  * The servo moves smoothly (no blocking delay): neutral -> flick -> hold -> back to neutral, then detaches (no buzzing)
  * Optional shared secret: set API_KEY and put the same text in Luna's config_local.py (ESP32_API_KEY)

  Meaning of "angle": how many degrees to push away from the neutral position.
      "on"  -> neutral + angle      "off" -> neutral - angle      (swap with INVERT[] if your switch works the other way)

  Libraries (Arduino IDE -> Library Manager):  "ESP32Servo" by Kevin Harrington,  "ArduinoJson" by Benoit Blanchon (v7)
  Board: "ESP32 Dev Module"  (esp32 core by Espressif, 2.x or 3.x)

  WIRING (see the guide PDF):  servo signal -> GPIO 13 / 14 / 26 / 27,  servo red -> external 5 V supply (NOT the ESP32 3V3 pin),
                               servo brown -> GND shared with the ESP32 GND.  Add a 470 uF capacitor across the servo 5 V rail.
*/
#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>
#include <Preferences.h>

// ============================== EDIT THESE ==============================
const char* WIFI_SSID   = "YOUR_WIFI_NAME";
const char* WIFI_PASS   = "YOUR_WIFI_PASSWORD";
const char* HOST_NAME   = "esp32-switch";          // -> esp32-switch.local
const char* API_KEY     = "";                      // "" = no key. Otherwise Luna must send header X-Luna-Key
const int   NUM_SERVOS  = 4;                       // 1..4 connected
const int   SERVO_PINS[4] = {13, 14, 26, 27};
const int   DEFAULT_NEUTRAL[4] = {90, 90, 90, 90}; // resting angle of each arm
const bool  INVERT[4]   = {false, false, false, false};
const int   DEFAULT_FLICK = 45;                    // degrees from neutral when "angle" is not sent
const unsigned HOLD_MS  = 450;                     // how long the arm presses the switch
const unsigned STEP_MS  = 12;                      // smoothness: one 2-degree step every 12 ms
const int   STEP_DEG    = 2;
// ========================================================================

const char* FW_VERSION = "1.0";

enum Phase { IDLE, TO_FLICK, HOLDING, TO_NEUTRAL, SETTLE };

struct ServoCh {
  Servo servo;
  int pin = 0;
  int neutral = 90;
  int target = 90;
  float pos = 90;
  int flickAngle = 135;
  Phase phase = IDLE;
  unsigned long t = 0;
  bool isOn = false;            // logical state of the wall switch
};

ServoCh ch[4];
WebServer server(80);
Preferences prefs;
unsigned long lastWifiCheck = 0, wifiStart = 0;
bool mdnsUp = false;

// ---------------------------------------------------------------- helpers
static void sendJson(int code, JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  server.send(code, "application/json", out);
}

static void sendErr(int code, const char* msg) {
  JsonDocument d;
  d["ok"] = false;
  d["error"] = msg;
  sendJson(code, d);
}

static bool authorised() {
  if (strlen(API_KEY) == 0) return true;
  return server.header("X-Luna-Key") == String(API_KEY);
}

// ---------------------------------------------------------------- servo state machine (non-blocking)
static void startFlick(int id, bool on, int angle) {
  ServoCh& c = ch[id];
  bool up = on ^ INVERT[id];
  int flick = up ? c.neutral + angle : c.neutral - angle;
  c.flickAngle = constrain(flick, 0, 180);
  c.isOn = on;
  if (!c.servo.attached()) {
    c.servo.setPeriodHertz(50);
    c.servo.attach(c.pin, 500, 2400);       // MG90: 500-2400 us
    c.servo.write((int)c.pos);
  }
  c.target = c.flickAngle;
  c.phase = TO_FLICK;
  c.t = millis();
}

static void updateServos() {
  unsigned long now = millis();
  for (int i = 0; i < NUM_SERVOS; i++) {
    ServoCh& c = ch[i];
    if (c.phase == IDLE) continue;
    if (c.phase == HOLDING) {
      if (now - c.t >= HOLD_MS) { c.target = c.neutral; c.phase = TO_NEUTRAL; c.t = now; }
      continue;
    }
    if (c.phase == SETTLE) {
      if (now - c.t >= 350) { c.servo.detach(); c.phase = IDLE; }   // no jitter, no heat
      continue;
    }
    if (now - c.t < STEP_MS) continue;
    c.t = now;
    if (c.pos < c.target) c.pos = min((float)c.target, c.pos + STEP_DEG);
    else if (c.pos > c.target) c.pos = max((float)c.target, c.pos - STEP_DEG);
    c.servo.write((int)c.pos);
    if ((int)c.pos == c.target) {
      if (c.phase == TO_FLICK) { c.phase = HOLDING; c.t = now; }
      else { c.phase = SETTLE; c.t = now; }
    }
  }
}

// ---------------------------------------------------------------- REST handlers
static void handleInfo() {
  if (!authorised()) return sendErr(401, "bad key");
  JsonDocument d;
  d["name"] = HOST_NAME;
  d["fw"] = FW_VERSION;
  d["servos"] = NUM_SERVOS;
  d["ip"] = WiFi.localIP().toString();
  sendJson(200, d);
}

static void handleStatus() {
  if (!authorised()) return sendErr(401, "bad key");
  JsonDocument d;
  d["ok"] = true;
  d["rssi"] = WiFi.RSSI();
  d["uptime"] = millis() / 1000;
  d["ip"] = WiFi.localIP().toString();
  JsonArray arr = d["servos"].to<JsonArray>();
  for (int i = 0; i < NUM_SERVOS; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["id"] = i;
    o["state"] = ch[i].isOn ? "on" : "off";
    o["busy"] = ch[i].phase != IDLE;
    o["neutral"] = ch[i].neutral;
  }
  sendJson(200, d);
}

static void handleServo() {
  if (!authorised()) return sendErr(401, "bad key");
  if (!server.hasArg("plain")) return sendErr(400, "json body required");
  JsonDocument d;
  if (deserializeJson(d, server.arg("plain"))) return sendErr(400, "bad json");
  int id = d["servo_id"] | -1;
  const char* action = d["action"] | "";
  int angle = d["angle"] | DEFAULT_FLICK;
  if (id < 0 || id >= NUM_SERVOS) return sendErr(400, "servo_id out of range");
  bool on = strcmp(action, "on") == 0;
  if (!on && strcmp(action, "off") != 0) return sendErr(400, "action must be on or off");
  if (ch[id].phase != IDLE) return sendErr(409, "servo busy");
  angle = constrain(angle, 5, 90);
  startFlick(id, on, angle);                         // returns immediately - the loop() moves the arm
  JsonDocument r;
  r["ok"] = true;
  r["servo_id"] = id;
  r["state"] = on ? "on" : "off";
  r["angle"] = angle;
  sendJson(200, r);
}

static void handleCalibrate() {
  if (!authorised()) return sendErr(401, "bad key");
  JsonDocument d;
  if (!server.hasArg("plain") || deserializeJson(d, server.arg("plain"))) return sendErr(400, "bad json");
  int id = d["servo_id"] | -1;
  int neutral = d["neutral"] | -1;
  if (id < 0 || id >= NUM_SERVOS || neutral < 20 || neutral > 160) return sendErr(400, "bad values");
  ch[id].neutral = neutral;
  prefs.putInt(("n" + String(id)).c_str(), neutral);
  JsonDocument r;
  r["ok"] = true;
  r["neutral"] = neutral;
  sendJson(200, r);
}

static void handleRoot() {
  server.send(200, "text/plain", String("Luna ESP32 switch node ") + FW_VERSION + "\nPOST /api/servo {\"servo_id\":0,\"action\":\"on\"}\n");
}

// ---------------------------------------------------------------- Wi-Fi (non-blocking)
static void startWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOST_NAME);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  wifiStart = millis();
}

static void startMdns() {
  if (MDNS.begin(HOST_NAME)) {
    MDNS.addService("http", "tcp", 80);
    MDNS.addService("luna-switch", "tcp", 80);
    MDNS.addServiceTxt("luna-switch", "tcp", "servos", String(NUM_SERVOS));
    mdnsUp = true;
  }
}

static void wifiTask() {
  unsigned long now = millis();
  if (now - lastWifiCheck < 2000) return;
  lastWifiCheck = now;
  if (WiFi.status() == WL_CONNECTED) {
    if (!mdnsUp) { startMdns(); Serial.printf("Online: http://%s.local  (%s)\n", HOST_NAME, WiFi.localIP().toString().c_str()); }
  } else {
    mdnsUp = false;
    if (now - wifiStart > 15000) { WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASS); wifiStart = now; Serial.println("Wi-Fi retry..."); }
  }
}

// ---------------------------------------------------------------- Arduino
void setup() {
  Serial.begin(115200);
  prefs.begin("luna", false);
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  for (int i = 0; i < NUM_SERVOS; i++) {
    ch[i].pin = SERVO_PINS[i];
    ch[i].neutral = prefs.getInt(("n" + String(i)).c_str(), DEFAULT_NEUTRAL[i]);
    ch[i].pos = ch[i].target = ch[i].neutral;
    // the arm is NOT driven at power-up: servos stay detached until the first command (no twitch on boot)
  }
  const char* keys[] = {"X-Luna-Key"};
  server.collectHeaders(keys, 1);
  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/info", HTTP_GET, handleInfo);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/servo", HTTP_POST, handleServo);
  server.on("/api/calibrate", HTTP_POST, handleCalibrate);
  server.onNotFound([]() { sendErr(404, "not found"); });
  server.begin();
  startWifi();
}

void loop() {
  wifiTask();
  server.handleClient();     // quick, never blocks
  updateServos();            // quick, never blocks
}
