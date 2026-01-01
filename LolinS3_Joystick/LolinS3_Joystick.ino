#include <Arduino.h>
#include <Preferences.h>
#include "USB.h"
#include "USBHIDKeyboard.h"
#define FW_VERSION "1.0.0-s3"

// ==========================================
//               CONFIGURATION
// ==========================================
// Change these to the ADC-capable pins on your Lolin S3 if needed
// Using pins 5 and 6 as requested
#define PIN_JOY_X 5
#define PIN_JOY_Y 6

// Default Values
#define DEFAULT_DEADZONE 0.15f  // 15% Radial Deadzone

// ==========================================
//               OBJECTS & GLOBALS
// ==========================================
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
  int rotation = 0; // degrees clockwise: 0,90,180,270
  int flipX = 0; // 0 = no flip, 1 = mirror left-right
} joyConfig;

// Runtime Variables
float normX = 0.0f;
float normY = 0.0f;
float magnitude = 0.0f;
float angle = 0.0f;
String currentDirLabel = "NEUTRAL";

// ==========================================
//               SETUP
// ==========================================
void loadCalibration() {
  prefs.begin("joystick", true);
  joyConfig.minX = prefs.getInt("minX", 0);
  joyConfig.maxX = prefs.getInt("maxX", 4095);
  joyConfig.centerX = prefs.getInt("centerX", 2048);
  joyConfig.minY = prefs.getInt("minY", 0);
  joyConfig.maxY = prefs.getInt("maxY", 4095);
  joyConfig.centerY = prefs.getInt("centerY", 2048);
  joyConfig.deadzone = prefs.getFloat("deadzone", DEFAULT_DEADZONE);
  joyConfig.rotation = prefs.getInt("rotation", 0);
  joyConfig.flipX = prefs.getInt("flipX", 0);
  prefs.end();
}

void saveCalibration() {
  prefs.begin("joystick", false);
  prefs.putInt("minX", joyConfig.minX);
  prefs.putInt("maxX", joyConfig.maxX);
  prefs.putInt("centerX", joyConfig.centerX);
  prefs.putInt("minY", joyConfig.minY);
  prefs.putInt("maxY", joyConfig.maxY);
  prefs.putInt("centerY", joyConfig.centerY);
  prefs.putFloat("deadzone", joyConfig.deadzone);
  prefs.putInt("rotation", joyConfig.rotation);
  prefs.putInt("flipX", joyConfig.flipX);
  prefs.end();
  Serial.println("Calibration Saved to Flash!");
}

void setup() {
  Serial.begin(115200);

  // Initialize HID
  Keyboard.begin();
  USB.begin();

  // Pin Setup
  pinMode(PIN_JOY_X, INPUT);
  pinMode(PIN_JOY_Y, INPUT);
  analogReadResolution(12);  // 0-4095

  loadCalibration();
  delay(200);

  Serial.println("Lolin S3 Joystick (no OLED) started");
  Serial.print("FW: "); Serial.println(FW_VERSION);
}

// ==========================================
//               LOGIC HANDLERS
// ==========================================
void readJoystick() {
  int rawX = analogRead(PIN_JOY_X);
  int rawY = analogRead(PIN_JOY_Y);

  float nX, nY;

  if (rawX >= joyConfig.centerX)
    nX = (float)(rawX - joyConfig.centerX) / (joyConfig.maxX - joyConfig.centerX);
  else
    nX = -(float)(joyConfig.centerX - rawX) / (joyConfig.centerX - joyConfig.minX);

  if (rawY >= joyConfig.centerY)
    nY = (float)(rawY - joyConfig.centerY) / (joyConfig.maxY - joyConfig.centerY);
  else
    nY = -(float)(joyConfig.centerY - rawY) / (joyConfig.centerY - joyConfig.minY);

  nX = constrain(nX, -1.0f, 1.0f);
  nY = constrain(nY, -1.0f, 1.0f);

  float rad = sqrt(nX * nX + nY * nY);

  if (rad < joyConfig.deadzone) {
    normX = 0.0f;
    normY = 0.0f;
    magnitude = 0.0f;
  } else {
    float scaledRad = (rad - joyConfig.deadzone) / (1.0f - joyConfig.deadzone);
    scaledRad = constrain(scaledRad, 0.0f, 1.0f);
    normX = (nX / rad) * scaledRad;
    normY = (nY / rad) * scaledRad;
    magnitude = scaledRad;
  }

  // Apply horizontal flip if configured (mirror X)
  if (joyConfig.flipX) {
    normX = -normX;
  }

  // Apply saved rotation before computing angle / direction
  float rx = normX;
  float ry = normY;
  switch (joyConfig.rotation) {
    case 0:
      rx = normX; ry = normY; break;
    case 90:
      // rotate clockwise 90 -> rx = normY, ry = -normX
      rx = normY; ry = -normX; break;
    case 180:
      rx = -normX; ry = -normY; break;
    case 270:
      // rotate clockwise 270 == counter-clockwise 90
      rx = -normY; ry = normX; break;
    default:
      rx = normX; ry = normY; break;
  }

  angle = atan2(ry, rx) * 180.0 / PI;
  if (angle < 0) angle += 360;
}

