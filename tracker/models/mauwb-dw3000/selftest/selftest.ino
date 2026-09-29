/*
 * MaUWB_DW3000 with STM32 AT Command  (Makerfabs MAUWBCA1)
 * PCB silkscreen: "ESP32 AT UWB Pro with Display v1.1"
 * MCU: ESP32-WROVER-B      UWB: STM32F103 + DW3000
 *
 * Incoming-inspection self test. Runs on boot and again whenever the host
 * sends 'T'. Prints facts, not verdicts -- the host script applies the limits.
 * Same split as the rest of this repo: measurement and rules stay separate, so
 * a limit change never means reflashing ten boards.
 *
 * Arduino IDE setup, all three matter:
 *   Board:  "ESP32 Dev Module"     (NOT an S3 board -- this is a WROVER-B)
 *   PSRAM:  "Enabled"              <- if you forget, PSRAM reads 0 and a
 *                                     perfectly good board reports FAIL
 *   Libraries: Adafruit_SSD1306, Adafruit_GFX, Wire
 */

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <esp_flash.h>
#include <esp_mac.h>

// ---- ESP32-WROVER-B pin map -------------------------------------------
// From Makerfabs' own serial_test.ino. Note their esp32_at.ino ships with
// the ESP32-S3 pins active and these commented out -- flash that unchanged
// and every board looks dead.
#define PIN_STM32_RESET 32
#define PIN_RXD2        18     // ESP32 receives from STM32
#define PIN_TXD2        19     // ESP32 transmits to STM32
#define PIN_I2C_SDA      4
#define PIN_I2C_SCL      5

#define OLED_ADDR     0x3C
#define AT_BAUD       115200

HardwareSerial AT(2);
Adafruit_SSD1306 display(128, 64, &Wire, -1);

// ---------------------------------------------------------------------

void kv(const char *key, const String &val) {
  Serial.print(key); Serial.print(' '); Serial.println(val);
}

// Drain anything the STM32 left in the buffer so one test's tail does not
// get read as the next test's response.
void flushAT() {
  while (AT.available()) AT.read();
}

String askAT(const char *cmd, uint32_t timeout_ms) {
  flushAT();
  AT.println(cmd);
  String resp = "";
  uint32_t t0 = millis();
  while (millis() - t0 < timeout_ms) {
    while (AT.available()) {
      char c = AT.read();
      if (c == '\r') continue;
      resp += (c == '\n') ? '|' : c;      // one line out, | as separator
    }
  }
  resp.trim();
  return resp;
}

void testChip() {
  kv("CHIP", String("model=") + ESP.getChipModel()
           + " rev=" + ESP.getChipRevision()
           + " cores=" + ESP.getChipCores()
           + " mhz=" + getCpuFrequencyMhz());
  // ESP.getFlashChipSize() reports what the bootloader header says -- i.e. the
  // build setting, not the part. A 16 MB board built with a 4 MB setting would
  // answer "4 MB" and we would be testing our own compile flags. Ask the chip
  // for its JEDEC id instead; byte 3 is the capacity exponent.
  uint32_t jedec = 0;
  esp_flash_read_id(NULL, &jedec);
  uint8_t cap = jedec & 0xFF;
  uint32_t real = (cap >= 0x10 && cap <= 0x1A) ? (1u << cap) : 0;   // 64 KB..64 MB
  kv("FLASH", String("real_bytes=") + real
            + " cfg_bytes=" + ESP.getFlashChipSize()
            + " jedec=0x" + String(jedec, HEX));
  // WROVER-B carries 8 MB PSRAM. 0 here means either dead PSRAM or, far more
  // often, PSRAM left disabled in the board menu.
  kv("PSRAM", String("bytes=") + ESP.getPsramSize());
  // WiFi.macAddress() returns 00:00:00:00:00:00 until the WiFi stack is up,
  // and the WiFi test runs after this one. Read the base MAC straight out of
  // eFuse instead -- always available, and it is the chip's real identity.
  uint8_t m[6];
  esp_efuse_mac_get_default(m);
  char macbuf[18];
  snprintf(macbuf, sizeof(macbuf), "%02X:%02X:%02X:%02X:%02X:%02X",
           m[0], m[1], m[2], m[3], m[4], m[5]);
  kv("MAC", String(macbuf));             // per-board serial number, free
}

void testI2C() {
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  String found = "";
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      if (n++) found += ",";
      found += "0x" + String(a, HEX);
    }
  }
  kv("I2C", String("count=") + n + " addrs=" + (n ? found : "none"));
}

void testOLED() {
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    kv("OLED", "init=fail");
    return;
  }
  kv("OLED", "init=ok");

  // All pixels on for a moment: dead rows, dead columns and a dim panel are
  // only visible against full white, never against text.
  display.clearDisplay();
  display.fillRect(0, 0, 128, 64, SSD1306_WHITE);
  display.display();
  delay(1200);

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("SELFTEST"));
  display.println(WiFi.macAddress());
  display.drawRect(0, 22, 128, 42, SSD1306_WHITE);   // border = edge columns
  for (int x = 2; x < 126; x += 4)                   // stripes = stuck columns
    display.drawFastVLine(x, 24, 38, SSD1306_WHITE);
  display.display();
}

void testSTM32() {
  // Hardware reset the UWB subsystem, then see if it talks.
  pinMode(PIN_STM32_RESET, OUTPUT);
  digitalWrite(PIN_STM32_RESET, LOW);
  delay(50);
  digitalWrite(PIN_STM32_RESET, HIGH);
  delay(1500);                                  // STM32 boot
  kv("STM32RESET", "asserted=ok");

  String r = askAT("AT?", 2000);
  kv("STM32AT", String("resp=\"") + r + "\"");

  // Config readback. Not on every firmware version; empty is a note, not a
  // failure -- the host decides which of these matter.
  kv("STM32CFG", String("resp=\"") + askAT("AT+CFG", 1500) + "\"");
}

void testWiFi() {
  // Proves the 2.4 GHz chain: PCB antenna, matching, ESP32 radio.
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  int n = WiFi.scanNetworks();
  int best = -127;
  for (int i = 0; i < n; i++) best = max(best, (int)WiFi.RSSI(i));
  kv("WIFI", String("networks=") + n + " best_rssi=" + (n > 0 ? best : -127));
  WiFi.scanDelete();
}

void runAll() {
  Serial.println();
  Serial.println("SELFTEST-BEGIN v1 mauwb-dw3000");
  testChip();
  testI2C();
  testOLED();
  testSTM32();
  testWiFi();
  Serial.println("SELFTEST-END");
}

void setup() {
  Serial.begin(115200);
  AT.begin(AT_BAUD, SERIAL_8N1, PIN_RXD2, PIN_TXD2);
  delay(400);
  runAll();
}

void loop() {
  if (Serial.available() && toupper(Serial.read()) == 'T') runAll();
}
