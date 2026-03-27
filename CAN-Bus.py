import subprocess
import time
import can
import threading


class CanBus:
    def __init__(self, autostart=True):
        # Eingangssignale der ItC
        self.ITC_signals = {
            "Blinker_L": {"Pin": 1, "Input": 0},
            "Blinker_R": {"Pin": 2, "Input": 0},
            "Aufblenden": {"Pin": 3, "Input": 0},
            "Standlicht": {"Pin": 4, "Input": 0},
            "Scheibenwischer": {"Pin": 5, "Input": 0},
            "Alarmblinker": {"Pin": 7, "Input": 0},
            "Innenbeleuchtung": {"Pin": 6, "Input": 0},
            "Hupe": {"Pin": 8, "Input": 0},
            "Bremslicht": {"Pin": 9, "Input": 0},
        }

        # Ausgangssignale Matic hinten
        self.Matic_hinten = {
            "Blinker_H_L": {"Pin": 1, "Output": 0},
            "Blinker_H_R": {"Pin": 2, "Output": 0},
            "Standlicht": {"Pin": 3, "Output": 0},
            "Bremslicht": {"Pin": 4, "Output": 0},
        }

        # Ausgangssignale Matic vorne
        self.Matic_vorne = {
            "Blinker_V_L": {"Pin": 1, "Output": 0},
            "Blinker_V_R": {"Pin": 2, "Output": 0},
            "Standlicht": {"Pin": 3, "Output": 0},
            "Aufblenden": {"Pin": 4, "Output": 0},
            "Hupe": {"Pin": 5, "Output": 0},
            "Scheibenwischer": {"Pin": 8, "Output": 0},
        }

        # Sicherer Zustand bei Fehlern
        self.safestate = {
            "Blinker_L": 0,
            "Blinker_R": 0,
            "Standlicht": 0,
            "Aufblenden": 0,
            "Bremslicht": 0,
            "Innenbeleuchtung": 0,
            "Hupe": 0,
            "Scheibenwischer": 0,
            "Alarmblinker": 1,
        }
        
        # ItC Konfiguration
        # Aufgrund von einer Geheimhaltungspflicht gegenüber Inomatic können hier keine echten CAN IDs angegeben werden.
        self.ItC = {
            "Heartbeat": "*****",
            "Request": "*****",
            "Request_Response": "*****",
            "Monitor": "*****",
            "Config": "*****",
            "Config_Response": "*****",
        }

        # Matic hinten Konfiguration
        # Aufgrund von einer Geheimhaltungspflicht gegenüber Inomatic können hier keine echten CAN IDs angegeben werden.
        self.Matic = {
            "Heartbeat": "*****",
            "Adress": "*****",
            "Acknowledge": "*****",
        }

        # Matic vorne Konfiguration
        # Aufgrund von einer Geheimhaltungspflicht gegenüber Inomatic können hier keine echten CAN IDs angegeben werden.
        self.Matic_front = {
            "Heartbeat": "*****",
            "Adress": "*****",
            "Acknowledge": "*****",
        }

        # DALY BMS Konfiguration
        self.Daly = {
            "Request_ID": 0x18100140,
            "Response_ID": 0x18104001,
        }

        # DALY BMS Werte
        self.bms_total_voltage = 0.0
        self.bms_gather_voltage = 0.0
        self.bms_current = 0.0
        self.bms_soc = 0.0
        self.bms_max_cell_voltage = 0
        self.bms_max_cell_number = 0
        self.bms_min_cell_voltage = 0
        self.bms_min_cell_number = 0
        self.bms_max_temperature = 0
        self.bms_max_temp_sensor = 0
        self.bms_min_temperature = 0
        self.bms_min_temp_sensor = 0

        # Fehlerflags
        self.errors = {
            "Can_Ackn_Error": False,
            "Can_Send_Error": False,
            "ItC_Timeout": False,
            "MaticRear_Timeout": False,
            "MaticFront_Timeout": False,
            "Listener_Error": False,
            "Daly_Error": False,
        }

        self.blinker_running = False
        self.blinker_frequency = 1.0
        self.alarm_frequency = 2.0
        self.last_message = ""
        self.previous_error_state = False

        self.can_reboot()
        self.full_update()

        if autostart:
            threading.Thread(target=self.listen_can, daemon=True).start()
            threading.Thread(target=self.daly_thread, daemon=True).start()



    # CAN Interface starten
    def can_up(self, interface="can0", bitrate=250000):
        cmd = ["sudo", "ip", "link", "set", interface, "up", "type", "can", "bitrate", str(bitrate)]
        subprocess.run(cmd, check=True)
        print(f"{interface} up, bitrate {bitrate}")

    # CAN Interface stoppen
    def can_down(self, interface="can0"):
        cmd = ["sudo", "ip", "link", "set", interface, "down"]
        subprocess.run(cmd, check=True)
        print(f"{interface} down")



    # CAN Interfaces neu starten
    def can_reboot(self):
        for iface in ("can0", "can1"):
            try:
                self.can_down(interface=iface)
            except Exception:
                pass

        time.sleep(0.2)

        try:
            self.can_up(interface="can0", bitrate=250000)
        except Exception as e:
            print(f"can0 up failed: {e}")

        try:
            self.can_up(interface="can1", bitrate=250000)
        except Exception:
            pass

        time.sleep(0.2)



    # Eingänge auf Safestate setzen
    def update_inputs_to_safestate(self):
        for name, val in self.safestate.items():
            if name in self.ITC_signals:
                self.ITC_signals[name]["Input"] = val



    # Alle Fehler zurücksetzen
    def reset_errors(self):
        for k in self.errors:
            self.errors[k] = False
        print("All errors have been reset.")


    
    # Nachricht von ItC dekodieren
    # Aufgrund von einer Geheimhaltungspflicht kann diese Funktion nicht gezeigt werden.
    def payload_to_input(self, hex_data: str):
        pass



    # Logik von ItC Eingängen auf Matic Ausgänge anwenden
    def itc_to_outputs(self):
        alarm = self.ITC_signals["Alarmblinker"]["Input"]
        bl_l_in = self.ITC_signals["Blinker_L"]["Input"]
        bl_r_in = self.ITC_signals["Blinker_R"]["Input"]

        eff_bl_l = 1 if alarm else bl_l_in
        eff_bl_r = 1 if alarm else bl_r_in

        stand_in = self.ITC_signals["Standlicht"]["Input"]
        high_in = self.ITC_signals["Aufblenden"]["Input"]
        stand = 1 if (stand_in or high_in) else 0

        brake = self.ITC_signals["Bremslicht"]["Input"]
        high = high_in
        horn = self.ITC_signals["Hupe"]["Input"]
        wiper = self.ITC_signals["Scheibenwischer"]["Input"]

        self.Matic_hinten["Blinker_H_L"]["Output"] = eff_bl_l
        self.Matic_hinten["Blinker_H_R"]["Output"] = eff_bl_r
        self.Matic_hinten["Standlicht"]["Output"] = stand
        self.Matic_hinten["Bremslicht"]["Output"] = brake

        self.Matic_vorne["Blinker_V_L"]["Output"] = eff_bl_l
        self.Matic_vorne["Blinker_V_R"]["Output"] = eff_bl_r
        self.Matic_vorne["Standlicht"]["Output"] = stand
        self.Matic_vorne["Aufblenden"]["Output"] = high
        self.Matic_vorne["Hupe"]["Output"] = horn
        self.Matic_vorne["Scheibenwischer"]["Output"] = wiper



    # Blinker-Thread bei Bedarf starten
    def handle_blinker_start(self):
        if (
            self.ITC_signals["Blinker_L"]["Input"]
            or self.ITC_signals["Blinker_R"]["Input"]
            or self.ITC_signals["Alarmblinker"]["Input"]
        ):
            if not self.blinker_running:
                self.blinker_running = True
                threading.Thread(target=self.blinker_thread, daemon=True).start()



    # Nachricht für Matic kodieren
    # Aufgrund von einer Geheimhaltungspflicht kann diese Funktion nicht gezeigt werden.
    def get_payload_from_outputs(self, outputs_dict):
        pass



    # CAN Nachricht senden und optional Antwort abwarten
    def sendframe(self, arbitration_id, payload, acknowledge_id=None, interface="can0", feedback=True):
        def parse_can_id(value):
            if value is None:
                return None, None

            if isinstance(value, str):
                s = value.strip().lower().replace("_", "").replace(" ", "")
                if s.startswith("0x"):
                    can_id = int(s, 16)
                else:
                    is_hex = any(c in "abcdef" for c in s)
                    can_id = int(s, 16 if is_hex else 10)
            elif isinstance(value, int):
                can_id = value
            else:
                raise TypeError(f"CAN ID must be int or str, got {type(value)}")

            if can_id < 0:
                raise ValueError("CAN ID must be >= 0")

            if can_id <= 0x7FF:
                return can_id, False
            if can_id <= 0x1FFFFFFF:
                return can_id, True

            raise ValueError(f"CAN ID out of range: 0x{can_id:X} (max 0x1FFFFFFF)")



        def parse_payload(pl):
            if isinstance(pl, str):
                payload_str = pl.strip().lower().replace("0x", "").replace(" ", "").replace("_", "")
                if len(payload_str) % 2 != 0:
                    raise ValueError("Hex payload string must have even length (2 chars per byte).")
                return bytes.fromhex(payload_str)
            if isinstance(pl, list):
                return bytes(pl)
            return bytes(pl)

        arb_id, arb_ext = parse_can_id(arbitration_id)
        ack_id, ack_ext = parse_can_id(acknowledge_id) if acknowledge_id is not None else (None, None)

        payload_bytes = parse_payload(payload)
        max_attempts = 3 if ack_id is not None else 1

        bus = None
        try:
            bus = can.Bus(channel=interface, interface="socketcan")

            for attempt in range(max_attempts):
                msg = can.Message(
                    arbitration_id=arb_id,
                    data=payload_bytes,
                    is_extended_id=arb_ext
                )

                try:
                    bus.send(msg, timeout=1.0)
                    if feedback:
                        id_fmt = f"0x{msg.arbitration_id:X}"
                        kind = "EXT" if msg.is_extended_id else "STD"
                        print(f"Sent (attempt {attempt + 1}/{max_attempts}) [{kind}]: ID={id_fmt} data={msg.data.hex()}")

                    if ack_id is None:
                        return None

                    mask = 0x1FFFFFFF if ack_ext else 0x7FF
                    bus.set_filters([{
                        "can_id": ack_id,
                        "can_mask": mask,
                        "extended": ack_ext
                    }])

                    timeout = 0.1
                    start_time = time.time()

                    while True:
                        remaining = timeout - (time.time() - start_time)
                        if remaining <= 0:
                            break

                        response = bus.recv(timeout=remaining)
                        if response is None:
                            continue

                        if response.arbitration_id == ack_id and response.is_extended_id == ack_ext:
                            if feedback:
                                r_kind = "EXT" if response.is_extended_id else "STD"
                                print(
                                    f"Answer [{r_kind}]: ID=0x{response.arbitration_id:X} "
                                    f"data={response.data.hex()} time={(time.time() - start_time) * 1000:.1f} ms"
                                )
                            return response.data.hex()

                    if feedback:
                        print(f"No acknowledgment received (attempt {attempt + 1}/{max_attempts}).")

                except can.CanError as e:
                    print("Send failed:", e)
                    self.errors["Can_Send_Error"] = True
                    print("Can_Send_Error set to True.")

            self.errors["Can_Ackn_Error"] = True
            print("Failed to receive acknowledgment after 3 attempts. Can_Ackn_Error set to True.")
            return None

        finally:
            if bus is not None:
                bus.shutdown()



    # DALY Anfrage senden
    def daly_request(self, data_id, interface="can0"):
        payload = [data_id, 0, 0, 0, 0, 0, 0, 0]
        return self.sendframe(
            arbitration_id=self.Daly["Request_ID"],
            payload=payload,
            acknowledge_id=self.Daly["Response_ID"],
            interface=interface,
            feedback=False
        )



    # DALY Datenblock 0x90 auswerten
    def parse_daly_90(self, data_hex):
        if not data_hex:
            return

        data = bytes.fromhex(data_hex)

        self.bms_total_voltage = int.from_bytes(data[0:2], byteorder="big") * 0.1
        self.bms_gather_voltage = int.from_bytes(data[2:4], byteorder="big") * 0.1
        current_raw = int.from_bytes(data[4:6], byteorder="big")
        self.bms_current = (current_raw - 30000) * 0.1
        self.bms_soc = int.from_bytes(data[6:8], byteorder="big") * 0.1



    # DALY Datenblock 0x91 auswerten
    def parse_daly_91(self, data_hex):
        if not data_hex:
            return

        data = bytes.fromhex(data_hex)

        self.bms_max_cell_voltage = int.from_bytes(data[0:2], "big")
        self.bms_max_cell_number = data[2]
        self.bms_min_cell_voltage = int.from_bytes(data[3:5], "big")
        self.bms_min_cell_number = data[5]



    # DALY Datenblock 0x92 auswerten
    def parse_daly_92(self, data_hex):
        if not data_hex:
            return

        data = bytes.fromhex(data_hex)

        self.bms_max_temperature = data[0] - 40
        self.bms_max_temp_sensor = data[1]
        self.bms_min_temperature = data[2] - 40
        self.bms_min_temp_sensor = data[3]



    # DALY zyklisch auslesen
    def daly_thread(self, interval=1.0, interface="can0"):
        try:
            while True:
                try:
                    resp_90 = self.daly_request(0x90, interface=interface)
                    self.parse_daly_90(resp_90)

                    resp_91 = self.daly_request(0x91, interface=interface)
                    self.parse_daly_91(resp_91)

                    resp_92 = self.daly_request(0x92, interface=interface)
                    self.parse_daly_92(resp_92)

                    self.errors["Daly_Error"] = False

                    print(
                        f"BMS: U={self.bms_total_voltage:.1f}V, "
                        f"I={self.bms_current:.1f}A, "
                        f"SOC={self.bms_soc:.1f}%, "
                        f"Tmax={self.bms_max_temperature}°C, "
                        f"Tmin={self.bms_min_temperature}°C"
                    )

                except Exception as e:
                    self.errors["Daly_Error"] = True
                    print(f"Daly thread cycle error: {e}")

                time.sleep(interval)

        except Exception as e:
            self.errors["Daly_Error"] = True
            print(f"Daly thread error: {e}")



    # Matic hinten aktualisieren
    def update_matic_hinten(self):
        data = self.get_payload_from_outputs(self.Matic_hinten)
        self.sendframe(
            self.Matic["Adress"],
            data,
            self.Matic["Acknowledge"],
            interface="can0",
            feedback=False
        )



    # Matic vorne aktualisieren
    def update_matic_vorne(self):
        data = self.get_payload_from_outputs(self.Matic_vorne)
        self.sendframe(
            self.Matic_front["Adress"],
            data,
            self.Matic_front["Acknowledge"],
            interface="can0",
            feedback=False
        )



    # Beide Matic Module aktualisieren
    def update_matics(self):
        self.update_matic_hinten()
        self.update_matic_vorne()



    # Zustand von ItC holen und anwenden
    def full_update(self):
        data = self.sendframe(self.ItC["Request"], [], self.ItC["Request_Response"], feedback=False)
        self.payload_to_input(data)
        self.itc_to_outputs()
        self.handle_blinker_start()
        self.update_matics()



    # Blinker zyklisch takten
    def blinker_thread(self):
        sleep_time_blinker = 1.0 / (2 * self.blinker_frequency)
        sleep_time_alarm = 1.0 / (2 * self.alarm_frequency)
        blinkstate = False

        try:
            while True:
                any_blinker_active = (
                    self.ITC_signals["Blinker_L"]["Input"]
                    or self.ITC_signals["Blinker_R"]["Input"]
                    or self.ITC_signals["Alarmblinker"]["Input"]
                )
                if not any_blinker_active:
                    break

                blinkstate = not blinkstate

                alarm = self.ITC_signals["Alarmblinker"]["Input"]
                left_in = self.ITC_signals["Blinker_L"]["Input"]
                right_in = self.ITC_signals["Blinker_R"]["Input"]

                if alarm:
                    eff_l = blinkstate
                    eff_r = blinkstate
                    time.sleep(sleep_time_alarm)
                else:
                    eff_l = blinkstate if left_in else 0
                    eff_r = blinkstate if right_in else 0
                    time.sleep(sleep_time_blinker)

                self.itc_to_outputs()

                self.Matic_hinten["Blinker_H_L"]["Output"] = eff_l
                self.Matic_hinten["Blinker_H_R"]["Output"] = eff_r
                self.Matic_vorne["Blinker_V_L"]["Output"] = eff_l
                self.Matic_vorne["Blinker_V_R"]["Output"] = eff_r

                self.update_matics()

        except Exception as e:
            print(f"Blinker thread error: {e}")

        finally:
            self.Matic_hinten["Blinker_H_L"]["Output"] = 0
            self.Matic_hinten["Blinker_H_R"]["Output"] = 0
            self.Matic_vorne["Blinker_V_L"]["Output"] = 0
            self.Matic_vorne["Blinker_V_R"]["Output"] = 0
            self.update_matics()
            self.blinker_running = False



    # CAN Nachrichten überwachen
    def listen_can(
        self,
        channel="can0",
        sleep_time=0.01,
        bustype="socketcan",
        heartbeat_timeout=2.0,
        itc_timeout=60.0
    ):
        try:
            bus = can.Bus(channel=channel, interface=bustype)
        except Exception as e:
            self.errors["Listener_Error"] = True
            print(f"CAN Listener start failed: {e}")
            return

        filters = [
            {"can_id": self.ItC["Heartbeat"], "can_mask": 0x7FF, "extended": False},
            {"can_id": self.Matic["Heartbeat"], "can_mask": 0x7FF, "extended": False},
            {"can_id": self.Matic_front["Heartbeat"], "can_mask": 0x7FF, "extended": False},
            {"can_id": self.ItC["Monitor"], "can_mask": 0x7FF, "extended": False},
        ]
        bus.set_filters(filters)

        last_itc_hb = time.time()
        last_matic_rear_hb = time.time()
        last_matic_front_hb = time.time()
        last_itc_msg = time.time()

        try:
            while True:
                now = time.time()

                error = (
                    self.errors["Can_Send_Error"]
                    or self.errors["ItC_Timeout"]
                    or self.errors["MaticRear_Timeout"]
                    or self.errors["MaticFront_Timeout"]
                    or self.errors["Listener_Error"]
                )

                if error and not self.previous_error_state:
                    print("Fehler erkannt, Safestate aktiviert.")
                    self.update_inputs_to_safestate()
                    self.itc_to_outputs()
                    self.handle_blinker_start()
                    self.update_matics()

                self.previous_error_state = error

                msg = bus.recv(1.0)
                if msg is not None:
                    arb = msg.arbitration_id

                    if arb == self.ItC["Heartbeat"]:
                        last_itc_hb = now
                        if self.errors["ItC_Timeout"]:
                            self.reset_errors()
                            self.full_update()

                    elif arb == self.Matic["Heartbeat"]:
                        last_matic_rear_hb = now
                        if self.errors["MaticRear_Timeout"]:
                            self.reset_errors()
                            self.full_update()

                    elif arb == self.Matic_front["Heartbeat"]:
                        last_matic_front_hb = now
                        if self.errors["MaticFront_Timeout"]:
                            self.reset_errors()
                            self.full_update()

                    elif arb == self.ItC["Monitor"]:
                        current_msg_hex = msg.data.hex()
                        if current_msg_hex != self.last_message and not error:
                            self.last_message = current_msg_hex
                            last_itc_msg = now
                            self.payload_to_input(current_msg_hex)
                            self.itc_to_outputs()
                            self.handle_blinker_start()
                            self.update_matics()

                if now - last_itc_hb > heartbeat_timeout:
                    self.errors["ItC_Timeout"] = True

                if now - last_matic_rear_hb > heartbeat_timeout:
                    self.errors["MaticRear_Timeout"] = True

                if now - last_matic_front_hb > heartbeat_timeout:
                    self.errors["MaticFront_Timeout"] = True

                if now - last_itc_msg > itc_timeout and not error:
                    last_itc_msg = now
                    self.full_update()

                time.sleep(sleep_time)

        except Exception as e:
            self.errors["Listener_Error"] = True
            print(f"Listener crashed: {e}")

        finally:
            try:
                bus.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    canbus = CanBus(autostart=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Programm beendet.")