void handleWASD() {
  bool w = false, a = false, s = false, d = false;
  currentDirLabel = "NEUTRAL";

  if (magnitude > 0.1) {
    if (angle >= 337.5 || angle < 22.5) { d = true; currentDirLabel = "RIGHT"; }
    else if (angle >= 22.5 && angle < 67.5) { d = true; s = true; currentDirLabel = "DOWN-RIGHT"; }
    else if (angle >= 67.5 && angle < 112.5) { s = true; currentDirLabel = "DOWN"; }
    else if (angle >= 112.5 && angle < 157.5) { s = true; a = true; currentDirLabel = "DOWN-LEFT"; }
    else if (angle >= 157.5 && angle < 202.5) { a = true; currentDirLabel = "LEFT"; }
    else if (angle >= 202.5 && angle < 247.5) { a = true; w = true; currentDirLabel = "UP-LEFT"; }
    else if (angle >= 247.5 && angle < 292.5) { w = true; currentDirLabel = "UP"; }
    else if (angle >= 292.5 && angle < 337.5) { w = true; d = true; currentDirLabel = "UP-RIGHT"; }
  }

  if (w) Keyboard.press('w'); else Keyboard.release('w');
  if (a) Keyboard.press('a'); else Keyboard.release('a');
  if (s) Keyboard.press('s'); else Keyboard.release('s');
  if (d) Keyboard.press('d'); else Keyboard.release('d');
}

