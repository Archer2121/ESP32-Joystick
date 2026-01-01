import serial
import serial.tools.list_ports
import threading
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
import time

OLED_W, OLED_H = 128, 64
SCALE = 4
BAUD = 115200

raw_x = raw_y = 0
norm_x = norm_y = 0.0
direction = "CENTER"

cal = {
    "cx": None, "cy": None,
    "minx": 4095, "maxx": 0,
    "miny": 4095, "maxy": 0
}

# =========================
# AUTO PORT DETECT
# =========================
def find_esp32():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        try:
            ser = serial.Serial(p.device, BAUD, timeout=1)
            time.sleep(1)
            ser.write(b"debug\n")
            for _ in range(5):
                line = ser.readline().decode(errors="ignore")
                if "Raw:" in line:
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
            line = ser.readline().decode(errors="ignore").strip()
            if "Raw:" in line:
                parts = line.replace("|", "").split()
                raw_x, raw_y = map(int, parts[1].split(","))
                norm_x, norm_y = map(float, parts[4].split(","))
                direction = parts[-1]
        except:
            pass

# =========================
# CALIBRATION ACTIONS
# =========================
def capture_center():
    cal["cx"] = raw_x
    cal["cy"] = raw_y

def capture_minmax():
    cal["minx"] = min(cal["minx"], raw_x)
    cal["maxx"] = max(cal["maxx"], raw_x)
    cal["miny"] = min(cal["miny"], raw_y)
    cal["maxy"] = max(cal["maxy"], raw_y)

# =========================
# OLED DRAW
# =========================
def draw_oled():
    img = Image.new("1", (OLED_W, OLED_H))
    d = ImageDraw.Draw(img)

    d.rectangle((0, 0, OLED_W - 1, OLED_H - 1), outline=1)

    cx, cy = OLED_W // 2, OLED_H // 2
    d.ellipse((cx-2, cy-2, cx+2, cy+2), fill=1)

    px = int(cx + norm_x * 28)
    py = int(cy - norm_y * 28)
    d.ellipse((px-3, py-3, px+3, py+3), fill=1)

    d.text((4, 4), f"DIR:{direction}", fill=1)

    return img

# =========================
# TK UI
# =========================
root = tk.Tk()
root.title("ESP32 OLED Mirror + Calibration")

canvas = tk.Canvas(root, width=OLED_W*SCALE, height=OLED_H*SCALE, bg="black")
canvas.grid(row=0, column=0, rowspan=6)

tk.Button(root, text="Capture Center", command=capture_center).grid(row=0, column=1, sticky="ew")
tk.Button(root, text="Capture Min/Max", command=capture_minmax).grid(row=1, column=1, sticky="ew")

info = tk.Label(root, justify="left", font=("Consolas", 9))
info.grid(row=2, column=1, sticky="nw")

def update():
    img = draw_oled().resize((OLED_W*SCALE, OLED_H*SCALE), Image.NEAREST)
    tk_img = ImageTk.PhotoImage(img)
    canvas.img = tk_img
    canvas.create_image(0, 0, anchor="nw", image=tk_img)

    info.config(text=
        f"RAW: {raw_x},{raw_y}\n"
        f"CENTER: {cal['cx']},{cal['cy']}\n"
        f"X: {cal['minx']} → {cal['maxx']}\n"
        f"Y: {cal['miny']} → {cal['maxy']}\n\n"
        "Move stick to extremes\n"
        "Press Min/Max repeatedly\n"
        "Then capture center"
    )

    root.after(20, update)

# =========================
# START
# =========================
threading.Thread(target=serial_worker, daemon=True).start()
update()
root.mainloop()
