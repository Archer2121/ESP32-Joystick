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


class SerialManager:
    """Simple serial backend that reads lines and dispatches them to a queue."""
    def __init__(self, out_queue):
        self.serial = None
        self.port = None
        self.alive = False
        self.thread = None
        self.out_q = out_queue

    def connect(self, port, baud=BAUDRATE):
        if not port:
            raise RuntimeError('No port')
        if self.serial and getattr(self.serial, 'is_open', False) and self.port == port:
            return
        self.disconnect()
        self.port = port
        self.serial = serial.Serial(port, baud, timeout=READ_TIMEOUT)
        self.alive = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def disconnect(self):
        try:
            self.alive = False
            if self.thread:
                try:
                    self.thread.join(timeout=0.5)
                except Exception:
                    pass
                self.thread = None
            if self.serial:
                try:
                    self.serial.close()
                except Exception:
                    pass
                self.serial = None
            self.port = None
        except Exception:
            pass

    def _read_loop(self):
        while self.alive and self.serial and getattr(self.serial, 'is_open', False):
            try:
                line = self.serial.readline()
                if not line:
                    time.sleep(0.01)
                    continue
                try:
                    text = line.decode(errors='replace')
                except Exception:
                    text = str(line)
                try:
                    self.out_q.put(text)
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.out_q.put(f"<ERROR reading serial: {e}>\n")
                except Exception:
                    pass
                break

    def write(self, cmd: str):
        if not (self.serial and getattr(self.serial, 'is_open', False)):
            raise RuntimeError('Serial not open')
        self.serial.write((cmd + '\n').encode())



class CalibratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Joystick Calibrator")

        # queue receives lines from SerialManager
        self.q = queue.Queue()
        self.serial_manager = SerialManager(self.q)
        # settings: selected port and output visibility
        self.settings_port = tk.StringVar()
        # legacy attributes (kept for compatibility)
        self.serial = None
        self.read_thread = None
        self.alive = threading.Event()

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
        # Port selection moved to Settings dialog; add Settings button
        ttk.Button(port_row, text="Settings", width=10, command=self.open_settings).grid(row=0, column=1, padx=(6, 4))

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
        # keep settings_port in sync if empty
        if port_list and not self.settings_port.get():
            try:
                self.settings_port.set(port_list[0])
            except Exception:
                pass
        return port_list

    def _auto_connect(self):
        ports = self.refresh_ports()
        if ports and len(ports) > 0:
            # if no settings port chosen, use first
            try:
                if not self.settings_port.get():
                    self.settings_port.set(ports[0])
            except Exception:
                pass
            # attempt connect if we have a chosen port
            if self.settings_port.get():
                self.connect()

    def toggle_connect(self):
        # kept for compatibility; prefer Settings dialog to manage connection
        if self.serial and getattr(self.serial, 'is_open', False):
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.settings_port.get()
        if not port:
            messagebox.showwarning("No Port", "Please select a COM port first.")
            return
        # use the shared SerialManager backend
        try:
            # disconnect first if manager already connected to different port
            try:
                if getattr(self.serial_manager, 'serial', None) and getattr(self.serial_manager.serial, 'is_open', False):
                    current = getattr(self.serial_manager.serial, 'port', None)
                    if current and current != port:
                        self.serial_manager.disconnect()
            except Exception:
                pass
            self.serial_manager.connect(port)
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))
            return
        self.status_var.set(f"Connected: {port} @ {BAUDRATE}")
        # query firmware version after connecting
        self.query_device_version()

    def disconnect(self):
        # disconnect shared backend
        try:
            self.serial_manager.disconnect()
        except Exception:
            pass
        # legacy cleanup
        self.alive.clear()
        if self.read_thread:
            try:
                self.read_thread.join(timeout=0.5)
            except Exception:
                pass
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
        # reading is handled by SerialManager which pushes into self.q
        return

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
        # prefer the shared serial manager
        try:
            if self.serial_manager and getattr(self.serial_manager, 'serial', None) and getattr(self.serial_manager.serial, 'is_open', False):
                try:
                    self.serial_manager.write(cmd)
                    if self.show_output.get():
                        self.append_log(f"> {cmd}\n")
                    return
                except Exception as e:
                    messagebox.showerror("Send Failed", str(e))
                    return
        except Exception:
            pass

        if not (self.serial and getattr(self.serial, 'is_open', False)):
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
        # prefer shared manager
        try:
            if not (self.serial_manager and getattr(self.serial_manager, 'serial', None) and getattr(self.serial_manager.serial, 'is_open', False)):
                return
        except Exception:
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
        # prefer shared manager
        try:
            if not (self.serial_manager and getattr(self.serial_manager, 'serial', None) and getattr(self.serial_manager.serial, 'is_open', False)):
                messagebox.showwarning("Not Connected", "Open a serial connection first.")
                return
        except Exception:
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

    def open_settings(self):
        # modal settings dialog to choose COM port and serial output visibility
        dlg = tk.Toplevel(self.root)
        dlg.title("Settings")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="COM Port:").grid(row=0, column=0, sticky='w', padx=8, pady=(8,4))
        ports = [p.device for p in serial.tools.list_ports.comports()]
        port_cb = ttk.Combobox(dlg, values=ports, state='readonly', width=28, textvariable=self.settings_port)
        port_cb.grid(row=0, column=1, padx=8, pady=(8,4))

        ttk.Label(dlg, text="Show Serial Output:").grid(row=1, column=0, sticky='w', padx=8, pady=(4,8))
        show_chk = ttk.Checkbutton(dlg, variable=self.show_output)
        show_chk.grid(row=1, column=1, sticky='w', padx=8, pady=(4,8))

        def on_save():
            sel = self.settings_port.get()
            # try to connect to selected port
            if sel:
                try:
                    # if manager already connected to other port, restart
                    if getattr(self.serial_manager, 'serial', None) and getattr(self.serial_manager.serial, 'is_open', False):
                        current = getattr(self.serial_manager.serial, 'port', None)
                        if current and current != sel:
                            self.serial_manager.disconnect()
                    if not getattr(self.serial_manager, 'serial', None) or not getattr(self.serial_manager.serial, 'is_open', False):
                        self.serial_manager.connect(sel)
                        self.status_var.set(f"Connected: {sel} @ {BAUDRATE}")
                except Exception as e:
                    messagebox.showerror("Connection Failed", str(e))
                    # keep dialog open for retry
                    return
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.grid(row=2, column=0, columnspan=2, pady=(0,8))
        ttk.Button(btn_frame, text="Save", command=on_save).grid(row=0, column=0, padx=6)
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).grid(row=0, column=1, padx=6)


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
