#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <Preferences.h>
#include "USB.h"
#include "USBHIDKeyboard.h"
#define FW_VERSION "1.0.0"

// ==========================================
//               CONFIGURATION
// ==========================================
#define PIN_JOY_X 4
#define PIN_JOY_Y 5

// Heltec V3 OLED Pins
#define OLED_SDA 17
#define OLED_SCL 18
#define OLED_RST 21

// Default Values
#define DEFAULT_DEADZONE 0.15f  // 15% Radial Deadzone

// ==========================================
//               OBJECTS & GLOBALS
// ==========================================
// Display: HW I2C for Heltec V3
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R2, OLED_RST, OLED_SCL, OLED_SDA);

Preferences prefs;
USBHIDKeyboard Keyboard;

// State Machine
enum SystemState {
  STATE_RUNNING,
  STATE_CALIBRATING_CENTER,
  STATE_CALIBRATING_EXTREMES,
  STATE_VISUALIZE
};

SystemState currentState = STATE_RUNNING;
bool debugMode = false;

// Data Structure for Calibration
struct JoystickConfig {
  int minX = 0;
  int maxX = 4095;
  int centerX = 2048;
  int minY = 0;
  int maxY = 4095;
  int centerY = 2048;
  float deadzone = DEFAULT_DEADZONE;
} joyConfig;

// Runtime Variables
float normX = 0.0f;
float normY = 0.0f;
float magnitude = 0.0f;
float angle = 0.0f;

// 8-Way Direction Tracking
String currentDirLabel = "NEUTRAL";

// ==========================================
//               SETUP
// ==========================================
void loadCalibration() {
  prefs.begin("joystick", true);  // Read-only mode first
  joyConfig.minX = prefs.getInt("minX", 0);
  joyConfig.maxX = prefs.getInt("maxX", 4095);
  joyConfig.centerX = prefs.getInt("centerX", 2048);
  joyConfig.minY = prefs.getInt("minY", 0);
  joyConfig.maxY = prefs.getInt("maxY", 4095);
  joyConfig.centerY = prefs.getInt("centerY", 2048);
  joyConfig.deadzone = prefs.getFloat("deadzone", DEFAULT_DEADZONE);
  prefs.end();
}

void saveCalibration() {
  prefs.begin("joystick", false);  // Read-write mode
  prefs.putInt("minX", joyConfig.minX);
  prefs.putInt("maxX", joyConfig.maxX);
  prefs.putInt("centerX", joyConfig.centerX);
  prefs.putInt("minY", joyConfig.minY);
  prefs.putInt("maxY", joyConfig.maxY);
  prefs.putInt("centerY", joyConfig.centerY);
  prefs.putFloat("deadzone", joyConfig.deadzone);
  prefs.end();
  Serial.println("Calibration Saved to Flash!");
}

void setup() {
  Serial.begin(115200);

  // Initialize I2C for Heltec V3
  Wire.begin(OLED_SDA, OLED_SCL);

  u8g2.begin();
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tf);
  u8g2.drawStr(10, 30, "Booting HID Joy...");
  u8g2.sendBuffer();

  // Initialize HID
  Keyboard.begin();
  USB.begin();

  // Pin Setup
  pinMode(PIN_JOY_X, INPUT);
  pinMode(PIN_JOY_Y, INPUT);
  analogReadResolution(12);  // 0-4095

  loadCalibration();
  delay(1000);
}

// ==========================================
//               LOGIC HANDLERS
// ==========================================

void readJoystick() {
  int rawX = analogRead(PIN_JOY_X);
  int rawY = analogRead(PIN_JOY_Y);

  // 1. Normalize to -1.0 to 1.0 based on calibration
  float nX, nY;

  if (rawX >= joyConfig.centerX)
    nX = (float)(rawX - joyConfig.centerX) / (joyConfig.maxX - joyConfig.centerX);
  else
    nX = -(float)(joyConfig.centerX - rawX) / (joyConfig.centerX - joyConfig.minX);

  if (rawY >= joyConfig.centerY)
    nY = (float)(rawY - joyConfig.centerY) / (joyConfig.maxY - joyConfig.centerY);
  else
    nY = -(float)(joyConfig.centerY - rawY) / (joyConfig.centerY - joyConfig.minY);

  // Clamp
  nX = constrain(nX, -1.0f, 1.0f);
  nY = constrain(nY, -1.0f, 1.0f);

  // 2. Radial Deadzone Calculation
  // Calculate magnitude (distance from center)
  float rad = sqrt(nX * nX + nY * nY);

  // Apply Deadzone
  if (rad < joyConfig.deadzone) {
    normX = 0.0f;
    normY = 0.0f;
    magnitude = 0.0f;
  } else {
    // Rescale the remaining range to 0.0 - 1.0 for smooth control
    float scaledRad = (rad - joyConfig.deadzone) / (1.0f - joyConfig.deadzone);
    scaledRad = constrain(scaledRad, 0.0f, 1.0f);

    // Preserve angle
    normX = (nX / rad) * scaledRad;
    normY = (nY / rad) * scaledRad;
    magnitude = scaledRad;
  }

  // 3. Calculate Angle (in degrees)
  angle = atan2(normY, normX) * 180.0 / PI;
  if (angle < 0) angle += 360;
}