// ==========================================
//               COMMAND INTERFACE
// ==========================================
void handleSerial() {
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;
    Serial.print("Received cmd: ");
    Serial.println(line);

    String lc = line;
    lc.toLowerCase();
    int sp = lc.indexOf(' ');
    String verb = (sp == -1) ? lc : lc.substring(0, sp);
    String arg = "";
    if (sp != -1) {
      arg = line.substring(sp + 1);
      arg.trim();
    }

    if (verb == "help") {
      Serial.println("Available commands:");
      Serial.println("  help                      : Show this help menu");
      Serial.println("  cal                       : Start calibration wizard (center, then rotate stick to edges)");
      Serial.println("  next                      : Advance calibration step / finish calibration");
      Serial.println("  viz                       : Visualize readings over serial (disables HID output)");
      Serial.println("  run                       : Resume HID output after viz/calibration");
      Serial.println("  rotate [0|90|180|270]     : Show or set board rotation (persists to flash)");
      Serial.println("  flip [toggle|h|none]      : Show/set horizontal flip (mirror left/right)");
      Serial.println("  set_deadzone <value>      : Set radial deadzone (e.g. set_deadzone 0.2)");
      Serial.println("  debug                     : Toggle verbose debug serial messages");
      Serial.println("  version                   : Print firmware version");
      Serial.println("");
      Serial.println("Examples:");
      Serial.println("  rotate 90                 -> rotate readings 90 degrees clockwise and save");
      Serial.println("  set_deadzone 0.15         -> set deadzone to 15% and save");
    } else if (verb == "rotate") {
      // Usage: rotate [0|90|180|270]
      if (arg.length() == 0) {
        Serial.print("Rotation: "); Serial.println(joyConfig.rotation);
      } else {
        int val = arg.toInt();
        if (val == 0 || val == 90 || val == 180 || val == 270) {
          joyConfig.rotation = val;
          saveCalibration();
          Serial.print("Rotation set to: "); Serial.println(val);
        } else {
          Serial.println("Invalid rotation. Use 0,90,180 or 270");
        }
      }
    } else if (verb == "flip") {
      // Usage: flip [toggle|h|none]
      if (arg.length() == 0) {
        Serial.print("Flip horizontal: "); Serial.println(joyConfig.flipX ? "ON" : "OFF");
      } else {
        String a = arg;
        a.toLowerCase();
        if (a == "toggle") {
          joyConfig.flipX = joyConfig.flipX ? 0 : 1;
          saveCalibration();
          Serial.print("Flip horizontal: "); Serial.println(joyConfig.flipX ? "ON" : "OFF");
        } else if (a == "h" || a == "horizontal" || a == "on") {
          joyConfig.flipX = 1;
          saveCalibration();
          Serial.println("Flip horizontal: ON");
        } else if (a == "none" || a == "off") {
          joyConfig.flipX = 0;
          saveCalibration();
          Serial.println("Flip horizontal: OFF");
        } else {
          Serial.println("Invalid flip arg. Use 'flip', 'flip toggle', 'flip h', or 'flip none'");
        }
      }
    } else if (verb == "cal") {
      Serial.println("Starting Calibration. Center stick and type 'next'");
      currentState = STATE_CALIBRATING_CENTER;
    } else if (verb == "viz") {
      Serial.println("Visualizer Mode (no OLED) - outputs serial data");
      currentState = STATE_VISUALIZE;
    } else if (verb == "run") {
      Serial.println("Running Mode.");
      currentState = STATE_RUNNING;
    } else if (verb == "debug") {
      debugMode = !debugMode;
      Serial.print("Debug Mode: "); Serial.println(debugMode ? "ON" : "OFF");
    } else if (verb == "set_deadzone") {
      if (arg.length() == 0) Serial.println("Usage: set_deadzone <value>");
      else {
        float newDz = arg.toFloat();
        if (newDz >= 0 && newDz < 0.9) {
          joyConfig.deadzone = newDz;
          saveCalibration();
          Serial.print("Deadzone set to: "); Serial.println(newDz);
        } else Serial.println("Invalid deadzone. Use >=0 and <0.9");
      }
    } else if (verb == "next") {
      if (currentState == STATE_CALIBRATING_CENTER) {
        joyConfig.centerX = analogRead(PIN_JOY_X);
        joyConfig.centerY = analogRead(PIN_JOY_Y);
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
      } else Serial.println("'next' ignored in current state.");
    } else if (verb == "version") {
      Serial.print("FW_VERSION:"); Serial.println(FW_VERSION);
    } else {
      Serial.print("Unknown command: "); Serial.println(line);
    }
  }
}

// ==========================================
//               MAIN LOOP
// ==========================================
void loop() {
  handleSerial();

  switch (currentState) {
    case STATE_RUNNING:
      readJoystick();
      handleWASD();
      if (debugMode) {
        Serial.printf("Raw: %d,%d | Norm: %.2f,%.2f | Dir: %s\n",
                      analogRead(PIN_JOY_X), analogRead(PIN_JOY_Y),
                      normX, normY, currentDirLabel.c_str());
      }
      break;

    case STATE_VISUALIZE:
      readJoystick();
      Serial.printf("Viz: X=%f Y=%f Mag=%.2f Ang=%.1f Dir=%s\n",
                    normX, normY, magnitude, angle, currentDirLabel.c_str());
      delay(100);
      break;

    case STATE_CALIBRATING_CENTER:
      // waiting for 'next' command
      break;

    case STATE_CALIBRATING_EXTREMES:
      int rx = analogRead(PIN_JOY_X);
      int ry = analogRead(PIN_JOY_Y);
      if (rx < joyConfig.minX) joyConfig.minX = rx;
      if (rx > joyConfig.maxX) joyConfig.maxX = rx;
      if (ry < joyConfig.minY) joyConfig.minY = ry;
      if (ry > joyConfig.maxY) joyConfig.maxY = ry;
      if (debugMode) {
        Serial.printf("Calib min/max X:%d-%d Y:%d-%d\n", joyConfig.minX, joyConfig.maxX, joyConfig.minY, joyConfig.maxY);
      }
      break;
  }

  delay(20);
}
