# ...existing code...
import os, threading, subprocess, requests, serial, time
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

CHIP = "auto"
BAUD_FLASH = "921600"
BAUD_SERIAL = 115200

# Use the merged Arduino output (single app binary)
MERGED_FILENAME = "Joystick.ino.merged.bin"
APP_ADDR = "0x10000"
FW_MERGED_URL = f"https://github.com/Archer2121/ESP32-Joystick/raw/597c542eba42b7a166a790ff989ffe8bf63c3959/Joystick/build/Heltec-esp32.esp32.heltec_wifi_lora_32_V3/Joystick.ino.merged.bin"

# adjust if your module has different flash size
FLASH_SIZE_BYTES = 8 * 1024 * 1024

BASE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(BASE, "firmware")
os.makedirs(FW_DIR, exist_ok=True)

class FirmwareUpdater(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Joystick Firmware Updater (merged)")
        self.geometry("720x460")

        self.port = tk.StringVar()
        self.progress = tk.IntVar()
        self.status = tk.StringVar(value="Idle")

        ttk.Label(self, text="COM Port").pack()
        self.ports = ttk.Combobox(self, textvariable=self.port, width=25)
        self.ports.pack()

        ttk.Button(self, text="Refresh Ports", command=self.refresh_ports).pack(pady=3)
        ttk.Button(self, text="Update Firmware (merged)", command=self.start_update).pack(pady=5)

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
        resp = messagebox.askquestion("Update Source", "Update from a local merged .bin file?\nYes = local file, No = GitHub merged binary")
        if resp == "yes":
            path = filedialog.askopenfilename(title="Select merged .bin file", filetypes=[("Binary files","*.bin"),("All files","*.*")])
            if not path:
                return
            threading.Thread(target=self.update, args=(path,), daemon=True).start()
        else:
            threading.Thread(target=self.update, daemon=True).start()

    def enter_flash_mode(self):
        try:
            if self.ser:
                try:
                    self.ser.close()
                except:
                    pass
                self.ser = None

            s = serial.Serial(self.port.get(), BAUD_SERIAL, timeout=0.1)
            # Toggle DTR/RTS sequence to try to force ESP32 into bootloader
            s.setDTR(False)
            s.setRTS(True)
            time.sleep(0.05)
            s.setDTR(True)
            s.setRTS(False)
            time.sleep(0.05)
            s.close()
            self.log("[INFO] Flash-mode sequence toggled.\n")
        except Exception as e:
            self.log(f"[BOOT MODE ERROR] {e}\n")

    def update(self, local_bin=None):
        try:
            self.progress.set(0)
            if local_bin:
                self.status.set("Preparing local merged update...")
            else:
                self.status.set("Downloading merged binary...")

            merged_path = None
            if not local_bin:
                r = requests.get(FW_MERGED_URL, timeout=30)
                if r.status_code != 200:
                    raise RuntimeError(f"Failed to download {MERGED_FILENAME}")
                merged_path = os.path.join(FW_DIR, MERGED_FILENAME)
                with open(merged_path, "wb") as w:
                    w.write(r.content)
                self.progress.set(50)
            else:
                merged_path = local_bin
                self.progress.set(50)

            file_size = os.path.getsize(merged_path)
            default_offset = int(APP_ADDR, 16)
            if file_size > FLASH_SIZE_BYTES - default_offset:
                flash_addr = "0x0"
            else:
                flash_addr = APP_ADDR

            self.status.set("Entering flash mode...")
            self.enter_flash_mode()

            self.status.set("Erasing flash...")
            subprocess.run(
                ["esptool", "--chip", CHIP, "--port", self.port.get(), "erase-flash"],
                check=True
            )

            self.status.set(f"Flashing merged binary at {flash_addr}...")
            cmd = ["esptool", "--chip", CHIP, "--port", self.port.get(),
                   "--baud", BAUD_FLASH, "write-flash", flash_addr, merged_path]
            subprocess.run(cmd, check=True)

            self.progress.set(100)
            self.status.set("Update complete ✔")
            time.sleep(2)
            self.start_serial()

        except Exception as e:
            self.progress.set(0)
            self.status.set("Error")
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    FirmwareUpdater().mainloop()
# ...existing code...