void handleWASD() {
  // Logic for 8-way directional pad
  // Sectors are 45 degrees each. 360 / 8 = 45.
  // Offset by 22.5 to center the cardinal directions.

  bool w = false, a = false, s = false, d = false;
  currentDirLabel = "NEUTRAL";

  if (magnitude > 0.1) {
    // Angle 0 is usually Right (East) on Cartesian plane
    // Adjust based on joystick orientation. Assuming standard: Y+ is Down/Up?, X+ is Right.
    // Usually: X0=Left, X4095=Right. Y0=Up, Y4095=Down.

    // Determine sector
    if (angle >= 337.5 || angle < 22.5) {
      d = true;
      currentDirLabel = "RIGHT";
    } else if (angle >= 22.5 && angle < 67.5) {
      d = true;
      s = true;
      currentDirLabel = "DOWN-RIGHT";
    } else if (angle >= 67.5 && angle < 112.5) {
      s = true;
      currentDirLabel = "DOWN";
    } else if (angle >= 112.5 && angle < 157.5) {
      s = true;
      a = true;
      currentDirLabel = "DOWN-LEFT";
    } else if (angle >= 157.5 && angle < 202.5) {
      a = true;
      currentDirLabel = "LEFT";
    } else if (angle >= 202.5 && angle < 247.5) {
      a = true;
      w = true;
      currentDirLabel = "UP-LEFT";
    } else if (angle >= 247.5 && angle < 292.5) {
      w = true;
      currentDirLabel = "UP";
    } else if (angle >= 292.5 && angle < 337.5) {
      w = true;
      d = true;
      currentDirLabel = "UP-RIGHT";
    }
  }

  // Send Key States
  if (w) Keyboard.press('w');
  else Keyboard.release('w');
  if (a) Keyboard.press('a');
  else Keyboard.release('a');
  if (s) Keyboard.press('s');
  else Keyboard.release('s');
  if (d) Keyboard.press('d');
  else Keyboard.release('d');
}

// ==========================================
//               DISPLAY DRAWING
// ==========================================
void drawRunning() {
  u8g2.setFont(u8g2_font_profont12_tf);
  u8g2.setCursor(0, 10);
  u8g2.print("Mode: RUN");

  u8g2.setFont(u8g2_font_profont17_tf);
  int strWidth = u8g2.getStrWidth(currentDirLabel.c_str());
  u8g2.setCursor((128 - strWidth) / 2, 40);
  u8g2.print(currentDirLabel);

  // Small debug info at bottom
  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.setCursor(0, 60);
  u8g2.print("X:");
  u8g2.print(normX);
  u8g2.print(" Y:");
  u8g2.print(normY);
}

void drawVisualizer() {
  // Center of screen
  int cx = 64;
  int cy = 32;
  int r = 30;

  // Draw Outer Ring
  u8g2.drawCircle(cx, cy, r, U8G2_DRAW_ALL);

  // Draw Deadzone Ring (Visual representation)
  int dr = r * joyConfig.deadzone;
  if (dr < 2) dr = 2;
  u8g2.drawCircle(cx, cy, dr, U8G2_DRAW_ALL);

  // Draw Stick Position
  // Map -1.0/1.0 to -r/r
  int px = cx + (normX * r);
  int py = cy + (normY * r);

  u8g2.drawDisc(px, py, 2, U8G2_DRAW_ALL);
  u8g2.drawLine(cx, cy, px, py);

  u8g2.setFont(u8g2_font_micro_tr);
  u8g2.setCursor(0, 64);
  u8g2.print("Deadzone Visualizer");
}

