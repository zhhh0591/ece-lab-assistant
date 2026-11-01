// Function self-test for a Seeed XIAO nRF52840 (step 8 of the Test Procedure).
//
// Board package: "Seeed nRF52 Boards" (the non-mbed one, which carries the
// Bluefruit BLE library). Flash with ../flash.sh so every XIAO is built the
// same way.
//
// The checks run once at boot and the report is kept. Every "T" from the Mac
// (selftest.py sends it) cycles the RGB LED red, green, blue for a person to
// watch, then prints the report:
//
//   SELFTEST-BEGIN v1 xiao-nrf52840
//   CHIP part=52840 variant=AAD0 flash_kb=1024 ram_kb=256
//   ADDR id=XX:XX:XX:XX:XX:XX
//   VBUS detect=1 outputrdy=1
//   VDD v=3.31
//   HFCLK running=1 src=xtal
//   LFCLK running=1 src=xtal
//   BLE reports=37 devices=9 best_rssi=-52
//   LED cycle=rgb
//   SELFTEST-END
//
// The clock and power registers are read before Bluefruit starts the
// SoftDevice, because after that the SoftDevice owns them.

#include <bluefruit.h>

static String report;

static void kv(const char *key, const String &val) {
  report += key;
  report += ' ';
  report += val;
  report += '\n';
}

// ---- chip identity, from the factory information registers --------------
static void testChip() {
  uint32_t v = NRF_FICR->INFO.VARIANT;
  char variant[5] = {(char)(v >> 24), (char)(v >> 16), (char)(v >> 8), (char)v, 0};
  kv("CHIP", String("part=") + String(NRF_FICR->INFO.PART, HEX) +
                 " variant=" + variant +
                 " flash_kb=" + NRF_FICR->INFO.FLASH +
                 " ram_kb=" + NRF_FICR->INFO.RAM);

  // A unique address burned in at the factory: this board's serial number,
  // the same job the MAC address does for the MaUWB boards.
  uint64_t a = ((uint64_t)(NRF_FICR->DEVICEADDR[1] & 0xFFFF) << 32) | NRF_FICR->DEVICEADDR[0];
  a |= 0xC00000000000ULL;                     // static random address: top two bits set
  char id[18];
  snprintf(id, sizeof id, "%02X:%02X:%02X:%02X:%02X:%02X",
           (int)(a >> 40) & 0xFF, (int)(a >> 32) & 0xFF, (int)(a >> 24) & 0xFF,
           (int)(a >> 16) & 0xFF, (int)(a >> 8) & 0xFF, (int)a & 0xFF);
  kv("ADDR", String("id=") + id);
}

// ---- USB power: does the chip see 5 V on its VBUS pin? -------------------
static void testVbus() {
  uint32_t s = NRF_POWER->USBREGSTATUS;
  kv("VBUS", String("detect=") + ((s & POWER_USBREGSTATUS_VBUSDETECT_Msk) ? 1 : 0) +
                 " outputrdy=" + ((s & POWER_USBREGSTATUS_OUTPUTRDY_Msk) ? 1 : 0));
}

// ---- the 3.3 V rail, measured by the chip's own ADC ---------------------
// Gain 1/6 with the 0.6 V internal reference gives a 3.6 V full scale.
static void testVdd() {
  volatile int16_t result = 0;
  NRF_SAADC->RESOLUTION = SAADC_RESOLUTION_VAL_12bit;
  NRF_SAADC->CH[0].CONFIG = (SAADC_CH_CONFIG_GAIN_Gain1_6 << SAADC_CH_CONFIG_GAIN_Pos) |
                            (SAADC_CH_CONFIG_REFSEL_Internal << SAADC_CH_CONFIG_REFSEL_Pos) |
                            (SAADC_CH_CONFIG_TACQ_10us << SAADC_CH_CONFIG_TACQ_Pos);
  NRF_SAADC->CH[0].PSELP = SAADC_CH_PSELP_PSELP_VDD;
  NRF_SAADC->CH[0].PSELN = SAADC_CH_PSELN_PSELN_NC;
  NRF_SAADC->RESULT.PTR = (uint32_t)&result;
  NRF_SAADC->RESULT.MAXCNT = 1;
  NRF_SAADC->ENABLE = 1;

  NRF_SAADC->EVENTS_STARTED = 0;
  NRF_SAADC->TASKS_START = 1;
  while (!NRF_SAADC->EVENTS_STARTED) {}
  NRF_SAADC->EVENTS_END = 0;
  NRF_SAADC->TASKS_SAMPLE = 1;
  while (!NRF_SAADC->EVENTS_END) {}
  NRF_SAADC->EVENTS_STOPPED = 0;
  NRF_SAADC->TASKS_STOP = 1;
  while (!NRF_SAADC->EVENTS_STOPPED) {}
  NRF_SAADC->ENABLE = 0;

  float v = (result < 0 ? 0 : result) * 3.6f / 4096.0f;
  kv("VDD", String("v=") + String(v, 2));
}

