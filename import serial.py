import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import requests
import subprocess
import sys
import threading
import time
import os

# ================= CONFIG =================

BAUD = 115200
GITHUB_API = (
    "https://api.github.com/repos/"
    "Archer2121/ESP32-Joystick/contents/"
    "Joystick/build/Heltec-esp32.esp32.heltec_wifi_lora_32_V3"
)

# ================= SERIAL =================

def find_device():
    for p in serial.tools.list_ports.comports():
        if any(k in p.description for k in ("USB", "CP210", "CH340", "ESP32")):
            return p.device
    return None

class SerialDevice:
    def __init__(self):
        self.ser = None

    def connect(self):
        port = find_device()
        if not port:
            return False
        self.ser = serial.Serial(port, BAUD, timeout=1)
        time.sleep(1)
        return True

    def send(self, cmd):
        if not self.ser:
            return ""
        self.ser.write((cmd + "\n").encode())
        time.sleep(0.2)
        return self.ser.read_all().decode(errors="ignore")

    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

device = SerialDevice()

# ================= FIRMWARE =================

def download_firmware(progress_cb):
    resp = requests.get(GITHUB_API, timeout=10)
    resp.raise_for_status()

    files = resp.json()

    preferred = None
    fallback = None

    for f in files:
        name = f["name"].lower()

        if name.endswith(".merged.bin"):
            preferred = f
            break

        if (
            name.endswith(".bin")
            and "bootloader" not in name
            and "partition" not in name
        ):
            fallback = f

    target = preferred or fallback
    if not target:
        raise RuntimeError("No valid firmware binary found")

    url = target["download_url"]
    filename = target["name"]

    r = requests.get(url, stream=True)
    r.raise_for_status()

    total = int(r.headers.get("content-length", 0))
    downloaded = 0

    with open(filename, "wb") as fw:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                fw.write(chunk)
                downloaded += len(chunk)
                if total:
                    progress_cb((downloaded / total) * 50)

    return os.path.abspath(filename)

# ================= GUI =================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ESP32 Joystick Utility")
        self.geometry("480x460")
        self.resizable(False, False)

        self.status = tk.StringVar(value="Disconnected")
        self.version = tk.StringVar(value="—")

        self._build_ui()
        self.auto_connect()

    def _build_ui(self):
        ttk.Label(self, text="ESP32 HID Joystick", font=("Segoe UI", 16, "bold")).pack(pady=10)

        info = ttk.Frame(self)
        info.pack()

        ttk.Label(info, text="Status:").grid(row=0, column=0, sticky="e")
        ttk.Label(info, textvariable=self.status).grid(row=0, column=1, sticky="w")

        ttk.Label(info, text="Firmware:").grid(row=1, column=0, sticky="e")
        ttk.Label(info, textvariable=self.version).grid(row=1, column=1, sticky="w")

        ttk.Separator(self).pack(fill="x", pady=12)

        ttk.Button(self, text="Calibrate Joystick", command=self.calibrate).pack(fill="x", padx=80, pady=4)
        ttk.Button(self, text="Set Deadzone", command=self.set_deadzone).pack(fill="x", padx=80, pady=4)
        ttk.Button(self, text="Firmware Update", command=self.update_firmware).pack(fill="x", padx=80, pady=10)

        ttk.Separator(self).pack(fill="x", pady=10)

        self.progress = ttk.Progressbar(self, length=400, mode="determinate")
        self.progress.pack(pady=8)

        ttk.Button(self, text="Reconnect", command=self.auto_connect).pack(pady=6)

    # ================= DEVICE =================

    def auto_connect(self):
        device.close()
        if device.connect():
            self.status.set("Connected")
            self.get_version()
        else:
            self.status.set("Device not found")
            self.version.set("—")

    def get_version(self):
        resp = device.send("version")
        for line in resp.splitlines():
            if line.startswith("FW_VERSION:"):
                self.version.set(line.split(":")[1])

    # ================= FEATURES =================

    def calibrate(self):
        messagebox.showinfo("Calibration", "Center joystick and press OK")
        device.send("cal")
        device.send("next")

        messagebox.showinfo("Calibration", "Move joystick to all extremes, then press OK")
        device.send("next")

        messagebox.showinfo("Calibration", "Calibration complete")

    def set_deadzone(self):
        dz = simpledialog.askfloat("Deadzone", "Enter deadzone (0.05 – 0.5):")
        if dz is not None:
            device.send(f"set_deadzone {dz}")

    # ================= UPDATE =================

    def update_firmware(self):
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            self.progress["value"] = 0
            self.status.set("Downloading firmware...")
            self.update_idletasks()

            fw = download_firmware(self._progress)

            device.close()
            port = find_device()
            if not port:
                raise RuntimeError("ESP32 not found")

            self.status.set("Flashing firmware...")
            self.update_idletasks()

            cmd = [
                sys.executable, "-m", "esptool",
                "--chip", "esp32s3",
                "--port", port,
                "--baud", "460800",
                "write_flash",
                "-z",
                "0x0",
                fw
            ]

            subprocess.run(cmd, check=True)

            self.progress["value"] = 100
            self.status.set("Update complete")

            messagebox.showinfo("Firmware", "Firmware updated successfully")
            self.auto_connect()

        except Exception as e:
            messagebox.showerror("Update failed", str(e))
            self.status.set("Update failed")

    def _progress(self, value):
        self.progress["value"] = value
        self.update_idletasks()

# ================= RUN =================

if __name__ == "__main__":
    App().mainloop()
