"""
Combined Joystick Tool
- Tabs: Firmware Updater and Calibrator
- Reuses logic from flash-joystick.py and calibrator_gui.py

Run: python joystick_tool.py
Requires: pyserial, requests
"""

import os
import threading
import subprocess
import requests
import serial
import serial.tools.list_ports
import time
import queue
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, scrolledtext, filedialog

# Firmware constants (from flash-joystick.py)
CHIP = "auto"
BAUD_FLASH = "921600"
BAUD_SERIAL = 115200
MERGED_FILENAME = "Joystick.ino.merged.bin"
APP_ADDR = "0x10000"
FW_MERGED_URL = "https://github.com/Archer2121/ESP32-Joystick/raw/597c542eba42b7a166a790ff989ffe8bf63c3959/Joystick/build/Heltec-esp32.esp32.heltec_wifi_lora_32_V3/Joystick.ino.merged.bin"
FLASH_SIZE_BYTES = 8 * 1024 * 1024
BASE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(BASE, "firmware")
os.makedirs(FW_DIR, exist_ok=True)

READ_TIMEOUT = 0.1

class UpdaterTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.port = tk.StringVar()
        self.progress = tk.IntVar()
        self.status = tk.StringVar(value="Idle")
        self.ser = None
        self._build()
        self.refresh_ports()

    def _build(self):
        ttk.Label(self, text="COM Port").grid(row=0, column=0, sticky='w')
        self.ports = ttk.Combobox(self, textvariable=self.port, width=25)
        self.ports.grid(row=0, column=1, sticky='w')
        ttk.Button(self, text="Refresh Ports", command=self.refresh_ports).grid(row=0, column=2, padx=6)
        ttk.Button(self, text="Update Firmware (merged)", command=self.start_update).grid(row=1, column=0, columnspan=3, pady=6)

        self.pbar = ttk.Progressbar(self, maximum=100, variable=self.progress)
        self.pbar.grid(row=2, column=0, columnspan=3, sticky='we', padx=6)
        ttk.Label(self, textvariable=self.status).grid(row=3, column=0, columnspan=3, sticky='w', pady=4)

        ttk.Label(self, text="Serial Monitor").grid(row=4, column=0, sticky='w')
        self.serial_box = scrolledtext.ScrolledText(self, height=12)
        self.serial_box.grid(row=5, column=0, columnspan=3, sticky='nsew', padx=6, pady=6)
        self.grid_rowconfigure(5, weight=1)

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.ports['values'] = ports
        if ports:
            self.port.set(ports[0])

    def log(self, msg):
        try:
            self.serial_box.insert(tk.END, msg)
            self.serial_box.see(tk.END)
        except Exception:
            pass

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
                line = self.ser.readline().decode(errors='ignore')
                if line:
                    self.log(line)
            except Exception:
                break

    def start_update(self):
        resp = messagebox.askquestion("Update Source", "Update from a local merged .bin file?\nYes = local file, No = GitHub merged binary")
        if resp == 'yes':
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
                except Exception:
                    pass
                self.ser = None

            s = serial.Serial(self.port.get(), BAUD_SERIAL, timeout=0.1)
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
                with open(merged_path, 'wb') as w:
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
            subprocess.run(["esptool", "--chip", CHIP, "--port", self.port.get(), "erase-flash"], check=True)

            self.status.set(f"Flashing merged binary at {flash_addr}...")
            cmd = ["esptool", "--chip", CHIP, "--port", self.port.get(), "--baud", BAUD_FLASH, "write-flash", flash_addr, merged_path]
            subprocess.run(cmd, check=True)

            self.progress.set(100)
            self.status.set("Update complete ✔")
            time.sleep(2)
            self.start_serial()

        except Exception as e:
            self.progress.set(0)
            self.status.set("Error")
            messagebox.showerror("Error", str(e))


class CalibratorTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.serial = None
        self.read_thread = None
        self.alive = threading.Event()
        self.q = queue.Queue()
        self.latest_version = self._load_latest_version()
        self.device_version = None
        self.awaiting_version = False
        self._build()
        self._poll_serial_queue()
        self.after(200, self._auto_connect)

    def _load_latest_version(self):
        try:
            with open(os.path.join(BASE, 'version.txt'), 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            return None

    def _build(self):
        heading_font = tkfont.Font(size=11, weight='bold')
        mono_font = tkfont.Font(family='Courier', size=10)

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky='we')
        ttk.Label(top, text='Port:').grid(row=0, column=0)
        self.port_cb = ttk.Combobox(top, width=20, state='readonly')
        self.port_cb.grid(row=0, column=1, padx=6)
        ttk.Button(top, text='Refresh', command=self.refresh_ports).grid(row=0, column=2)
        self.connect_btn = ttk.Button(top, text='Connect', command=self.toggle_connect)
        self.connect_btn.grid(row=0, column=3, padx=6)

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky='we', pady=(8,0))
        ttk.Button(controls, text='Calibrate', command=self.open_calibration_dialog, width=12).grid(row=0, column=0, padx=4, pady=2)
        ttk.Button(controls, text='Next', command=lambda: self.send_cmd('next'), width=12).grid(row=0, column=1, padx=4, pady=2)
        ttk.Button(controls, text='Viz', command=lambda: self.send_cmd('viz'), width=12).grid(row=0, column=2, padx=4, pady=2)
        ttk.Button(controls, text='Run', command=lambda: self.send_cmd('run'), width=12).grid(row=0, column=3, padx=4, pady=2)
        ttk.Button(controls, text='Version', command=lambda: self.send_cmd('version'), width=12).grid(row=0, column=4, padx=4, pady=2)

        settings = ttk.Frame(self)
        settings.grid(row=2, column=0, sticky='we', pady=(8,0))
        ttk.Label(settings, text='Deadzone:').grid(row=0, column=0)
        self.dz_var = tk.StringVar(value='0.15')
        ttk.Entry(settings, width=8, textvariable=self.dz_var).grid(row=0, column=1)
        ttk.Button(settings, text='Set', command=self.set_deadzone).grid(row=0, column=2, padx=6)
        self.show_output = tk.BooleanVar(value=True)
        ttk.Checkbutton(settings, text='Show Serial Output', variable=self.show_output, command=self._update_output_visibility).grid(row=1, column=0, columnspan=3, pady=(6,0))

        self.status_var = tk.StringVar(value='Disconnected')
        ttk.Label(self, textvariable=self.status_var).grid(row=3, column=0, sticky='w', pady=(6,0))

        self.log = scrolledtext.ScrolledText(self, height=12)
        self.log.grid(row=4, column=0, sticky='nsew', pady=(8,0))
        self.grid_rowconfigure(4, weight=1)

        # version display
        self.ver_var = tk.StringVar(value='')
        self.ver_label = ttk.Label(self, textvariable=self.ver_var)
        self.ver_label.grid(row=5, column=0, sticky='w', pady=(6,0))

        self.refresh_ports()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_cb['values'] = ports
        if ports:
            try:
                self.port_cb.current(0)
            except Exception:
                pass

    def _auto_connect(self):
        vals = self.port_cb['values']
        if vals and len(vals) > 0:
            try:
                if not self.port_cb.get():
                    self.port_cb.current(0)
            except Exception:
                pass
            self.connect()

    def toggle_connect(self):
        if self.serial and self.serial.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_cb.get()
        if not port:
            messagebox.showwarning('No Port', 'Please select a COM port first.')
            return
        try:
            self.serial = serial.Serial(port, BAUD_SERIAL, timeout=READ_TIMEOUT)
        except Exception as e:
            messagebox.showerror('Connection Failed', str(e))
            return
        self.alive.set()
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        self.status_var.set(f'Connected: {port} @ {BAUD_SERIAL}')
        try:
            self.connect_btn.config(text='Disconnect')
        except Exception:
            pass
        self.query_device_version()

    def disconnect(self):
        self.alive.clear()
        if self.read_thread:
            self.read_thread.join(timeout=0.5)
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
        except Exception:
            pass
        self.serial = None
        self.status_var.set('Disconnected')
        try:
            self.connect_btn.config(text='Connect')
        except Exception:
            pass

    def _read_loop(self):
        while self.alive.is_set() and self.serial and self.serial.is_open:
            try:
                line = self.serial.readline().decode(errors='replace')
                if line:
                    self.q.put(line)
                else:
                    time.sleep(0.01)
            except Exception as e:
                self.q.put(f"<ERROR reading serial: {e}>\n")
                break

    def _poll_serial_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if self.awaiting_version:
                    m = re.search(r'FW_VERSION\s*[:=]?\s*([0-9]+\.[0-9]+\.[0-9]+)', msg)
                    if m:
                        self.device_version = m.group(1)
                        self.awaiting_version = False
                        self._update_version_label()
                if self.show_output.get():
                    self.log.insert('end', msg)
                    self.log.see('end')
        except queue.Empty:
            pass
        self.after(100, self._poll_serial_queue)

    def send_cmd(self, cmd):
        if not (self.serial and self.serial.is_open):
            messagebox.showwarning('Not Connected', 'Open a serial connection first.')
            return
        try:
            self.serial.write((cmd + '\n').encode())
            if self.show_output.get():
                self.log.insert('end', f"> {cmd}\n")
                self.log.see('end')
        except Exception as e:
            messagebox.showerror('Send Failed', str(e))

    def query_device_version(self):
        if not (self.serial and self.serial.is_open):
            return
        self.awaiting_version = True
        try:
            self.send_cmd('version')
        except Exception:
            pass
        self.after(2000, self._version_timeout)

    def _version_timeout(self):
        if self.awaiting_version:
            self.awaiting_version = False
            self.device_version = None
            self._update_version_label()

    def _update_version_label(self):
        text = f"Device: {self.device_version or 'unknown'}"
        if self.latest_version:
            text += f"   Latest: {self.latest_version}"
        self.ver_var.set(text)
        try:
            if self.device_version and self.latest_version and self.device_version != self.latest_version:
                self.ver_label.config(foreground='red')
            else:
                self.ver_label.config(foreground='green')
        except Exception:
            pass

    def open_calibration_dialog(self):
        if not (self.serial and self.serial.is_open):
            messagebox.showwarning('Not Connected', 'Open a serial connection first.')
            return
        try:
            self.send_cmd('cal')
        except Exception:
            pass
        dlg = tk.Toplevel(self)
        dlg.title('Calibration Wizard')
        dlg.transient(self)
        dlg.grab_set()
        instr_var = tk.StringVar()
        steps = [
            'Step 1: Center the stick and press Next to save center.',
            'Step 2: Rotate the stick to all edges (min/max). Press Next to finish.',
            'Calibration complete. Close this dialog.'
        ]
        instr_var.set(steps[0])
        lbl = ttk.Label(dlg, textvariable=instr_var, wraplength=420, justify='left', padding=(12,12))
        lbl.grid(row=0, column=0, columnspan=2, padx=12, pady=(12,6))
        step_state = {'index':0}
        def on_next():
            self.send_cmd('next')
            step_state['index'] += 1
            if step_state['index'] < len(steps):
                instr_var.set(steps[step_state['index']])
            if step_state['index'] >= len(steps) - 1:
                next_btn.config(text='Close', command=dlg.destroy)
        def on_cancel():
            dlg.destroy()
        next_btn = ttk.Button(dlg, text='Next', command=on_next)
        next_btn.grid(row=1, column=0, padx=12, pady=(0,12), sticky='e')
        ttk.Button(dlg, text='Cancel', command=on_cancel).grid(row=1, column=1, padx=12, pady=(0,12), sticky='w')
        dlg.columnconfigure(0, weight=1)
        dlg.columnconfigure(1, weight=1)
        self.wait_window(dlg)

    def _update_output_visibility(self):
        if self.show_output.get():
            try:
                self.log.grid()
            except Exception:
                pass
        else:
            try:
                self.log.grid_remove()
            except Exception:
                pass

    def set_deadzone(self):
        val = self.dz_var.get().strip()
        try:
            f = float(val)
        except ValueError:
            messagebox.showwarning('Invalid Value', 'Deadzone must be a number (e.g. 0.2)')
            return
        if f < 0 or f >= 0.9:
            messagebox.showwarning('Out Of Range', 'Deadzone must be >=0 and <0.9')
            return
        self.send_cmd(f"set_deadzone {f}")


class JoystickToolApp(ttk.Frame):
    def __init__(self, root):
        super().__init__(root)
        root.title('Joystick Tool')
        root.geometry('900x640')
        self.pack(fill='both', expand=True)

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True)

        self.updater = UpdaterTab(nb)
        nb.add(self.updater, text='Updater')

        self.calibrator = CalibratorTab(nb)
        nb.add(self.calibrator, text='Calibrator')
        # Show calibrator tab first
        try:
            nb.select(self.calibrator)
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = JoystickToolApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
