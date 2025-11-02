# Program: rd03d_async.py
# Purpose: Asynchrone Python-Klasse zur Kommunikation mit dem RD03D mmWave Radar Sensor über UART.
#          Basiert auf der rd03d.py Klasse, adaptiert für asyncio und aioserial.
# Author: Dr. Ralf Korell / CircuIT (basierend auf rd03d.py)
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 12:00 UTC - Korrektur: aioserial.AioSerial Instanziierung ist nicht awaitable.
# Modified: October 17, 2025, 12:10 UTC - Korrektur: reset_input_buffer() und close() sind nicht async.
# Modified: October 17, 2025, 12:55 UTC - Korrektur der Frame-Erkennung und Pufferbereinigung in update_async().
# Modified: October 17, 2025, 13:05 UTC - Erneute Korrektur der Pufferbereinigung in update_async() nach Original-Logik.
# Modified: October 17, 2025, 13:20 UTC - Hinzufügen von Debug-Meldungen für systematische Fehlersuche.
# Modified: October 17, 2025, 13:40 UTC - Finale Korrektur der Pufferbereinigung und Frame-Erkennung nach Original-Logik.
# Modified: October 17, 2025, 13:50 UTC - Erneute und finale Korrektur der Pufferbereinigung in update_async() nach exakter Original-Logik.
# Modified: October 17, 2025, 14:00 UTC - Korrektur der erwarteten Frame-Länge auf 30 Bytes für alle Modi.
# Modified: October 17, 2025, 14:35 UTC - Leere Targets im Debug-Log unterdrücken.
# Modified: October 26, 2025, 12:45 UTC - Target-Dekodierung-Ausgabe auf TRACE-Mode umgestellt für bessere Log-Übersicht.
# Modified: November 02, 2025, 16:55 UTC - Korrektur (Root Cause Fix): self.targets speichert nur noch Targets mit distance > 0.

import aioserial
import asyncio
import math
import logging
import globals_state as gs

class Target:
    def __init__(self, x, y, speed, pixel_distance):
        self.x = x                  # mm
        self.y = y                  # mm
        self.speed = speed          # cm/s
        self.pixel_distance = pixel_distance  # mm
        self.distance = math.sqrt(x**2 + y**2) # Berechnete Gesamtentfernung
        self.angle = math.degrees(math.atan2(x, y)) # Berechneter Winkel
    
    def __str__(self):
        return ('Target(x={}mm, y={}mm, speed={}cm/s, pixel_dist={}mm, '
                'distance={:.1f}mm, angle={:.1f}°)').format(
                self.x, self.y, self.speed, self.pixel_distance, self.distance, self.angle)