// ---- the two crystals ----------------------------------------------------
// USB needs the 32 MHz crystal, so it is normally running already; if not,
// ask for it and wait. The 32.768 kHz clock is started by the core; its
// source says whether the board's crystal or the internal RC is in use.
static void testClocks() {
  uint32_t hf = NRF_CLOCK->HFCLKSTAT;
  if (!(hf & CLOCK_HFCLKSTAT_STATE_Msk) ||
      ((hf & CLOCK_HFCLKSTAT_SRC_Msk) >> CLOCK_HFCLKSTAT_SRC_Pos) != CLOCK_HFCLKSTAT_SRC_Xtal) {
    NRF_CLOCK->EVENTS_HFCLKSTARTED = 0;
    NRF_CLOCK->TASKS_HFCLKSTART = 1;
    uint32_t t0 = millis();
    while (!NRF_CLOCK->EVENTS_HFCLKSTARTED && millis() - t0 < 500) {}
    hf = NRF_CLOCK->HFCLKSTAT;
  }
  bool hfXtal = ((hf & CLOCK_HFCLKSTAT_SRC_Msk) >> CLOCK_HFCLKSTAT_SRC_Pos) == CLOCK_HFCLKSTAT_SRC_Xtal;
  kv("HFCLK", String("running=") + ((hf & CLOCK_HFCLKSTAT_STATE_Msk) ? 1 : 0) +
                  " src=" + (hfXtal ? "xtal" : "rc"));

  uint32_t lf = NRF_CLOCK->LFCLKSTAT;
  uint32_t src = (lf & CLOCK_LFCLKSTAT_SRC_Msk) >> CLOCK_LFCLKSTAT_SRC_Pos;
  const char *name = src == CLOCK_LFCLKSTAT_SRC_Xtal ? "xtal"
                   : src == CLOCK_LFCLKSTAT_SRC_RC   ? "rc" : "synth";
  kv("LFCLK", String("running=") + ((lf & CLOCK_LFCLKSTAT_STATE_Msk) ? 1 : 0) + " src=" + name);
}

// ---- the 2.4 GHz radio: listen for BLE advertisers for 5 s --------------
// Phones, laptops and watches advertise all the time, so any working radio
// and antenna in a lab hears some. Same idea as the MaUWB's WiFi scan.
static const int MAX_PEERS = 64;
static uint8_t peers[MAX_PEERS][6];
static volatile int nReports = 0, nPeers = 0, bestRssi = -127;

static void onAdvert(ble_gap_evt_adv_report_t *r) {
  nReports++;
  if (r->rssi > bestRssi) bestRssi = r->rssi;
  bool seen = false;
  for (int i = 0; i < nPeers && !seen; i++) seen = memcmp(peers[i], r->peer_addr.addr, 6) == 0;
  if (!seen && nPeers < MAX_PEERS) memcpy(peers[nPeers++], r->peer_addr.addr, 6);
  Bluefruit.Scanner.resume();
}

static void testBle() {
  Bluefruit.autoConnLed(false);               // else Bluefruit drives the blue LED itself
  Bluefruit.begin(0, 1);                      // no peripheral links, one central
  Bluefruit.Scanner.setRxCallback(onAdvert);
  Bluefruit.Scanner.setInterval(160, 80);     // listen 50 ms of every 100 ms (0.625 ms units)
  Bluefruit.Scanner.useActiveScan(false);
  Bluefruit.Scanner.start(0);
  delay(5000);
  Bluefruit.Scanner.stop();
  kv("BLE", String("reports=") + nReports + " devices=" + nPeers + " best_rssi=" + bestRssi);
}

// ---- the RGB LED: active low (common anode), watched by a person --------
static void ledOff() {
  digitalWrite(LED_RED, HIGH);
  digitalWrite(LED_GREEN, HIGH);
  digitalWrite(LED_BLUE, HIGH);
}

static void cycleLed() {
  const int pins[] = {LED_RED, LED_GREEN, LED_BLUE};
  for (int p : pins) {
    ledOff();
    digitalWrite(p, LOW);
    delay(700);
  }
  ledOff();
}

void setup() {
  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  ledOff();
  Serial.begin(115200);

  testChip();
  testVbus();
  testVdd();
  testClocks();
  testBle();                                  // last: it starts the SoftDevice
  kv("LED", "cycle=rgb");
}

void loop() {
  if (Serial.available() && toupper(Serial.read()) == 'T') {
    cycleLed();
    Serial.println();
    Serial.println("SELFTEST-BEGIN v1 xiao-nrf52840");
    Serial.print(report);
    Serial.println("SELFTEST-END");
  }
}
