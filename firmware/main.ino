/*
 * ==============================================================================
 * SMART TRAFFIC VIOLATION DETECTION SYSTEM - ESP32-S3 SENSE FIRMWARE
 * Group 36 | PC122 Project | Mentor: P S Kalyan Sasidhar
 * ==============================================================================
 * Hardware Pinout (Aligned with Circuit Diagram - Page 9 of Project Report):
 * ------------------------------------------------------------------------------
 *  Controller: Seeed Studio XIAO ESP32-S3 Sense (with OV2640 Camera & MicroSD)
 *
 *  Sensors:
 *   - HC-SR04 Ultrasonic Sensor:
 *       VCC       -> 5V
 *       GND       -> GND
 *       Trig      -> D0 (GPIO 1)
 *       Echo (5V) -> Voltage divider (R1=1kΩ, R2=2kΩ) -> D1 (GPIO 2 - 3.3V safe)
 *
 *   - IR Obstacle Sensor:
 *       VCC       -> 3.3V
 *       GND       -> GND
 *       OUT       -> D2 (GPIO 3)
 *
 *   - 16GB MicroSD Module (SPI):
 *       CS        -> D5 (GPIO 6)
 *       SCK       -> D8 (GPIO 7)
 *       MISO      -> D7 (GPIO 8)
 *       MOSI      -> D6 (GPIO 9)
 *
 *  2-Stage Event Workflow:
 *   1. HC-SR04 & IR sensor detect vehicle entering restricted right-turn circle path.
 *   2. Register Event: POST /api/v1/events (with sensor readings and device ID).
 *   3. Capture OV2640 frame and backup to 16GB MicroSD card.
 *   4. Upload Image: POST /api/v1/events/{event_id}/images (multipart/form-data).
 *   5. Backend stages incident for human review and plate OCR.
 * ==============================================================================
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// ------------------------------------------------------------------------------
// Pin Definitions (XIAO ESP32S3 Pin Mapping)
// ------------------------------------------------------------------------------
#define TRIG_PIN         D0    // HC-SR04 Trigger
#define ECHO_PIN         D1    // HC-SR04 Echo (via voltage divider)
#define IR_SENSOR_PIN    D2    // IR Obstacle Sensor Output (Active LOW)
#define SD_CS_PIN        D5    // MicroSD Chip Select

#define LED_STATUS_PIN   21    // Onboard user LED indicator

// Detection Thresholds
#define VEHICLE_DISTANCE_THRESHOLD_CM  45.0  // Distance below which vehicle is in restricted zone
#define SENSOR_COOLDOWN_MS             5000  // Avoid multi-triggering for same vehicle

// ------------------------------------------------------------------------------
// Wi-Fi and Backend API Configuration
// ------------------------------------------------------------------------------
#ifndef WIFI_SSID
  #define WIFI_SSID     "Campus_WiFi"
#endif
#ifndef WIFI_PASSWORD
  #define WIFI_PASSWORD "Campus_Password"
#endif

// IP address of computer running FastAPI
const char* apiBaseUrl = "http://192.168.1.100:8000/api/v1/events";

// ------------------------------------------------------------------------------
// XIAO ESP32S3 Sense OV2640 Camera Pinout
// ------------------------------------------------------------------------------
#define CAMERA_MODEL_XIAO_ESP32S3
#define PWDN_GPIO_NUM     -1
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM     10
#define SIOD_GPIO_NUM     40
#define SIOC_GPIO_NUM     39
#define Y9_GPIO_NUM       48
#define Y8_GPIO_NUM       11
#define Y7_GPIO_NUM       12
#define Y6_GPIO_NUM       14
#define Y5_GPIO_NUM       16
#define Y4_GPIO_NUM       18
#define Y3_GPIO_NUM       17
#define Y2_GPIO_NUM       15
#define VSYNC_GPIO_NUM    38
#define HREF_GPIO_NUM     47
#define PCLK_GPIO_NUM     13

// ------------------------------------------------------------------------------
// Global State
// ------------------------------------------------------------------------------
unsigned long lastTriggerTime = 0;
bool sdCardAvailable = false;
uint32_t captureCounter = 0;

// ------------------------------------------------------------------------------
// Function Prototypes
// ------------------------------------------------------------------------------
bool initCamera();
bool initMicroSD();
void connectToWiFi();
float measureDistanceCm();
bool isVehicleViolating();
void processViolationEvent(float distanceCm, int irVal);
String registerEventOnBackend(float distanceCm, int irVal);
bool uploadFrameToEvent(String eventId, camera_fb_t* fb);
bool saveFrameToSD(camera_fb_t* fb, String filepath);
void blinkStatus(int flashes, int delayMs);

// ------------------------------------------------------------------------------
// Setup
// ------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n======================================================="));
  Serial.println(F("   SMART TRAFFIC VIOLATION DETECTION - FIRMWARE v0.3   "));
  Serial.println(F("   Group 36 | PC122 | Seeed XIAO ESP32-S3 Sense       "));
  Serial.println(F("=======================================================\n"));

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(IR_SENSOR_PIN, INPUT);
  pinMode(LED_STATUS_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(LED_STATUS_PIN, LOW);

  // Initialize MicroSD
  sdCardAvailable = initMicroSD();

  // Initialize OV2640 camera
  if (!initCamera()) {
    Serial.println(F("[ERROR] Camera initialization failed!"));
    while (true) { blinkStatus(4, 150); delay(1000); }
  }
  Serial.println(F("[OK] OV2640 Camera initialized successfully."));

  // Connect to Wi-Fi
  connectToWiFi();

  Serial.println(F("[READY] Monitoring restricted right-turn circle path...\n"));
}

// ------------------------------------------------------------------------------
// Main Loop
// ------------------------------------------------------------------------------
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  if (millis() - lastTriggerTime > SENSOR_COOLDOWN_MS) {
    float dist = measureDistanceCm();
    int ir = digitalRead(IR_SENSOR_PIN);

    bool ultrasonicTrigger = (dist > 2.0 && dist <= VEHICLE_DISTANCE_THRESHOLD_CM);
    bool irTrigger = (ir == LOW);

    if (ultrasonicTrigger || irTrigger) {
      Serial.printf("[ALERT] Violation Triggered! Dist: %.1f cm, IR: %d\n", dist, ir);
      lastTriggerTime = millis();
      processViolationEvent(dist, ir);
    }
  }

  delay(100);
}

// ------------------------------------------------------------------------------
// Sensor Measurement
// ------------------------------------------------------------------------------
float measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration <= 0) return 999.0;
  return (duration * 0.0343) / 2.0;
}

// ------------------------------------------------------------------------------
// 2-Stage Event & Image Processing
// ------------------------------------------------------------------------------
void processViolationEvent(float distanceCm, int irVal) {
  blinkStatus(1, 100);

  // Stage 1: Register Event
  String eventId = registerEventOnBackend(distanceCm, irVal);
  if (eventId.length() == 0) {
    Serial.println(F("[ERROR] Failed to register event on backend."));
    return;
  }
  Serial.printf("[STAGE 1 OK] Registered event ID: %s\n", eventId.c_str());

  // Stage 2: Capture Frame
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println(F("[ERROR] Camera capture failed."));
    return;
  }

  captureCounter++;
  String filename = "/captures/" + eventId + "_" + String(captureCounter) + ".jpg";

  // MicroSD Local Backup
  if (sdCardAvailable) {
    saveFrameToSD(fb, filename);
  }

  // Stage 3: Upload Frame
  uploadFrameToEvent(eventId, fb);

  esp_camera_fb_return(fb);
}

// ------------------------------------------------------------------------------
// Register Event on Backend (Stage 1)
// ------------------------------------------------------------------------------
String registerEventOnBackend(float distanceCm, int irVal) {
  if (WiFi.status() != WL_CONNECTED) return "";

  HTTPClient http;
  http.begin(apiBaseUrl);
  http.addHeader("Content-Type", "application/json");

  JsonDocument doc;
  doc["device_id"] = "ESP32S3-CAM-01";
  doc["location"] = "Lotus Pond Road Circle";
  doc["sensor_data"] = "Ultrasonic: " + String(distanceCm, 1) + "cm | IR: " + (irVal == LOW ? "TRIGGERED" : "CLEAR");

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  int code = http.POST(jsonPayload);
  String eventId = "";

  if (code == 201 || code == 200) {
    String resp = http.getString();
    JsonDocument resDoc;
    deserializeJson(resDoc, resp);
    eventId = (const char*)resDoc["event_id"];
  } else {
    Serial.printf("[ERROR] Register event failed, HTTP: %d\n", code);
  }

  http.end();
  return eventId;
}

// ------------------------------------------------------------------------------
// Upload Frame to Event (Stage 2)
// ------------------------------------------------------------------------------
bool uploadFrameToEvent(String eventId, camera_fb_t* fb) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  String uploadUrl = String(apiBaseUrl) + "/" + eventId + "/images";
  http.begin(uploadUrl);

  String boundary = "----ESP32S3BoundaryXYZ";
  String head = "--" + boundary + "\r\n" +
                "Content-Disposition: form-data; name=\"file\"; filename=\"capture.jpg\"\r\n" +
                "Content-Type: image/jpeg\r\n\r\n";
  String tail = "\r\n--" + boundary + "--\r\n";

  uint32_t totalLen = head.length() + fb->len + tail.length();
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  http.addHeader("Content-Length", String(totalLen));

  uint8_t* buf = (uint8_t*)malloc(totalLen);
  if (!buf) {
    http.end();
    return false;
  }

  memcpy(buf, head.c_str(), head.length());
  memcpy(buf + head.length(), fb->buf, fb->len);
  memcpy(buf + head.length() + fb->len, tail.c_str(), tail.length());

  int code = http.POST(buf, totalLen);
  free(buf);

  if (code == 200) {
    Serial.printf("[STAGE 2 OK] Frame successfully uploaded for event %s!\n", eventId.c_str());
    blinkStatus(2, 100);
  } else {
    Serial.printf("[ERROR] Image upload failed, HTTP: %d\n", code);
  }

  http.end();
  return (code == 200);
}

// ------------------------------------------------------------------------------
// Camera Initialization
// ------------------------------------------------------------------------------
bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_VGA;
  config.jpeg_quality = 12;
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_LATEST;

  return (esp_camera_init(&config) == ESP_OK);
}

// ------------------------------------------------------------------------------
// MicroSD Initialization
// ------------------------------------------------------------------------------
bool initMicroSD() {
  SPI.begin(D8, D7, D6, SD_CS_PIN);
  if (!SD.begin(SD_CS_PIN)) {
    Serial.println(F("[WARN] MicroSD mount failed. Continuing with RAM buffer."));
    return false;
  }
  if (!SD.exists("/captures")) {
    SD.mkdir("/captures");
  }
  Serial.println(F("[OK] 16GB MicroSD mounted."));
  return true;
}

// ------------------------------------------------------------------------------
// Save Frame to MicroSD
// ------------------------------------------------------------------------------
bool saveFrameToSD(camera_fb_t* fb, String filepath) {
  File file = SD.open(filepath.c_str(), FILE_WRITE);
  if (!file) return false;
  file.write(fb->buf, fb->len);
  file.close();
  return true;
}

// ------------------------------------------------------------------------------
// Status LED Helper
// ------------------------------------------------------------------------------
void blinkStatus(int flashes, int delayMs) {
  for (int i = 0; i < flashes; i++) {
    digitalWrite(LED_STATUS_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_STATUS_PIN, LOW);
    delay(delayMs);
  }
}
