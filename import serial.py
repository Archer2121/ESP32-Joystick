import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys
import time

BAUD = 115200

# ================= SERIAL UTILS =================

def find_device():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if "USB" in p.description or "CP210" in p.description or "CH340" in p.description:
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
        time.sleep(0.8)
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

# ================= GUI =================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ESP32 Joystick Utility")
        self.geometry("420x360")
        self.resizable(False, False)

        self.status = tk.StringVar(value="Disconnected")
        self.version = tk.StringVar(value="Unknown")

        self.create_widgets()
        self.auto_connect()

    def create_widgets(self):
        ttk.Label(self, text="ESP32 HID Joystick", font=("Segoe UI", 14, "bold")).pack(pady=10)

        info = ttk.Frame(self)
        info.pack(pady=5)

        ttk.Label(info, text="Status:").grid(row=0, column=0, sticky="e")
        ttk.Label(info, textvariable=self.status).grid(row=0, column=1, sticky="w")

        ttk.Label(info, text="Firmware:").grid(row=1, column=0, sticky="e")
        ttk.Label(info, textvariable=self.version).grid(row=1, column=1, sticky="w")

        ttk.Separator(self).pack(fill="x", pady=10)

        ttk.Button(self, text="Calibrate Joystick", command=self.calibrate).pack(fill="x", padx=40, pady=4)
        ttk.Button(self, text="Deadzone Visualizer", command=self.visualize).pack(fill="x", padx=40, pady=4)
        ttk.Button(self, text="Set Deadzone", command=self.set_deadzone).pack(fill="x", padx=40, pady=4)
        ttk.Button(self, text="Flash Firmware", command=self.flash_firmware).pack(fill="x", padx=40, pady=4)

        ttk.Separator(self).pack(fill="x", pady=10)

        ttk.Button(self, text="Reconnect", command=self.auto_connect).pack(pady=5)

    # ================= ACTIONS =================

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

    def calibrate(self):
        messagebox.showinfo("Calibration", "Center the stick, then press OK")
        device.send("cal")
        device.send("next")

        messagebox.showinfo("Calibration", "Rotate stick to ALL edges, then press OK")
        device.send("next")

        messagebox.showinfo("Calibration", "Calibration complete!")

    def visualize(self):
        device.send("viz")
        messagebox.showinfo("Visualizer", "OLED visualizer enabled.\nPress OK to exit.")
        device.send("run")

    def set_deadzone(self):
        dz = tk.simpledialog.askfloat("Deadzone", "Enter deadzone (0.05–0.5):")
        if dz is not None:
            device.send(f"set_deadzone {dz}")

    def flash_firmware(self):
        path = filedialog.askopenfilename(
            filetypes=[("ESP32 Firmware", "*.bin")]
        )
        if not path:
            return

        device.close()

        cmd = [
            sys.executable, "-m", "esptool",
            "--chip", "esp32s3",
            "--port", find_device(),
            "--baud", "460800",
            "write_flash",
            "-z",
            "0x0",
            path
        ]

        try:
            subprocess.run(cmd, check=True)
            messagebox.showinfo("Firmware", "Firmware updated successfully!")
            self.auto_connect()
        except subprocess.CalledProcessError:
            messagebox.showerror("Firmware", "Flashing failed")

# ================= RUN =================

if __name__ == "__main__":
    App().mainloop()