void drawCalibration() {
  u8g2.setFont(u8g2_font_6x10_tf);
  if (currentState == STATE_CALIBRATING_CENTER) {
    u8g2.drawStr(5, 20, "CALIBRATION WIZARD");
    u8g2.drawStr(5, 40, "1. Center Stick");
    u8g2.drawStr(5, 55, "Send 'next'...");
  } else if (currentState == STATE_CALIBRATING_EXTREMES) {
    u8g2.drawStr(5, 20, "Rotate Stick to");
    u8g2.drawStr(5, 35, "ALL Edges (Min/Max)");
    u8g2.setCursor(5, 55);
    u8g2.print("X:");
    u8g2.print(analogRead(PIN_JOY_X));
    u8g2.print(" Y:");
    u8g2.print(analogRead(PIN_JOY_Y));
  }
}

// ==========================================
//               COMMAND INTERFACE
// ==========================================
void handleSerial() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "help") {
      Serial.println("\n--- HELP ---");
      Serial.println("cal           : Start Calibration Wizard");
      Serial.println("viz           : Visualize Deadzone on OLED");
      Serial.println("run           : Exit modes & run HID");
      Serial.println("debug         : Toggle Serial Output");
      Serial.println("next          : Advance Calibration Step");
      Serial.println("set_deadzone X: Set deadzone (e.g. 0.2 for 20%)");
    } else if (cmd == "cal") {
      Serial.println("Starting Calibration. Center stick and type 'next'");
      currentState = STATE_CALIBRATING_CENTER;
    } else if (cmd == "viz") {
      Serial.println("Visualizer Mode.");
      currentState = STATE_VISUALIZE;
    } else if (cmd == "run") {
      Serial.println("Running Mode.");
      currentState = STATE_RUNNING;
    } else if (cmd == "debug") {
      debugMode = !debugMode;
      Serial.print("Debug Mode: ");
      Serial.println(debugMode ? "ON" : "OFF");
    } else if (cmd.startsWith("set_deadzone ")) {
      float newDz = cmd.substring(13).toFloat();
      if (newDz >= 0 && newDz < 0.9) {
        joyConfig.deadzone = newDz;
        saveCalibration();
        Serial.print("Deadzone set to: ");
        Serial.println(newDz);
      }
    } else if (cmd == "next") {
      if (currentState == STATE_CALIBRATING_CENTER) {
        joyConfig.centerX = analogRead(PIN_JOY_X);
        joyConfig.centerY = analogRead(PIN_JOY_Y);
        // Reset min/max for next step capture
        joyConfig.minX = joyConfig.centerX;
        joyConfig.maxX = joyConfig.centerX;
        joyConfig.minY = joyConfig.centerY;
        joyConfig.maxY = joyConfig.centerY;
        Serial.println("Center Saved. Now rotate stick to limits and type 'next' to finish.");
        currentState = STATE_CALIBRATING_EXTREMES;
      } else if (currentState == STATE_CALIBRATING_EXTREMES) {
        saveCalibration();
        currentState = STATE_RUNNING;
        Serial.println("Calibration Complete.");
      } else if (cmd == "version") {
        Serial.print("FW_VERSION:");
        Serial.println(FW_VERSION);
      }
    }
  }
}

// ==========================================
//               MAIN LOOP
// ==========================================
void loop() {
  handleSerial();

  u8g2.clearBuffer();

  switch (currentState) {
    case STATE_RUNNING:
      readJoystick();
      handleWASD();
      drawRunning();

      if (debugMode) {
        Serial.printf("Raw: %d,%d | Norm: %.2f,%.2f | Dir: %s\n",
                      analogRead(PIN_JOY_X), analogRead(PIN_JOY_Y),
                      normX, normY, currentDirLabel.c_str());
      }
      break;

    case STATE_VISUALIZE:
      readJoystick();
      // No HID output in visualizer mode to prevent accidents
      drawVisualizer();
      break;

    case STATE_CALIBRATING_CENTER:
      drawCalibration();
      break;

    case STATE_CALIBRATING_EXTREMES:
      // Continually update min/max while user rotates
      int rx = analogRead(PIN_JOY_X);
      int ry = analogRead(PIN_JOY_Y);
      if (rx < joyConfig.minX) joyConfig.minX = rx;
      if (rx > joyConfig.maxX) joyConfig.maxX = rx;
      if (ry < joyConfig.minY) joyConfig.minY = ry;
      if (ry > joyConfig.maxY) joyConfig.maxY = ry;
      drawCalibration();
      break;
  }

  u8g2.sendBuffer();
  delay(20);  // ~50Hz refresh
}