class RD03D_Async:
    SINGLE_TARGET_CMD = bytes([0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x80, 0x00, 0x04, 0x03, 0x02, 0x01])
    MULTI_TARGET_CMD  = bytes([0xFD, 0xFC, 0xFB, 0xFA, 0x02, 0x00, 0x90, 0x00, 0x04, 0x03, 0x02, 0x01])
    
    BAUDRATE = 256000 

    def __init__(self, uart_port):
        self.uart_port = uart_port
        self.uart = None
        self.targets = []
        self.buffer = b''
        self.multi_mode = False # Speichert den Modus, in den der Sensor versetzt wurde
    
    async def connect(self, multi_mode=True):
        """Initialisiert die UART-Verbindung asynchron."""
        try:
            self.uart = aioserial.AioSerial(self.uart_port, self.BAUDRATE, timeout=0.1)
            logging.info(f"RD03D_Async: UART-Verbindung zu {self.uart_port} mit {self.BAUDRATE} Baud hergestellt.")
            await asyncio.sleep(0.2)
            await self.set_multi_mode_async(multi_mode)
            return True
        except aioserial.SerialException as e:
            logging.error(f"RD03D_Async: Fehler beim Verbinden mit UART {self.uart_port}: {e}")
            self.uart = None
            return False
        except Exception as e:
            logging.error(f"RD03D_Async: Unerwarteter Fehler bei UART-Verbindung: {e}")
            self.uart = None
            return False
    
    async def set_multi_mode_async(self, multi_mode=True):
        """Setzt den Radarmodus asynchron: True=Multi-target, False=Single-target."""
        if not self.uart:
            logging.warning("RD03D_Async: UART nicht verbunden. Kann Modus nicht setzen.")
            return

        cmd = self.MULTI_TARGET_CMD if multi_mode else self.SINGLE_TARGET_CMD
        try:
            await self.uart.write_async(cmd)
            await asyncio.sleep(0.2)
            self.uart.reset_input_buffer() 
            self.buffer = b''
            self.multi_mode = multi_mode # Speichert den tatsächlich gesetzten Modus
            logging.info(f"RD03D_Async: Radar-Modus auf {'Multi-Target' if multi_mode else 'Single-Target'} gesetzt.")
        except Exception as e:
            logging.error(f"RD03D_Async: Fehler beim Setzen des Radar-Modus: {e}")
    
    @staticmethod
    def parse_signed16(high, low):
        raw = (high << 8) + low
        sign = 1 if (raw & 0x8000) else -1
        value = raw & 0x7FFF
        return sign * value
    
    def _decode_frame(self, data):
        targets = []
        expected_len = 30 

        if len(data) < expected_len or data[0] != 0xAA or data[1] != 0xFF or data[-2] != 0x55 or data[-1] != 0xCC:
            logging.debug(f"RD03D_Async: _decode_frame: Invalid frame format or length {len(data)} (expected {expected_len}). Data: {data.hex()}")
            return targets
        
        num_targets_in_frame = 3 
        for i in range(num_targets_in_frame):
            base = 4 + i*8
            x = self.parse_signed16(data[base+1], data[base])
            y = self.parse_signed16(data[base+3], data[base+2])
            speed = self.parse_signed16(data[base+5], data[base+4])
            pixel_dist = data[base+6] + (data[base+7] << 8)
            targets.append(Target(x, y, speed, pixel_dist))
        
        return targets
    
    def _find_complete_frame(self, data):
        """Findet einen vollständigen Frame im Datenpuffer."""
        expected_frame_len = 30 

        start_idx = -1
        for i in range(len(data) - 1):
            if data[i] == 0xAA and data[i+1] == 0xFF:
                start_idx = i
                logging.debug(f"RD03D_Async: _find_complete_frame: Start-Marker gefunden bei Index {start_idx}.")
                break
        
        if start_idx == -1:
            logging.debug("RD03D_Async: _find_complete_frame: Kein Frame-Start gefunden.")
            return None, data  # Kein Frame-Start gefunden, alle Daten behalten
        
        if start_idx + expected_frame_len <= len(data):
            if data[start_idx + expected_frame_len - 2] == 0x55 and data[start_idx + expected_frame_len - 1] == 0xCC:
                frame = data[start_idx : start_idx + expected_frame_len]
                remaining = data[start_idx + expected_frame_len :]
                logging.debug(f"RD03D_Async: _find_complete_frame: Vollständiger Frame gefunden. Länge: {len(frame)}. Remaining: {len(remaining)} bytes.")
                return frame, remaining
        
        logging.debug(f"RD03D_Async: _find_complete_frame: Frame-Start bei {start_idx} gefunden, aber kein vollständiger Frame (erwartet {expected_frame_len} Bytes) oder kein Ende.")
        return None, data[start_idx:]
    
    async def update_async(self):
        """Aktualisiert die interne Zielliste mit den neuesten Daten vom Radar asynchron."""
        if not self.uart:
            logging.warning("RD03D_Async: UART nicht verbunden. Kann keine Daten aktualisieren.")
            return False

        try:
            bytes_to_read = self.uart.in_waiting 
            if bytes_to_read > 0:
                new_data = await self.uart.read_async(bytes_to_read)
                self.buffer += new_data
                logging.debug(f"RD03D_Async: update_async: {len(new_data)} neue Bytes gelesen. Puffergröße: {len(self.buffer)}. Neue Daten: {new_data.hex()}")
            else:
                logging.debug("RD03D_Async: update_async: Keine neuen Bytes verfügbar.")
        except Exception as e:
            logging.error(f"RD03D_Async: Fehler beim Lesen von UART-Daten: {e}")
            return False
        
        if len(self.buffer) > 300:
            logging.debug(f"RD03D_Async: update_async: Puffer zu groß ({len(self.buffer)} Bytes). Kürze auf 150 Bytes.")
            self.buffer = self.buffer[-150:]

        latest_frame = None
        temp_buffer = self.buffer
        
        logging.debug(f"RD03D_Async: update_async: Starte Frame-Parsing. Aktueller Puffer: {self.buffer.hex()}")

        while True:
            frame, temp_buffer = self._find_complete_frame(temp_buffer)
            if frame:
                latest_frame = frame
                logging.debug(f"RD03D_Async: update_async: Vollständigen Frame gefunden. Puffer nach diesem Frame: {temp_buffer.hex()}")
            else:
                logging.debug("RD03D_Async: update_async: Keine weiteren vollständigen Frames gefunden.")
                break
        
        if latest_frame:
            # Finde, wo der latest_frame im ursprünglichen Puffer beginnt
            frame_start_index = self.buffer.rfind(latest_frame)
            if frame_start_index != -1:
                self.buffer = self.buffer[frame_start_index + len(latest_frame):]
                logging.debug(f"RD03D_Async: update_async: Puffer nach Bereinigung (Start des letzten Frames): {self.buffer.hex()}")
            else:
                logging.warning("RD03D_Async: update_async: latest_frame nicht im Puffer gefunden, Puffer wird geleert.")
                self.buffer = b''
            
            decoded = self._decode_frame(latest_frame)
            if decoded:
                # KORREKTUR: Filtere leere Targets für das Debug-Log
                filtered_targets = [str(t) for t in decoded if t.distance > 0]
                if gs.TRACE_MODE:
                    logging.info(f"TRACE: Targets dekodiert: {filtered_targets}")
                logging.debug(f"RD03D_Async: update_async: Targets erfolgreich dekodiert: {filtered_targets}")
                
                # KORRIGIERTE ZEILE (wie besprochen): Speichere nur Targets, die keine Artefakte (distance=0) sind
                self.targets = [t for t in decoded if t.distance > 0]
                return True
        
        logging.debug("RD03D_Async: update_async: Kein gültiger Frame gefunden oder dekodiert.")
        return False
    
    def get_target(self, target_number=1):
        """Gibt ein Ziel nach Nummer zurück (1-basierter Index)."""
        if 1 <= target_number <= len(self.targets):
            return self.targets[target_number - 1]
        return None
    
    async def close(self):
        """Schließt die UART-Verbindung asynchron."""
        if self.uart and self.uart.is_open:
            try:
                self.uart.close()
                logging.info("RD03D_Async: UART-Verbindung geschlossen.")
            except Exception as e:
                logging.error(f"RD03D_Async: Fehler beim Schließen der UART-Verbindung: {e}")