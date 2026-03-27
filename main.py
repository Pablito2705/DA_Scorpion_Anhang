import tkinter as tk
from tkinter import Canvas
from PIL import Image, ImageTk
import os
import random
import threading
import time
import math
from collections import deque

import serial


class RacingEVDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Racing EV Dashboard")
        self.root.geometry("1024x600")
        self.root.configure(bg="#000000")
        self.root.attributes("-fullscreen", False)

        # --- Skalierung: Design-Basis 1280x720 -> tatsächliche 1024x600 --- #
        self.design_w = 1280
        self.design_h = 720
        self.actual_w = 1024
        self.actual_h = 600
        self.scale_x = self.actual_w / self.design_w
        self.scale_y = self.actual_h / self.design_h
        self.tacho_scale = min(self.scale_x, self.scale_y)
        self.tacho_size = int(420 * self.tacho_scale)

        # Fahrzeugdaten (Sim)
        self.speed = 0.0
        self.speed_target = 25.0
        self.rpm = 0.0
        self.voltage = 57.0
        self.current = 0.0          # A (>0 Entladen, <0 Reku)
        self.battery_soc = 85.0
        self.temp_motor = 45.0
        self.temp_battery = 38.0
        self.odometer = 0.0         # km ab 0
        self.max_speed_session = 0

        # LoRa-Telemetrie
        self.lora_link_ok = True

        # Kontrollleuchten
        self.warnings = {
            "left_blinker": False,
            "right_blinker": False,
            "Alarmblinkanlage": False,
            "parking": False,
            "Handbremse": False,
            "high_beam": False,
            "battery_low": False,
            "battery_temp": False,
            "mcu_temp": False,
        }

        # Kommunikations-Fehlerzustände (True = OK, False = LOSS)
        self.errors = {
            "Send-Error": True,
            "ItC-Error": True,
            "Matic-Error": True,
            "Listener-Error": True,
            "Acknowledge-Error": True,
        }
        self.error_labels = {}

        self.blinker_state = False

        # LEFT PANEL

        self.inst_power_kWh = 0.0
        self.energy_wh_min = 0.0            # signed (kWh/min)
        self.energy_wh_min_filtered = 0.0   # signed geglättet
        self.reku_wh_min = 0.0              # positiv
        self.max_energy_whmin = 2.0
        self.energy_bar_gamma = 0.65        # <1.0: stärkerer Anstieg bei kleinen Leistungen
        self.energy_history = deque()       # (t, delta_energy_kwh, delta_distance_km)
        self.avg60_whmin = 0.0              # kWh/km
        self.last_consumption_ts = None

        self.icon_images = {}
        self.scorpion_image = None
        self.load_icon_images()

        self.create_dashboard()
        self.start_simulation()
        self.start_blinker()

    # ---------------------------------------------------------
    # Hilfsfunktionen für Skalierung
    # ---------------------------------------------------------
    def sx(self, x): return x * self.scale_x
    def sy(self, y): return y * self.scale_y

    # ---------------------------------------------------------
    # UART: Empfang und Parsing
    # ---------------------------------------------------------

    def connect_uart(self):
        try:
            # Serielle Verbindung öffnen
            self.ser = serial.Serial(
                self.serial_port,
                self.serial_baudrate,
                timeout=self.serial_timeout
            )

            print(f"UART verbunden: {self.serial_port}")
            return True

        except Exception as e:
            # Falls die Verbindung nicht klappt
            print("UART-Verbindung fehlgeschlagen:", e)
            self.ser = None
            return False


    def parse_data(self, line):

        # Beispiel: SOC:84.5;VOLT:186.2;CURR:12.4;POWER:2308.9

        # Zeile bei ; trennen
        fields = line.strip().split(";")

        for field in fields:
            # Nur gültige Teile mit : verarbeiten
            if ":" not in field:
                continue

            # Schlüssel und Wert trennen
            key, raw_value = field.split(":", 1)
            key = key.strip().upper()
            raw_value = raw_value.strip()

            # Wert in Zahl umwandeln
            try:
                value = float(raw_value)
            except ValueError:
                continue

            # Wert in passende Variable speichern
            if key == "SOC":
                self.battery_soc = value
            elif key == "VOLT":
                self.voltage = value
            elif key == "CURR":
                self.current = value
            elif key == "POWER":
                self.power = value
            elif key == "TMOTOR":
                self.temp_motor = value
            elif key == "TBATT":
                self.temp_battery = value
            elif key == "SPEED":
                self.speed = value
            elif key == "RPM":
                self.rpm = value
            elif key == "ODO":
                self.odometer = value
            elif key == "LORA":

                # 1 = Verbindung OK, 0 = Verbindung verloren
                self.lora_link_ok = bool(int(value))

        # Warnungen automatisch setzen
        self.warnings["battery_low"] = self.battery_soc < 20
        self.warnings["battery_temp"] = self.temp_battery > 50
        self.warnings["mcu_temp"] = self.temp_motor > 75


    def uart_read_loop(self):
        # Erst Verbindung aufbauen
        if not self.connect_uart():
            return

        while True:
            try:
                # Eine komplette Zeile von UART lesen
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()

                # Leere Zeilen überspringen
                if not line:
                    continue

                print("Empfangen:", line)

                # Daten zerlegen und speichern
                self.parse_bms_data(line)

                # Anzeige aktualisieren
                self.root.after(0, self.update_display)
                self.root.after(0, self.update_warning_lights)

            except Exception as e:
                print("UART-Fehler:", e)
                time.sleep(1)


    def start_uart_receiver(self):
        # UART-Empfang in eigenem Thread starten
        threading.Thread(target=self.uart_read_loop, daemon=True).start()

    # ---------------------------------------------------------
    # Layout & UI
    # ---------------------------------------------------------
    def load_icon_images(self):
        icons = [
            "left_blinker", "right_blinker", "Alarmblinkanlage", "parking",
            "Handbremse", "high_beam", "battery_low", "battery_temp", "mcu_temp"
        ]
        for key in icons:
            self.icon_images[key] = {"on": None, "off": None}
            for state in ["on", "off"]:
                file = f"{key}_{state}.png"
                if os.path.exists(file):
                    try:
                        img = Image.open(file).resize((60, 60))
                        self.icon_images[key][state] = ImageTk.PhotoImage(img)
                    except:
                        pass

        if os.path.exists("Scorpion_ICON.png"):
            try:
                img = Image.open("Scorpion_ICON.png").resize((200, 140))
                self.scorpion_image = ImageTk.PhotoImage(img)
            except:
                self.scorpion_image = None

    def create_dashboard(self):
        self.main_canvas = Canvas(self.root, bg="#000000", highlightthickness=0)
        self.main_canvas.pack(fill=tk.BOTH, expand=True)

        self.draw_racing_frame(self.main_canvas)
        self.create_top_warning_bar(self.main_canvas)
        self.create_speed_tacho(self.main_canvas)
        self.create_left_panel(self.main_canvas) 
        self.create_right_panel(self.main_canvas) 
        self.create_bottom_bar(self.main_canvas)  

    def draw_racing_frame(self, canvas):
        accent_color = "#00ffff"

        canvas.create_line(self.sx(15), self.sy(15), self.sx(100), self.sy(15), fill=accent_color, width=4)
        canvas.create_line(self.sx(15), self.sy(15), self.sx(15), self.sy(80), fill=accent_color, width=4)

        canvas.create_line(self.sx(1180), self.sy(15), self.sx(1265), self.sy(15), fill=accent_color, width=4)
        canvas.create_line(self.sx(1265), self.sy(15), self.sx(1265), self.sy(80), fill=accent_color, width=4)

        canvas.create_line(self.sx(15), self.sy(640), self.sx(15), self.sy(705), fill=accent_color, width=4)
        canvas.create_line(self.sx(15), self.sy(705), self.sx(100), self.sy(705), fill=accent_color, width=4)

        canvas.create_line(self.sx(1265), self.sy(640), self.sx(1265), self.sy(705), fill=accent_color, width=4)
        canvas.create_line(self.sx(1180), self.sy(705), self.sx(1265), self.sy(705), fill=accent_color, width=4)

        canvas.create_line(self.sx(15), self.sy(100), self.sx(15), self.sy(620), fill=accent_color, width=4)
        canvas.create_line(self.sx(1265), self.sy(100), self.sx(1265), self.sy(620), fill=accent_color, width=4)

    def create_top_warning_bar(self, canvas):
        bar_frame = tk.Frame(canvas, bg="#0a0a0a")
        canvas.create_window(self.sx(640), self.sy(75), window=bar_frame)

        self.warning_labels = {}
        icons_order = ["left_blinker", "Alarmblinkanlage", "parking", "Handbremse", "high_beam", "right_blinker"]

        for key in icons_order:
            if self.icon_images.get(key, {}).get("off"):
                label = tk.Label(bar_frame, image=self.icon_images[key]["off"], bg="#0a0a0a", bd=0)
            else:
                label = tk.Label(bar_frame, text="?", font=("Arial", 26, "bold"),
                                 bg="#0a0a0a", fg="#333333", width=2)
            label.pack(side=tk.LEFT, padx=20, pady=4)
            self.warning_labels[key] = {"label": label}

    def create_speed_tacho(self, canvas):
        cx, cy = self.sx(640), self.sy(360)

        self.tacho_canvas = Canvas(canvas, width=self.tacho_size, height=self.tacho_size,
                                   bg="#000000", highlightthickness=0)
        canvas.create_window(cx, cy, window=self.tacho_canvas)

        self.draw_tacho()

        self.speed_label = tk.Label(canvas, text="000", font=("Orbitron", 62, "bold"),
                                    fg="#ffffff", bg="#000000")
        canvas.create_window(cx, cy - self.sy(10), window=self.speed_label)

        self.speed_unit = tk.Label(canvas, text="KM/H", font=("Arial", 12, "bold"),
                                   fg="#00ffff", bg="#000000")
        canvas.create_window(cx, cy + self.sy(50), window=self.speed_unit)

        self.max_speed_label = tk.Label(canvas, text="MAX: 0", font=("Arial", 14, "bold"),
                                        fg="#666666", bg="#000000")
        canvas.create_window(cx, cy + self.sy(155), window=self.max_speed_label)

    def draw_tacho(self):
        canvas = self.tacho_canvas
        canvas.delete("all")

        cx = self.tacho_size / 2
        cy = self.tacho_size / 2
        r_outer = 200 * self.tacho_scale
        r_inner = 160 * self.tacho_scale

        num_segments = 50
        segment_denominator = max(1, num_segments - 1)
        for i in range(num_segments):
            progress = i / segment_denominator
            angle = 135 + progress * 270
            rad = math.radians(angle)
            rpm_threshold = progress * 4000

            is_active = self.rpm >= rpm_threshold

            if rpm_threshold >= 3500:
                color = "#ff3333" if is_active else "#331111"
            elif rpm_threshold >= 3000:
                color = "#ffff00" if is_active else "#333311"
            else:
                color = "#00ff00" if is_active else "#113311"

            x1 = cx + (r_outer - 15 * self.tacho_scale) * math.cos(rad)
            y1 = cy + (r_outer - 15 * self.tacho_scale) * math.sin(rad)
            x2 = cx + r_outer * math.cos(rad)
            y2 = cy + r_outer * math.sin(rad)

            width = 7 if is_active else 3
            canvas.create_line(x1, y1, x2, y2, fill=color, width=width, capstyle=tk.ROUND)

        canvas.create_oval(cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner,
                           outline="#333333", width=2)

        for rpm in range(0, 4001, 1000):
            angle = 120 + (rpm / 4000) * 300
            rad = math.radians(angle)

            x1 = cx + (r_inner - 20 * self.tacho_scale) * math.cos(rad)
            y1 = cy + (r_inner - 20 * self.tacho_scale) * math.sin(rad)
            x2 = cx + (r_inner - 5 * self.tacho_scale) * math.cos(rad)
            y2 = cy + (r_inner - 5 * self.tacho_scale) * math.sin(rad)
            canvas.create_line(x1, y1, x2, y2, fill="#888888", width=3)

            x3 = cx + (r_inner - 40 * self.tacho_scale) * math.cos(rad)
            y3 = cy + (r_inner - 40 * self.tacho_scale) * math.sin(rad)
            canvas.create_text(x3, y3, text=str(int(rpm / 1000)),
                               font=("Arial", 12, "bold"), fill="#ffffff")

        canvas.create_text(cx, cy - 80 * self.tacho_scale, text="RPM × 1000",
                           font=("Arial", 10, "bold"), fill="#00ffff")

        rpm_color = "#00ff00"
        if self.rpm > 3500:
            rpm_color = "#ff3333"
        elif self.rpm > 3000:
            rpm_color = "#ffff00"

        canvas.create_text(cx, cy + 90 * self.tacho_scale, text=f"{int(self.rpm)}",
                           font=("Orbitron", 18, "bold"), fill=rpm_color)

        r_dot = 10 * self.tacho_scale
        canvas.create_oval(cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot,
                           fill="#00ffff", outline="#ffffff", width=2)

        canvas.create_oval(cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer,
                           outline="#00ffff", width=5)

    # ---------------------------------------------------------
    # LEFT PANEL: kWh/min 
    # ---------------------------------------------------------
    def create_left_panel(self, canvas):
        x1, y1, x2, y2 = self.sx(80), self.sy(130), self.sx(360), self.sy(610)
        canvas.create_rectangle(x1, y1, x2, y2, outline="#00ffff", width=2, fill="#0a0a0a")
        cx = (x1 + x2) / 2
        ph = (y2 - y1)

        def py(frac):
            return y1 + ph * frac
    
        canvas.create_text(cx, py(0.07), text="AKTUELL",
                           font=("Arial", 12, "bold"), fill="#aaaaaa")

        self.energy_label = tk.Label(
            canvas, text="-0.0 kWh",
            font=("Orbitron", 26, "bold"),
            fg="#00ff88", bg="#0a0a0a"
        )
        canvas.create_window(cx, py(0.15), window=self.energy_label)

        self.energy_bar_canvas = Canvas(
            canvas,
            width=(x2 - x1) * 0.85,
            height=max(14, int(ph * 0.06)),
            bg="#0a0a0a",
            highlightthickness=0
        )
        canvas.create_window(cx, py(0.26), window=self.energy_bar_canvas)

        canvas.create_line(x1, py(0.32), x2, py(0.32), fill="#00ffff", width=1)

        canvas.create_text(cx, py(0.38), text="VERBRAUCH",
                           font=("Arial", 10, "bold"), fill="#00ffff")

        self.avg60_value = tk.Label(
            canvas, text="-0.0 kWh/km",
            font=("Orbitron", 22, "bold"),
            fg="#ffffff", bg="#0a0a0a"
        )
        canvas.create_window(cx, py(0.46), window=self.avg60_value)

        self.reku_label = tk.Label(
            canvas, text="REKU 0.0 kWh",
            font=("Arial", 12, "bold"),
            fg="#888888", bg="#0a0a0a"
        )
        canvas.create_window(cx, py(0.55), window=self.reku_label)

        canvas.create_line(x1, py(0.60), x2, py(0.60), fill="#00ffff", width=1)

        canvas.create_text(cx, py(0.65), text="KOMMUNIKATION",
                           font=("Arial", 12, "bold"), fill="#ffaa00")

        error_frame_h = int(ph * 0.30)
        error_frame_w = int((x2 - x1) * 0.90)
        error_frame = tk.Frame(canvas, bg="#220000", bd=2, relief=tk.RIDGE)
        canvas.create_window(cx, py(0.83), window=error_frame,
                             width=error_frame_w, height=error_frame_h)

        self.error_labels = {}
        for name in ["Send-Error", "ItC-Error", "Matic-Error", "Listener-Error", "Acknowledge-Error"]:
            row = tk.Frame(error_frame, bg="#220000")
            row.pack(anchor="w", pady=1, padx=6)

            tk.Label(row, text=f"{name}:", font=("Arial", 9, "bold"),
                     fg="#ffdd88", bg="#220000").pack(side=tk.LEFT, padx=(0, 6))

            status = tk.Label(row, text="OK", font=("Arial", 9, "bold"),
                              fg="#00ff00", bg="#220000")
            status.pack(side=tk.LEFT)

            self.error_labels[name] = status

        self.update_error_display()

    def draw_energy_bar(self, consumption_whmin):
        c = self.energy_bar_canvas
        c.delete("all")
        w = int(float(c["width"]))
        h = int(float(c["height"]))

        c.create_rectangle(1, 1, w - 1, h - 1, outline="#444444", width=2)

        ratio_linear = max(0.0, min(1.0, consumption_whmin / self.max_energy_whmin))
        ratio = ratio_linear ** self.energy_bar_gamma

        if ratio_linear <= 0.35:
            color = "#00ff00"
        elif ratio_linear <= 0.65:
            color = "#ffff00"
        else:
            color = "#ff3333"

        fill_w = 2 + ratio * (w - 4)
        c.create_rectangle(2, 2, fill_w, h - 2, outline="", fill=color)

    # ---------------------------------------------------------
    # RIGHT PANEL + BOTTOM BAR
    # ---------------------------------------------------------
    def create_right_panel(self, canvas):
        x1, y1, x2, y2 = self.sx(920), self.sy(130), self.sx(1200), self.sy(610)
        canvas.create_rectangle(x1, y1, x2, y2, outline="#00ffff", width=2, fill="#0a0a0a")

        center_x = (x1 + x2) / 2
        canvas.create_text(center_x, y1 + self.sy(30), text="BATTERY SOC",
                           font=("Arial", 18, "bold"), fill="#00ffff")

        self.soc_canvas = Canvas(
            canvas, width=200 * self.scale_x, height=200 * self.scale_y,
            bg="#0a0a0a", highlightthickness=0
        )
        canvas.create_window(center_x, y1 + self.sy(150), window=self.soc_canvas)
        self.draw_battery_circle()

        canvas.create_line(x1, y1 + self.sy(260), x2, y1 + self.sy(260), fill="#00ffff", width=1)

        canvas.create_text(center_x, y1 + self.sy(280), text="MOTOR TEMP",
                           font=("Arial", 14, "bold"), fill="#ff6b35")

        self.temp_motor_label = tk.Label(canvas, text="45°", font=("Orbitron", 30, "bold"),
                                         fg="#ff6b35", bg="#0a0a0a")
        canvas.create_window(center_x, y1 + self.sy(330), window=self.temp_motor_label)

        canvas.create_line(x1, y1 + self.sy(370), x2, y1 + self.sy(370), fill="#00ffff", width=1)

        canvas.create_text(center_x, y1 + self.sy(390), text="BATTERY TEMP",
                           font=("Arial", 14, "bold"), fill="#00ff88")

        self.temp_battery_label = tk.Label(canvas, text="38°", font=("Orbitron", 30, "bold"),
                                           fg="#00ff88", bg="#0a0a0a")
        canvas.create_window(center_x, y1 + self.sy(435), window=self.temp_battery_label)

    def create_bottom_bar(self, canvas):
        y = self.sy(670)

        volt_box = tk.Frame(canvas, bg="#1a1a1a", bd=2, relief=tk.RAISED)
        canvas.create_window(self.sx(180), y, window=volt_box)
        tk.Label(volt_box, text="U", font=("Arial", 14, "bold"),
                 fg="#ffff00", bg="#1a1a1a").pack(side=tk.LEFT, padx=4)
        self.voltage_label = tk.Label(volt_box, text="57.0", font=("Arial", 18, "bold"),
                                      fg="#ffff00", bg="#1a1a1a")
        self.voltage_label.pack(side=tk.LEFT, padx=2)
        tk.Label(volt_box, text="V", font=("Arial", 14),
                 fg="#ffff00", bg="#1a1a1a").pack(side=tk.LEFT, padx=2)

        curr_box = tk.Frame(canvas, bg="#1a1a1a", bd=2, relief=tk.RAISED)
        canvas.create_window(self.sx(360), y, window=curr_box)
        tk.Label(curr_box, text="I", font=("Arial", 14, "bold"),
                 fg="#ff00ff", bg="#1a1a1a").pack(side=tk.LEFT, padx=4)
        self.current_label = tk.Label(curr_box, text="0.0", font=("Arial", 18, "bold"),
                                      fg="#ff00ff", bg="#1a1a1a")
        self.current_label.pack(side=tk.LEFT, padx=2)
        tk.Label(curr_box, text="A", font=("Arial", 14),
                 fg="#ff00ff", bg="#1a1a1a").pack(side=tk.LEFT, padx=2)

        if self.scorpion_image:
            canvas.create_image(self.sx(640), self.sy(650), image=self.scorpion_image)
        else:
            canvas.create_text(self.sx(640), self.sy(650), text="SCORPION",
                               font=("Arial", 20), fill="#00ff00")

        odo_box = tk.Frame(canvas, bg="#1a1a1a", bd=2, relief=tk.RAISED)
        canvas.create_window(self.sx(900), y, window=odo_box)
        tk.Label(odo_box, text="ODO", font=("Arial", 14, "bold"),
                 fg="#00ffff", bg="#1a1a1a").pack(side=tk.LEFT, padx=4)
        self.odo_label = tk.Label(odo_box, text="0.00", font=("Arial", 18, "bold"),
                                  fg="#00ffff", bg="#1a1a1a")
        self.odo_label.pack(side=tk.LEFT, padx=2)
        tk.Label(odo_box, text="km", font=("Arial", 14),
                 fg="#00ffff", bg="#1a1a1a").pack(side=tk.LEFT, padx=2)

        lora_box = tk.Frame(canvas, bg="#1a1a1a", bd=2, relief=tk.RAISED)
        canvas.create_window(self.sx(1120), y, window=lora_box)
        tk.Label(lora_box, text="LoRa", font=("Arial", 14, "bold"),
                 fg="#00ffff", bg="#1a1a1a").pack(side=tk.LEFT, padx=6)

        self.lora_status_label = tk.Label(lora_box, text="OK", font=("Arial", 14, "bold"),
                                          fg="#00ff00", bg="#1a1a1a")
        self.lora_status_label.pack(side=tk.LEFT, padx=6)

    # ---------------------------------------------------------
    # SOC Circle
    # ---------------------------------------------------------
    def draw_battery_circle(self):
        canvas = self.soc_canvas
        canvas.delete("all")

        try:
            w = int(float(canvas["width"]))
            h = int(float(canvas["height"]))
        except Exception:
            w, h = 200, 200

        cx, cy = w // 2, h // 2
        r = min(w, h) // 2 - 10
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#333333", width=6)

        extent = (self.battery_soc / 100.0) * 360.0
        if self.battery_soc > 50:
            color = "#00ff00"
        elif self.battery_soc > 20:
            color = "#ffff00"
        else:
            color = "#ff3333"

        canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                          start=90, extent=-extent, style="arc",
                          outline=color, width=8)

        canvas.create_text(cx, cy - 8, text=f"{int(self.battery_soc)}",
                           font=("Orbitron", 42, "bold"), fill="#ffffff")
        canvas.create_text(cx, cy + 32, text="%", font=("Arial", 20), fill="#888888")

    # ---------------------------------------------------------
    # Updates
    # ---------------------------------------------------------
    def update_error_display(self):
        for name, ok in self.errors.items():
            label = self.error_labels.get(name)
            if not label:
                continue
            label.config(text=("OK" if ok else "LOSS"),
                         fg=("#00ff00" if ok else "#ff3333"))

    def update_warning_lights(self):
        for key, entry in self.warning_labels.items():
            is_on = self.warnings.get(key, False)
            if key in ["left_blinker", "right_blinker", "Alarmblinkanlage"]:
                show = is_on and self.blinker_state
            else:
                show = is_on

            if (self.icon_images.get(key)
                    and self.icon_images[key]["on"]
                    and self.icon_images[key]["off"]):
                img = self.icon_images[key]["on"] if show else self.icon_images[key]["off"]
                entry["label"].config(image=img)

    def update_display(self):

        # Speed
        spd = int(self.speed)
        self.speed_label.config(text=f"{spd:03d}")
        if spd > self.max_speed_session:
            self.max_speed_session = spd
        self.max_speed_label.config(text=f"MAX: {self.max_speed_session}")
        self.draw_tacho()

        # inst_power_kWh >0 Verbrauch, <0 Reku
        self.inst_power_kWh = self.voltage * self.current / 1000.0
        self.energy_wh_min = self.inst_power_kWh 

        # Glättung (signed)
        alpha = 0.18
        self.energy_wh_min_filtered = (1 - alpha) * self.energy_wh_min_filtered + alpha * self.energy_wh_min

        consumption_whmin = max(0.0, self.energy_wh_min_filtered)
        reku_whmin = max(0.0, -self.energy_wh_min_filtered)
        self.reku_wh_min = reku_whmin

        # Verbrauch als kWh/km
        now = time.time()
        dt_s = 0.0 if self.last_consumption_ts is None else max(0.0, now - self.last_consumption_ts)
        self.last_consumption_ts = now

        delta_energy_kwh = consumption_whmin * dt_s / 3600.0
        delta_distance_km = max(0.0, self.speed) * dt_s / 3600.0
        self.energy_history.append((now, delta_energy_kwh, delta_distance_km))

        while self.energy_history and (now - self.energy_history[0][0]) > 60.0:
            self.energy_history.popleft()

        energy_60_kwh = sum(e for _, e, _ in self.energy_history)
        distance_60_km = sum(d for _, _, d in self.energy_history)
        self.avg60_whmin = (energy_60_kwh / distance_60_km) if distance_60_km > 1e-6 else 0.0

        # Anzeige: Verbrauch negativ
        self.energy_label.config(text=f"{-self.energy_wh_min_filtered:.1f} kWh")
        self.avg60_value.config(text=f"{self.avg60_whmin:.2f} kWh/km")

        if self.reku_wh_min > 0.2:
            self.reku_label.config(text=f"REKU {self.reku_wh_min:.1f} kWh", fg="#00ffff")
        else:
            self.reku_label.config(text="REKU 0.0 kWh", fg="#888888")

        self.draw_energy_bar(consumption_whmin)

        # Restliche Anzeigen
        self.current_label.config(text=f"{abs(self.current):.2f}")
        self.voltage_label.config(text=f"{self.voltage:.1f}")
        self.temp_motor_label.config(text=f"{int(self.temp_motor)}°")
        self.temp_battery_label.config(text=f"{int(self.temp_battery)}°")
        self.odo_label.config(text=f"{self.odometer:.2f}")
        self.draw_battery_circle()

        self.lora_status_label.config(
            text=("OK" if self.lora_link_ok else "LOSS"),
            fg=("#00ff00" if self.lora_link_ok else "#ff3333")
        )

        self.update_error_display()

    # ---------------------------------------------------------
    # Simulation 
    # ---------------------------------------------------------
    def simulate_data(self):

        # Simulationsintervall
        dt = 0.15
        while True:
            # Zufallsbasierte Zielwerte
            if random.random() < 0.02:
                self.speed_target = random.uniform(15, 40)

            # Fahrzustand aktualisieren
            self.speed += (self.speed_target - self.speed) * 0.08
            self.speed += random.uniform(-0.3, 0.3)
            self.speed = max(0.0, min(55.0, self.speed))

            # Drehzahl und Spannung simulieren
            self.rpm = max(500.0, min(4000.0, self.speed * 60 + random.uniform(-20, 20)))
            self.voltage = 57.0 + random.uniform(-0.6, 0.6)

            # Leistungsmodell
            target_power_kWh = (self.rpm / 3000.0) * 1.7
            target_power_kWh = max(0.0, min(2.3, target_power_kWh))

            # Strom berechnen in abhängigkeit von Spannung
            base_current = (target_power_kWh * 1000.0 / max(1.0, self.voltage)) + random.uniform(-1.0, 1.0)
            base_current = max(0.0, base_current)

            # Rekuperation
            if self.speed > 10 and random.random() < 0.05:
                self.current = -base_current * random.uniform(0.2, 0.6)
            else:
                self.current = base_current

            # SOC und Kilometerstand nur aktualisieren, wenn das Fahrzeug fährt
            if self.speed > 1:
                self.battery_soc -= random.uniform(0.0005, 0.003)
                self.battery_soc = max(5.0, min(100.0, self.battery_soc))
                self.odometer += self.speed * dt / 3600.0

            # Temperaturen modellieren
            power_kWh_abs = abs(self.voltage * self.current) / 1000.0
            if power_kWh_abs > 0.5:
                self.temp_motor += random.uniform(0.01, 0.05)
                self.temp_battery += random.uniform(0.005, 0.03)
            else:
                self.temp_motor -= random.uniform(0.005, 0.03)
                self.temp_battery -= random.uniform(0.002, 0.02)

            # Grenzwerte einhalten
            self.temp_motor = max(25.0, min(90.0, self.temp_motor))
            self.temp_battery = max(25.0, min(60.0, self.temp_battery))

            # Kommunikationsstatus simulieren
            if random.random() < 0.01:
                self.lora_link_ok = False
            elif random.random() < 0.1:
                self.lora_link_ok = True

            # Fehlerstatus simulieren
            flip_p = 0.001 if self.lora_link_ok else 0.01
            for k in self.errors.keys():
                if random.random() < flip_p:
                    self.errors[k] = not self.errors[k]

            # Anzeige aktualisieren
            self.root.after(0, self.update_display)
            time.sleep(dt)

    def blink_animation(self):
        while True:
            self.blinker_state = not self.blinker_state
            self.root.after(0, self.update_warning_lights)
            time.sleep(0.5)

    def start_simulation(self):
        threading.Thread(target=self.simulate_data, daemon=True).start()

    def start_blinker(self):
        threading.Thread(target=self.blink_animation, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = RacingEVDashboard(root)
    root.mainloop()
