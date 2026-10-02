/*
 * MaUWB_DW3000 with STM32 AT Command  (Makerfabs MAUWBCA1)
 * PCB silkscreen: "ESP32 AT UWB Pro with Display v1.1"
 *
 * Phase B firmware: a bridge between USB and the STM32 that does the UWB work.
 *
 * The ESP32 makes no decisions here. Every line from the Mac goes to the STM32,
 * every line from the STM32 comes back to the Mac, and ranging.py does all the
 * talking. Same split as selftest.ino -- the board carries no settings and no
 * rules, so changing the role, the anchor/tag index or the data rate never
 * means reflashing ten boards. (Makerfabs' esp32_at.ino does the opposite:
 * role and index are #defines, one compile per board.)
 *
 * One line is for the bridge itself and is not forwarded:
 *   BRIDGE?   ->   BRIDGE v1 mauwb-dw3000 mac=XX:XX:XX:XX:XX:XX
 * The same line is printed once at boot. The MAC is how ranging.py proves the
 * board on the port is the board you named.
 *
 * Build settings are the same as selftest.ino -- use ./flash.sh bridge.
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <esp_mac.h>

// ---- ESP32-WROVER-B pin map (same as selftest.ino) ---------------------
#define PIN_STM32_RESET 32     // held HIGH. The module only resets when this
                               // is held LOW for ~3 s (AT manual, section 2.6)
#define PIN_RXD2        18     // ESP32 receives from STM32
#define PIN_TXD2        19     // ESP32 transmits to STM32
#define PIN_I2C_SDA      4
#define PIN_I2C_SCL      5

#define OLED_ADDR     0x3C
#define AT_BAUD       115200

HardwareSerial AT(2);
Adafruit_SSD1306 display(128, 64, &Wire, -1);

String banner;
String fromMac, fromStm;      // one partial line per direction

// Add one character to a line buffer; true once the line is complete.
// '\r' is dropped, so a line ends at '\n' whatever line ending the sender used.
bool feed(String &line, char c) {
  if (c == '\r') return false;
  if (c == '\n') return true;
  line += c;
  return false;
}

void setup() {
  pinMode(PIN_STM32_RESET, OUTPUT);
  digitalWrite(PIN_STM32_RESET, HIGH);

  Serial.begin(115200);
  AT.begin(AT_BAUD, SERIAL_8N1, PIN_RXD2, PIN_TXD2);

  // Base MAC from eFuse: always readable, and the chip's real identity
  // (WiFi.macAddress() reads zeros until the WiFi stack is up).
  uint8_t m[6];
  esp_efuse_mac_get_default(m);
  char mac[18];
  snprintf(mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X",
           m[0], m[1], m[2], m[3], m[4], m[5]);
  banner = String("BRIDGE v1 mauwb-dw3000 mac=") + mac;

  // The screen says which firmware is on the board -- with ten identical
  // boards moving between phases, that is the first thing you need to know.
  // A dead screen is not a reason to stop: the bridge works without it.
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  if (display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(2);
    display.setCursor(0, 0);
    display.println(F("UWB"));
    display.println(F("BRIDGE"));
    display.setTextSize(1);
    display.setCursor(0, 48);
    display.println(mac);
    display.display();
  }

  delay(200);
  Serial.println();
  Serial.println(banner);
}

void loop() {
  // Whole lines in both directions, so the banner can never land in the
  // middle of a distance report.
  while (Serial.available()) {
    if (!feed(fromMac, Serial.read())) continue;
    if (fromMac == "BRIDGE?") Serial.println(banner);
    else if (fromMac.length()) AT.println(fromMac);
    fromMac = "";
  }
  while (AT.available()) {
    if (!feed(fromStm, AT.read())) continue;
    if (fromStm.length()) Serial.println(fromStm);
    fromStm = "";
  }
}
