"""
ESP32-Joystick Calibrator GUI
- Polished Tkinter UI
- Serial connect, background reader
- Hideable serial log
- Calibration modal that sends 'cal' and 'next'

Run: python calibrator_gui.py
Requires: pyserial
"""

import threading
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
import os
import re
from tkinter import ttk, scrolledtext, messagebox

try:
    import serial
    import serial.tools.list_ports
except Exception:
    print("Missing dependency: pyserial. Install with: pip install pyserial")
    raise

BAUDRATE = 115200
READ_TIMEOUT = 0.1


class CalibratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Joystick Calibrator")

        self.serial = None
        self.read_thread = None
        self.alive = threading.Event()
        self.q = queue.Queue()

        self._build_ui()
        self._poll_serial_queue()

        # load latest version from repo (used as GitHub reference)
        try:
            base = os.path.dirname(__file__)
            with open(os.path.join(base, 'version.txt'), 'r', encoding='utf-8') as f:
                self.latest_version = f.read().strip()
        except Exception:
            self.latest_version = None

        self.device_version = None
        self.awaiting_version = False

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass

        heading_font = tkfont.Font(size=11, weight='bold')
        mono_font = tkfont.Font(family='Courier', size=10)

        frm = ttk.Frame(self.root, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        paned = ttk.Panedwindow(frm, orient=tk.HORIZONTAL)
        paned.grid(row=0, column=0, sticky='nsew')
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)

        left = ttk.Frame(paned, padding=(8, 8))
        right = ttk.Frame(paned, padding=(8, 8))
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        # Port selection
        port_row = ttk.Frame(left)
        port_row.grid(row=0, column=0, sticky="we", pady=(0, 8))
        ttk.Label(port_row, text="Port:", font=heading_font).grid(row=0, column=0, sticky='w')
        self.port_cb = ttk.Combobox(port_row, width=20, state="readonly")
        self.port_cb.grid(row=0, column=1, padx=(6, 4))
        ttk.Button(port_row, text="Refresh", width=10, command=self.refresh_ports).grid(row=0, column=2, padx=(4, 0))
        self.connect_btn = ttk.Button(port_row, text="Connect", width=10, command=self.toggle_connect)
        self.connect_btn.grid(row=0, column=3, padx=(6, 0))

        # Controls
        controls_lbl = ttk.Label(left, text="Controls", font=heading_font)
        controls_lbl.grid(row=1, column=0, sticky='w')
        controls = ttk.Frame(left)
        controls.grid(row=2, column=0, sticky="we", pady=(6, 10))

        btn_opts = {'width': 16}
        ttk.Button(controls, text="Calibrate", command=self.open_calibration_dialog, **btn_opts).grid(row=0, column=0, padx=4, pady=3)
        ttk.Button(controls, text="Next", command=lambda: self.send_cmd("next"), **btn_opts).grid(row=1, column=0, padx=4, pady=3)
        ttk.Button(controls, text="Visualize", command=lambda: self.send_cmd("viz"), **btn_opts).grid(row=2, column=0, padx=4, pady=3)
        ttk.Button(controls, text="Run", command=lambda: self.send_cmd("run"), **btn_opts).grid(row=3, column=0, padx=4, pady=3)
        ttk.Button(controls, text="Version", command=lambda: self.send_cmd("version"), **btn_opts).grid(row=4, column=0, padx=4, pady=3)
        ttk.Button(controls, text="Toggle Debug", command=lambda: self.send_cmd("debug"), **btn_opts).grid(row=5, column=0, padx=4, pady=3)

        # Settings
        dz_frame = ttk.LabelFrame(left, text='Settings')
        dz_frame.grid(row=3, column=0, sticky='we', pady=(6, 0))
        ttk.Label(dz_frame, text="Deadzone:").grid(row=0, column=0, sticky='w', padx=(6, 6), pady=6)
        self.dz_var = tk.StringVar(value="0.15")
        ttk.Entry(dz_frame, width=8, textvariable=self.dz_var).grid(row=0, column=1, sticky='w')
        ttk.Button(dz_frame, text="Set", command=self.set_deadzone).grid(row=0, column=2, padx=6)

        self.show_output = tk.BooleanVar(value=True)
        ttk.Checkbutton(dz_frame, text="Show Serial Output", variable=self.show_output, command=self._update_output_visibility).grid(row=1, column=0, columnspan=3, sticky='w', padx=6, pady=(0, 6))

        # Status
        self.status_var = tk.StringVar(value="Disconnected")
        status = ttk.Label(left, textvariable=self.status_var, relief='ridge', padding=6)
        status.grid(row=4, column=0, sticky='we', pady=(10, 0))

        # Right: serial log
        self.log_frame = ttk.LabelFrame(right, text="Serial Log")
        self.log_frame.grid(row=0, column=0, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.log = scrolledtext.ScrolledText(self.log_frame, height=20, state="disabled", wrap="none", font=mono_font)
        self.log.grid(row=0, column=0, sticky="nsew")

        log_buttons = ttk.Frame(self.log_frame)
        log_buttons.grid(row=1, column=0, sticky='e', pady=(6, 0))
        ttk.Button(log_buttons, text="Clear Log", command=self.clear_log).grid(row=0, column=0, padx=4)
        ttk.Button(log_buttons, text="Copy All", command=self.copy_log).grid(row=0, column=1, padx=4)

        self.refresh_ports()
        # attempt auto-connect after UI settles
        self.root.after(200, self._auto_connect)

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.port_cb['values'] = port_list
        if port_list:
            try:
                self.port_cb.current(0)
            except Exception:
                pass

    def _auto_connect(self):
        vals = self.port_cb['values']
        if vals and len(vals) > 0:
            # ensure combobox has a value
            try:
                if not self.port_cb.get():
                    self.port_cb.current(0)
            except Exception:
                pass
            # try connect
            self.connect()

    def toggle_connect(self):
        if self.serial and self.serial.is_open:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_cb.get()
        if not port:
            messagebox.showwarning("No Port", "Please select a COM port first.")
            return
        try:
            self.serial = serial.Serial(port, BAUDRATE, timeout=READ_TIMEOUT)
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))
            return

        self.alive.set()
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        self.status_var.set(f"Connected: {port} @ {BAUDRATE}")
        try:
            self.connect_btn.config(text='Disconnect')
        except Exception:
            pass
        # query firmware version after connecting
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
        self.status_var.set("Disconnected")
        try:
            self.connect_btn.config(text='Connect')
        except Exception:
            pass

    def _read_loop(self):
        while self.alive.is_set() and self.serial and self.serial.is_open:
            try:
                line = self.serial.readline()
                if line:
                    try:
                        text = line.decode(errors='replace')
                    except Exception:
                        text = str(line)
                    self.q.put(text)
                else:
                    time.sleep(0.01)
            except Exception as e:
                self.q.put(f"<ERROR reading serial: {e}>\n")
                break

    def _poll_serial_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                # check for version string first
                if self.awaiting_version:
                    m = re.search(r'FW_VERSION\s*[:=]?\s*([0-9]+\.[0-9]+\.[0-9]+)', msg)
                    if m:
                        self.device_version = m.group(1)
                        self.awaiting_version = False
                        self._update_version_label()
                if self.show_output.get():
                    self.append_log(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_serial_queue)

    def append_log(self, text):
        try:
            self.log.configure(state='normal')
            self.log.insert('end', text)
            self.log.see('end')
            self.log.configure(state='disabled')
        except Exception:
            pass

    def clear_log(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def copy_log(self):
        try:
            txt = self.log.get('1.0', 'end')
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
        except Exception:
            pass

    def send_cmd(self, cmd):
        if not (self.serial and self.serial.is_open):
            messagebox.showwarning("Not Connected", "Open a serial connection first.")
            return
        try:
            self.serial.write((cmd + "\n").encode())
            if self.show_output.get():
                self.append_log(f"> {cmd}\n")
        except Exception as e:
            messagebox.showerror("Send Failed", str(e))

    def query_device_version(self):
        # send version request and wait for response handled in _poll_serial_queue
        if not (self.serial and self.serial.is_open):
            return
        self.awaiting_version = True
        try:
            self.send_cmd("version")
        except Exception:
            pass
        # timeout if no response in 2s
        self.root.after(2000, self._version_timeout)

    def _version_timeout(self):
        if self.awaiting_version:
            self.awaiting_version = False
            # mark as unknown
            self.device_version = None
            self._update_version_label()

    def _update_version_label(self):
        # create label if missing
        if not hasattr(self, 'ver_label'):
            self.ver_var = tk.StringVar(value='')
            self.ver_label = tk.Label(self.root, textvariable=self.ver_var)
            # place it under status (use grid) — find left frame location
            try:
                # assume left frame is at grid row 0/col 0 of paned; place near status
                self.ver_label.place(x=12, y=200)
            except Exception:
                pass

        if self.device_version:
            text = f"Device: {self.device_version}"
        else:
            text = "Device: unknown"
        if self.latest_version:
            text += f"   Latest: {self.latest_version}"
        self.ver_var.set(text)

        # color
        try:
            if self.device_version and self.latest_version and self.device_version != self.latest_version:
                self.ver_label.config(fg='red')
            else:
                self.ver_label.config(fg='green')
        except Exception:
            pass

    def open_calibration_dialog(self):
        # Open a modal dialog with calibration instructions. Send initial 'cal' command.
        if not (self.serial and self.serial.is_open):
            messagebox.showwarning("Not Connected", "Open a serial connection first.")
            return

        try:
            self.send_cmd("cal")
        except Exception:
            pass

        dlg = tk.Toplevel(self.root)
        dlg.title("Calibration Wizard")
        dlg.transient(self.root)
        dlg.grab_set()

        instr_var = tk.StringVar()
        steps = [
            "Step 1: Center the stick and press Next to save center.",
            "Step 2: Rotate the stick to all edges (min/max). Press Next to finish.",
            "Calibration complete. Close this dialog."
        ]
        instr_var.set(steps[0])

        lbl = ttk.Label(dlg, textvariable=instr_var, wraplength=420, justify="left", padding=(12, 12))
        lbl.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6))

        step_state = {"index": 0}

        def on_next():
            # Send 'next' and advance dialog
            self.send_cmd("next")
            step_state['index'] += 1
            if step_state['index'] < len(steps):
                instr_var.set(steps[step_state['index']])
            if step_state['index'] >= len(steps) - 1:
                next_btn.config(text="Close", command=dlg.destroy)

        def on_cancel():
            dlg.destroy()

        next_btn = ttk.Button(dlg, text="Next", command=on_next)
        next_btn.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="e")
        ttk.Button(dlg, text="Cancel", command=on_cancel).grid(row=1, column=1, padx=12, pady=(0, 12), sticky="w")

        dlg.columnconfigure(0, weight=1)
        dlg.columnconfigure(1, weight=1)
        self.root.wait_window(dlg)

    def _update_output_visibility(self):
        # Show or hide the serial log frame without stopping the reader thread
        if self.show_output.get():
            try:
                self.log_frame.grid()
            except Exception:
                pass
        else:
            try:
                self.log_frame.grid_remove()
            except Exception:
                pass

    def set_deadzone(self):
        val = self.dz_var.get().strip()
        try:
            f = float(val)
        except ValueError:
            messagebox.showwarning("Invalid Value", "Deadzone must be a number (e.g. 0.2)")
            return
        if f < 0 or f >= 0.9:
            messagebox.showwarning("Out Of Range", "Deadzone must be >=0 and <0.9")
            return
        self.send_cmd(f"set_deadzone {f}")

    def on_close(self):
        self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = CalibratorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
