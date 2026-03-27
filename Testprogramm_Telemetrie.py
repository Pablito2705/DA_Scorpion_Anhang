# Testprogramm für LoRa-Telemetrie-Sender

import time
import random
import sx126x

# ---------------------------------------------------------
# LoRa-Modul initialisieren
# ---------------------------------------------------------
node = sx126x.sx126x(
    serial_num="/dev/ttyAMA0",
    freq=868,
    addr=0,
    power=22,
    rssi=True,
    air_speed=2400,
    relay=False
)

# ---------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------
target_address = 0
target_frequency = 868
send_interval = 1  # Sekunden

# ---------------------------------------------------------
# Startwerte für Testdaten
# ---------------------------------------------------------
soc = 85.0
volt = 186.0
curr = 8.0
temp_motor = 42.0
temp_battery = 31.0
speed = 0.0
rpm = 0.0
odo = 154.7
lora = 1

# ---------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------
def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))

# ---------------------------------------------------------
# LoRa-Datenpaket bauen
# ---------------------------------------------------------
def build_lora_packet(message, target_address, target_frequency):
    offset_frequency = target_frequency - (850 if target_frequency > 850 else 410)

    data = (
        bytes([target_address >> 8]) +
        bytes([target_address & 0xFF]) +
        bytes([offset_frequency]) +
        bytes([node.addr >> 8]) +
        bytes([node.addr & 0xFF]) +
        bytes([node.offset_freq]) +
        message.encode("utf-8")
    )
    return data

# ---------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------
try:
    time.sleep(1)  # kurze Initialisierungszeit
    print("LoRa-Testsender gestartet")

    while True:
        # Geschwindigkeit etwas variieren
        speed += random.uniform(-3.0, 5.0)
        speed = clamp(speed, 0.0, 65.0)

        # Drehzahl grob aus Geschwindigkeit ableiten
        rpm = speed * random.uniform(90.0, 115.0)
        rpm = clamp(rpm, 0.0, 6500.0)

        # Strom abhängig von Geschwindigkeit
        curr = 2.0 + speed * 0.35 + random.uniform(-2.0, 2.0)
        curr = clamp(curr, -10.0, 60.0)

        # Spannung leicht schwankend
        volt += random.uniform(-0.4, 0.2)
        volt = clamp(volt, 175.0, 189.0)

        # Leistung berechnen
        power = volt * curr

        # SOC langsam sinken lassen
        soc -= random.uniform(0.01, 0.08)
        soc = clamp(soc, 0.0, 100.0)

        # Temperaturen leicht dynamisch
        temp_motor += 0.015 * speed + random.uniform(-0.8, 0.6)
        temp_motor = clamp(temp_motor, 25.0, 95.0)

        temp_battery += 0.006 * abs(curr) + random.uniform(-0.3, 0.2)
        temp_battery = clamp(temp_battery, 20.0, 60.0)

        # Kilometerzähler erhöhen
        odo += speed / 3600.0

        # LoRa-Link gelegentlich simuliert schlecht
        lora = 0 if random.random() < 0.03 else 1

        # Nachricht exakt im erwarteten Format
        message = (
            f"SOC:{soc:.1f};"
            f"VOLT:{volt:.1f};"
            f"CURR:{curr:.1f};"
            f"POWER:{power:.1f};"
            f"TMOTOR:{temp_motor:.1f};"
            f"TBATT:{temp_battery:.1f};"
            f"SPEED:{speed:.1f};"
            f"RPM:{rpm:.0f};"
            f"ODO:{odo:.1f};"
            f"LORA:{lora}"
        )

        # LoRa-Paket bauen und senden
        data = build_lora_packet(message, target_address, target_frequency)
        node.send(data)

        print("Gesendet:", message)

        time.sleep(send_interval)

except KeyboardInterrupt:
    print("\nProgramm beendet.")

except Exception as e:
    print("Fehler:", e)