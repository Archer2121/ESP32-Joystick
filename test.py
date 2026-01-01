import serial
import serial.tools.list_ports
import threading
import tkinter as tk
import time

BAUD = 115200

# =========================
# RAW STATE
# =========================
raw_x = raw_y = 0
norm_x = norm_y = 0.0
direction = "CENTER"

# =========================
# CALIBRATION DATA
# =========================
cal = {
    "cx": None, "cy": None,
    "minx": 4095, "maxx": 0,
    "miny": 4095, "maxy": 0,
    "deadzone": 0.08
}

# =========================
# AUTO PORT DETECT
# =========================
def find_esp32():
    for p in serial.tools.list_ports.comports():
        try:
            ser = serial.Serial(p.device, BAUD, timeout=1)
            time.sleep(1)
            ser.write(b"debug\n")
            for _ in range(5):
                if b"Raw:" in ser.readline():
                    return ser
            ser.close()
        except:
            pass
    return None

# =========================
# SERIAL THREAD
# =========================
def serial_worker():
    global raw_x, raw_y, norm_x, norm_y, direction
    ser = None
    while ser is None:
        ser = find_esp32()
        time.sleep(1)

    while True:
        try:
            line = ser.readline().decode(errors="ignore")
            if "Raw:" in line:
                parts = line.replace("|", "").split()
                raw_x, raw_y = map(int, parts[1].split(","))
                norm_x, norm_y = map(float, parts[4].split(","))
                direction = parts[-1]
        except:
            pass

# =========================
# CALC HELPERS
# =========================
def calibrated(val, c, mn, mx):
    if c is None or mx == mn:
        return 0.0
    return (val - c) / (mx - c) if val >= c else (val - c) / (c - mn)

def apply_deadzone(v, dz):
    if abs(v) < dz:
        return 0.0
    return (v - dz if v > 0 else v + dz) / (1 - dz)

# =========================
# TK UI (CREATE ROOT FIRST!)
# =========================
root = tk.Tk()
root.title("ESP32 Joystick Visualizer + Calibration")
root.configure(bg="#111")

use_cal = tk.BooleanVar(value=True)

JOY_SIZE = 260
BAR_W = 260

joy_canvas = tk.Canvas(root, width=JOY_SIZE, height=JOY_SIZE, bg="#111", highlightthickness=0)
joy_canvas.grid(row=0, column=0, rowspan=6, padx=10, pady=10)

# Controls
tk.Button(root, text="Capture Center",
          command=lambda: cal.update(cx=raw_x, cy=raw_y)
          ).grid(row=0, column=1, sticky="ew")

tk.Button(root, text="Capture Min/Max",
          command=lambda: cal.update(
              minx=min(cal["minx"], raw_x),
              maxx=max(cal["maxx"], raw_x),
              miny=min(cal["miny"], raw_y),
              maxy=max(cal["maxy"], raw_y))
          ).grid(row=1, column=1, sticky="ew")

tk.Checkbutton(root, text="Use Calibration",
               variable=use_cal, bg="#111", fg="white",
               selectcolor="#111").grid(row=2, column=1, sticky="w")

dz_slider = tk.Scale(root, from_=0, to=0.25, resolution=0.01,
                     orient="horizontal", label="Deadzone",
                     bg="#111", fg="white", highlightthickness=0)
dz_slider.set(cal["deadzone"])
dz_slider.grid(row=3, column=1, sticky="ew")

info = tk.Label(root, font=("Consolas", 10), fg="white", bg="#111", justify="left")
info.grid(row=4, column=1, sticky="nw")

bar_x = tk.Canvas(root, width=BAR_W, height=22, bg="#111", highlightthickness=0)
bar_x.grid(row=6, column=0, columnspan=2)
bar_y = tk.Canvas(root, width=BAR_W, height=22, bg="#111", highlightthickness=0)
bar_y.grid(row=7, column=0, columnspan=2)

# =========================
# DRAW LOOP
# =========================
def update():
    joy_canvas.delete("all")

    pad = 20
    cx = JOY_SIZE // 2
    cy = JOY_SIZE // 2
    radius = JOY_SIZE // 2 - pad

    # Frame
    joy_canvas.create_rectangle(pad, pad, JOY_SIZE-pad, JOY_SIZE-pad, outline="#555")
    joy_canvas.create_line(cx, pad, cx, JOY_SIZE-pad, fill="#222")
    joy_canvas.create_line(pad, cy, JOY_SIZE-pad, cy, fill="#222")

    # Deadzone
    dz = dz_slider.get()
    dzr = radius * dz
    joy_canvas.create_oval(cx-dzr, cy-dzr, cx+dzr, cy+dzr, outline="#333")

    # Value selection
    if use_cal.get():
        vx = apply_deadzone(calibrated(raw_x, cal["cx"], cal["minx"], cal["maxx"]), dz)
        vy = apply_deadzone(calibrated(raw_y, cal["cy"], cal["miny"], cal["maxy"]), dz)
    else:
        vx, vy = norm_x, norm_y

    # Stick dot
    px = cx + vx * radius * 0.85
    py = cy - vy * radius * 0.85
    joy_canvas.create_oval(px-7, py-7, px+7, py+7, fill="white")

    # Bars
    for bar, val, label in [(bar_x, vx, "X"), (bar_y, -vy, "Y")]:
        bar.delete("all")
        bar.create_rectangle(0, 6, BAR_W, 16, outline="#333")
        bar.create_rectangle(BAR_W//2, 6, BAR_W//2 + val*(BAR_W//2-4), 16, fill="white")
        bar.create_text(8, 11, text=f"{label} {int(val*100)}%", fill="white", anchor="w")

    info.config(text=
        f"CENTER: {cal['cx']},{cal['cy']}\n"
        f"X: {cal['minx']} → {cal['maxx']}\n"
        f"Y: {cal['miny']} → {cal['maxy']}\n"
        f"Mode: {'CAL' if use_cal.get() else 'RAW'}"
    )

    root.after(16, update)

# =========================
# START
# =========================
threading.Thread(target=serial_worker, daemon=True).start()
update()
root.mainloop()
