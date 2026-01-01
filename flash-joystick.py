import os, threading, subprocess, requests, serial, time
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

CHIP = "esp32s3"
BAUD_FLASH = "460800"
BAUD_SERIAL = 115200

VERSION_URL = "https://raw.githubusercontent.com/Archer2121/Macropad/main/version.txt"
FW_BASE = "https://raw.githubusercontent.com/Archer2121/Macropad/main/main/build/esp32.esp32.lolin_s3"

FILES = {
    "bootloader": ("main.ino.bootloader.bin", "0x0000"),
    "partitions": ("main.ino.partitions.bin", "0x8000"),
    "boot_app0": ("boot_app0.bin", "0xE000"),
    "app": ("main.ino.bin", "0x10000"),
}

BASE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(BASE, "firmware")
os.makedirs(FW_DIR, exist_ok=True)

class FirmwareUpdater(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Macropad Firmware Updater")
        self.geometry("720x460")

        self.port = tk.StringVar()
        self.progress = tk.IntVar()
        self.status = tk.StringVar(value="Idle")

        ttk.Label(self, text="COM Port").pack()
        self.ports = ttk.Combobox(self, textvariable=self.port, width=25)
        self.ports.pack()

        ttk.Button(self, text="Refresh Ports", command=self.refresh_ports).pack(pady=3)
        ttk.Button(self, text="Update Firmware (GitHub)", command=self.start_update).pack(pady=5)

        ttk.Progressbar(self, maximum=100, variable=self.progress).pack(fill="x", padx=10)
        ttk.Label(self, textvariable=self.status).pack(pady=4)

        ttk.Label(self, text="Serial Monitor").pack()
        self.serial_box = scrolledtext.ScrolledText(self, height=14)
        self.serial_box.pack(fill="both", expand=True, padx=10)

        self.ser = None
        self.refresh_ports()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.ports["values"] = ports
        if ports:
            self.port.set(ports[0])

    def log(self, msg):
        self.serial_box.insert(tk.END, msg)
        self.serial_box.see(tk.END)

    def start_serial(self):
        if self.ser:
            return
        try:
            self.ser = serial.Serial(self.port.get(), BAUD_SERIAL, timeout=0.1)
            threading.Thread(target=self.read_serial, daemon=True).start()
        except Exception as e:
            self.log(f"[SERIAL ERROR] {e}\n")

    def read_serial(self):
        while self.ser:
            try:
                line = self.ser.readline().decode(errors="ignore")
                if line:
                    self.log(line)
            except:
                break

    def start_update(self):
        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        try:
            self.progress.set(0)
            self.status.set("Downloading firmware...")

            for i, (_, (f, _)) in enumerate(FILES.items()):
                r = requests.get(f"{FW_BASE}/{f}", timeout=20)
                if r.status_code != 200:
                    raise RuntimeError(f"Failed to download {f}")
                with open(os.path.join(FW_DIR, f), "wb") as w:
                    w.write(r.content)
                self.progress.set(10 + i * 8)

            self.status.set("Erasing flash...")
            subprocess.run(
                ["esptool", "--chip", CHIP, "--port", self.port.get(), "erase-flash"],
                check=True
            )

            self.status.set("Flashing firmware...")
            cmd = ["esptool", "--chip", CHIP, "--port", self.port.get(),
                   "--baud", BAUD_FLASH, "write_flash"]
            for _, (f, addr) in FILES.items():
                cmd += [addr, os.path.join(FW_DIR, f)]
            subprocess.run(cmd, check=True)

            self.progress.set(100)
            self.status.set("Update complete ✔")

            time.sleep(2)
            self.start_serial()

        except Exception as e:
            self.progress.set(0)
            self.status.set("Error")
            messagebox.showerror("Error", str(e))

FirmwareUpdater().mainloop()
