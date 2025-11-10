# Program: ld2450_async.py
# Purpose: Asynchrone Python-Klasse zur Kommunikation mit dem HLK-LD2450 mmWave Radar Sensor über UART.
#          Basiert auf der Architektur von rd03d_async.py (verwendet aioserial).
# Author: Dr. Ralf Korell / CircuIT (basierend auf LD2450 Doku und rd03d_async.py)
# Creation Date: November 08, 2025
# Modified: November 08, 2025, 15:21 UTC - Erstellung des Moduls, Implementierung des Protokolls (Frame-Parsing, Sign-Magnitude-Dekodierung) und Single-Target-Konfigurationssequenz.

import aioserial
import asyncio
import math
import logging
import time

# NEU: Benannter Logger
log = logging.getLogger(__name__)

class Target:
    """
    Klassendefinition für ein Target, identisch zur rd03d_async.py Implementierung,
    um Kompatibilität mit radar_logic.py zu gewährleisten.
    """
    def __init__(self, x, y, speed, pixel_distance):
        self.x = x                  # mm
        self.y = y                  # mm
        self.speed = speed          # cm/s
        self.pixel_distance = pixel_distance  # mm (in LD2450 Doku: "Distance resolution")
        self.distance = math.sqrt(x**2 + y**2) # Berechnete Gesamtentfernung
        self.angle = math.degrees(math.atan2(x, y)) # Berechneter Winkel
    
    def __str__(self):
        return ('Target(x={}mm, y={}mm, speed={}cm/s, pixel_dist={}mm, '
                'distance={:.1f}mm, angle={:.1f}°)').format(
                self.x, self.y, self.speed, self.pixel_distance, self.distance, self.angle)

class LD2450_Async:
    # --- Protokollkonstanten (basierend auf Doku und serial_protocol.py) ---
    
    # Baudrate (Hardcoded, wie beim RD-03D)
    BAUDRATE = 256000 
    
    # 1. Daten-Report-Frames (vom Sensor zum Host)
    REPORT_HEADER = b'\xAA\xFF\x03\x00'
    REPORT_TAIL = b'\x55\xCC'
    REPORT_FRAME_LEN = 30 # Inkl. Header und Tail
    
    # 2. Konfigurations-Frames (vom Host zum Sensor)
    COMMAND_HEADER = b'\xFD\xFC\xFB\xFA'
    COMMAND_TAIL = b'\x04\x03\x02\x01'

    # --- Befehle (Host -> Sensor) ---
    # 2.2.1 Enable configuration
    CMD_ENABLE_CONFIG_VAL = b'\x01\x00'
    CMD_ENABLE_CONFIG = (
        COMMAND_HEADER + 
        b'\x04\x00' +       # Länge (2 bytes) + Wert (2 bytes) = 4 bytes
        b'\xFF\x00' +       # Command word 0x00FF
        CMD_ENABLE_CONFIG_VAL + 
        COMMAND_TAIL
    )
    
    # 2.2.3 Single target tracking
    CMD_SINGLE_TARGET_VAL = b''
    CMD_SINGLE_TARGET = (
        COMMAND_HEADER + 
        b'\x02\x00' +       # Länge (2 bytes) + Wert (0 bytes) = 2 bytes
        b'\x80\x00' +       # Command word 0x0080
        CMD_SINGLE_TARGET_VAL + 
        COMMAND_TAIL
    )

    # 2.2.2 End configuration
    CMD_END_CONFIG_VAL = b''
    CMD_END_CONFIG = (
        COMMAND_HEADER + 
        b'\x02\x00' +       # Länge (2 bytes) + Wert (0 bytes) = 2 bytes
        b'\xFE\x00' +       # Command word 0x00FE
        CMD_END_CONFIG_VAL + 
        COMMAND_TAIL
    )

    # --- ACKs (Sensor -> Host) ---
    # Erwartete erfolgreiche ACK-Antworten
    ACK_ENABLE_CONFIG = (
        COMMAND_HEADER + 
        b'\x08\x00' +       # Länge 8 bytes
        b'\xFF\x01' +       # ACK (0x01FF)
        b'\x00\x00'         # Status 0 = Erfolg
        # + 4 bytes (Protokollversion, Buffer size) - wir prüfen nur bis Status
    )
    
    ACK_SINGLE_TARGET = (
        COMMAND_HEADER + 
        b'\x04\x00' +       # Länge 4 bytes
        b'\x80\x01' +       # ACK (0x0180)
        b'\x00\x00'         # Status 0 = Erfolg
        # + COMMAND_TAIL
    )
    
    ACK_END_CONFIG = (
        COMMAND_HEADER + 
        b'\x04\x00' +       # Länge 4 bytes
        b'\xFE\x01' +       # ACK (0x01FE)
        b'\x00\x00'         # Status 0 = Erfolg
        # + COMMAND_TAIL
    )


    def __init__(self, uart_port):
        self.uart_port = uart_port
        self.uart = None
        self.targets = []
        self.buffer = b''
    
    async def _send_command(self, cmd_name: str, cmd_bytes: bytes, expected_ack_prefix: bytes):
        """
        Sendet einen Konfigurationsbefehl und wartet auf ein spezifisches, erfolgreiches ACK.
        """
        if not self.uart:
            return False
            
        try:
            log.debug(f"Sende Befehl: {cmd_name} ({cmd_bytes.hex()})")
            await self.uart.write_async(cmd_bytes)
            
            # Warte auf ACK
            ack_buffer = b''
            start_time = time.monotonic()
            while (time.monotonic() - start_time) < 1.0: # 1 Sekunde Timeout pro ACK
                bytes_to_read = self.uart.in_waiting
                if bytes_to_read > 0:
                    ack_buffer += await self.uart.read_async(bytes_to_read)
                    
                    # Suche nach dem vollständigen ACK-Prefix
                    if expected_ack_prefix in ack_buffer:
                        log.info(f"ACK für '{cmd_name}' erfolgreich empfangen.")
                        
                        # Bereinige Puffer (alles bis und mit dem ACK entfernen)
                        idx = ack_buffer.find(expected_ack_prefix)
                        # Finde das Ende dieses Frames (bis zum COMMAND_TAIL)
                        tail_idx = ack_buffer.find(self.COMMAND_TAIL, idx)
                        if tail_idx != -1:
                            self.buffer = ack_buffer[tail_idx + len(self.COMMAND_TAIL):]
                        else:
                            # Fallback: Puffer leeren (sollte nicht passieren)
                            self.buffer = b''
                            
                        return True
                        
                await asyncio.sleep(0.01)

            log.error(f"Timeout beim Warten auf ACK für '{cmd_name}'. Erwartet: {expected_ack_prefix.hex()}, Empfangen: {ack_buffer.hex()}")
            return False
            
        except Exception as e:
            log.error(f"Fehler beim Senden/Empfangen von Befehl '{cmd_name}': {e}")
            return False

    async def _configure_sensor(self):
        """Führt die 3-stufige Konfigurationssequenz aus."""
        # 1. Enable Config
        if not await self._send_command("Enable Config", self.CMD_ENABLE_CONFIG, self.ACK_ENABLE_CONFIG):
            return False
        await asyncio.sleep(0.05) # Kurze Pause zwischen Befehlen

        # 2. Set Single Target Mode
        if not await self._send_command("Set Single Target", self.CMD_SINGLE_TARGET, self.ACK_SINGLE_TARGET):
            return False
        await asyncio.sleep(0.05)

        # 3. End Config
        if not await self._send_command("End Config", self.CMD_END_CONFIG, self.ACK_END_CONFIG):
            return False
        
        log.info("LD2450 erfolgreich in Single-Target-Modus konfiguriert.")
        return True

    async def connect(self, multi_mode=None): # multi_mode wird ignoriert, da wir Single-Target erzwingen
        """Initialisiert die UART-Verbindung asynchron."""
        try:
            self.uart = aioserial.AioSerial(self.uart_port, self.BAUDRATE, timeout=0.1)
            log.info(f"UART-Verbindung zu {self.uart_port} mit {self.BAUDRATE} Baud (LD2450) hergestellt.")
            await asyncio.sleep(0.1)
            
            # Führe die Konfigurationssequenz aus (Enable -> Single Target -> End)
            if not await self._configure_sensor():
                raise RuntimeError("LD2450 Konfigurationssequenz fehlgeschlagen.")

            # Puffer nach der Konfiguration final leeren
            self.uart.reset_input_buffer() 
            self.buffer = b''
            log.info("LD2450 Puffer bereinigt, bereit für Daten-Streaming.")
            return True
            
        except aioserial.SerialException as e:
            log.error(f"Fehler beim Verbinden mit UART {self.uart_port}: {e}")
            self.uart = None
            return False
        except Exception as e:
            log.error(f"Unerwarteter Fehler bei UART-Verbindung oder Konfiguration: {e}")
            if self.uart:
                self.uart.close()
            self.uart = None
            return False
    
    def _parse_sign_magnitude(self, raw_bytes: bytes) -> int:
        """
        Dekodiert einen 2-Byte-Wert (Little-Endian) gemäß der 
        Sign-Magnitude-Logik des LD2450 (Bit 15 = Vorzeichen).
        (Basierend auf der Diskussion und Analyse der PDF)
        """
        raw = int.from_bytes(raw_bytes, byteorder='little')
        
        if raw & 0x8000:  # Bit 15 ist 1 -> positiv
            # Wert = Rohwert - 0x8000 (oder Bit 15 löschen)
            return (raw & 0x7FFF)
        else:            # Bit 15 ist 0 -> negativ
            # Wert = -(Rohwert) (oder -(Rohwert & 0x7FFF))
            return -(raw & 0x7FFF)

    def _decode_frame(self, data: bytes) -> list:
        """
        Dekodiert einen einzelnen 30-Byte-Datenframe (REPORT_FRAME_LEN).
        Gibt eine Liste mit einem Target-Objekt zurück (da im Single-Target-Modus).
        """
        targets = []
        
        # Wir parsen nur Target 1 (Bytes 4-11), da wir im Single-Target-Modus sind.
        # (Target 2: 12-19, Target 3: 20-27)
        
        # Byte 4, 5: X Koordinate (Low, High)
        x = self._parse_sign_magnitude(data[4:6])
        
        # Byte 6, 7: Y Koordinate (Low, High)
        y = self._parse_sign_magnitude(data[6:8])
        
        # Byte 8, 9: Speed (Low, High)
        speed = self._parse_sign_magnitude(data[8:10])
        
        # Byte 10, 11: Distance Resolution (Low, High) - uint16
        dist_res = int.from_bytes(data[10:12], byteorder='little')

        # Erstelle Target (nur wenn Y-Wert plausibel ist,
        # RD-03D Filter war distance > 0, Y=0 ist hier ein gültiger Wert (Kreuzen der Achse))
        if x != 0 or y != 0 or speed != 0:
            targets.append(Target(x, y, speed, dist_res))
            
        return targets
    
    def _find_complete_frame(self, data: bytes) -> (bytes, bytes):
        """
        Findet einen vollständigen 30-Byte-Datenframe im Puffer.
        (Adaptiert von rd03d_async.py)
        """
        start_idx = -1
        
        # Suche nach dem 4-Byte-Header
        # (Wir suchen nur nach den ersten 2, da 0x03 0x00 Teil der Payload sein könnten,
        # obwohl AA FF selten ist)
        for i in range(len(data) - (self.REPORT_FRAME_LEN - 1)):
            if data[i:i+4] == self.REPORT_HEADER:
                start_idx = i
                log.trace(f"_find_complete_frame: Start-Header gefunden bei Index {start_idx}.")
                break
        
        if start_idx == -1:
            log.trace("_find_complete_frame: Kein Frame-Start gefunden.")
            # Puffer intakt lassen, wenn kein Header gefunden wurde (vielleicht unvollständig)
            return None, data
        
        # Prüfe, ob der Frame (30 Bytes) vollständig im Puffer vorhanden ist
        if start_idx + self.REPORT_FRAME_LEN <= len(data):
            # Prüfe den Tail (letzte 2 Bytes des Frames)
            frame_end_idx = start_idx + self.REPORT_FRAME_LEN
            if data[frame_end_idx - 2 : frame_end_idx] == self.REPORT_TAIL:
                frame = data[start_idx : frame_end_idx]
                remaining = data[frame_end_idx :]
                log.trace(f"_find_complete_frame: Vollständiger Frame gefunden. Länge: {len(frame)}. Remaining: {len(remaining)} bytes.")
                return frame, remaining
            else:
                log.trace(f"_find_complete_frame: Header bei {start_idx} gefunden, aber Tail FALSCH. Verwerfe Daten bis nach Header.")
                # Daten korrupt, verwerfe alles bis NACH diesem falschen Header
                return None, data[start_idx + 4:]
        
        log.trace(f"_find_complete_frame: Frame-Start bei {start_idx} gefunden, aber (noch) unvollständig.")
        # Frame-Start gefunden, aber noch nicht vollständig. Behalte Puffer ab Start.
        return None, data[start_idx:]
    
    async def update_async(self) -> bool:
        """
        Aktualisiert die interne Zielliste mit den neuesten Daten vom Radar asynchron.
        (Logik identisch zu rd03d_async.py, nur _find/_decode sind anders)
        """
        if not self.uart:
            log.warning("UART nicht verbunden. Kann keine Daten aktualisieren.")
            return False

        try:
            bytes_to_read = self.uart.in_waiting 
            if bytes_to_read > 0:
                new_data = await self.uart.read_async(bytes_to_read)
                self.buffer += new_data
                log.trace(f"update_async: {len(new_data)} neue Bytes gelesen. Puffergröße: {len(self.buffer)}.")
            else:
                log.trace("update_async: Keine neuen Bytes verfügbar.")
        except Exception as e:
            log.error(f"Fehler beim Lesen von UART-Daten: {e}")
            return False
        
        # Puffer-Management (identisch zu rd03d_async)
        if len(self.buffer) > 300:
            log.trace(f"update_async: Puffer zu groß ({len(self.buffer)} Bytes). Kürze auf 150 Bytes.")
            self.buffer = self.buffer[-150:]

        latest_frame = None
        temp_buffer = self.buffer
        
        log.trace(f"update_async: Starte Frame-Parsing. Aktueller Puffer: {self.buffer.hex()}")

        while True:
            frame, temp_buffer = self._find_complete_frame(temp_buffer)
            if frame:
                latest_frame = frame
                log.trace(f"update_async: Vollständigen Frame gefunden. Puffer nach diesem Frame: {temp_buffer.hex()}")
            else:
                # Puffer ist jetzt entweder leer oder enthält einen unvollständigen Frame
                self.buffer = temp_buffer
                log.trace(f"update_async: Keine weiteren Frames. Restpuffer: {self.buffer.hex()}")
                break
        
        if latest_frame:
            # Wir haben den letzten vollständigen Frame gefunden.
            # Der Puffer (self.buffer) wurde bereits von _find_complete_frame 
            # auf den Rest *nach* dem letzten vollständigen Frame gesetzt.
            
            decoded = self._decode_frame(latest_frame)
            if decoded:
                filtered_targets = [str(t) for t in decoded]
                log.trace(f"Targets erfolgreich dekodiert: {filtered_targets}")
                
                # Speichere die dekodierten Targets
                self.targets = decoded
                return True
            else:
                # Frame gefunden, aber Dekodierung ergab kein Target (z.B. 0,0,0)
                self.targets = [] # Wichtig: Alte Targets löschen
                return True # Frame wurde empfangen, auch wenn er leer war
        
        log.trace("update_async: Kein gültiger Frame gefunden oder dekodiert.")
        return False # Es wurden keine neuen, vollständigen Frames gefunden
    
    def get_target(self, target_number=1) -> Target | None:
        """Gibt ein Ziel nach Nummer zurück (1-basierter Index)."""
        # Da wir im Single-Target-Modus sind, gibt es nur Target 1 (Index 0)
        if target_number == 1 and len(self.targets) > 0:
            return self.targets[0]
        return None
    
    async def close(self):
        """Schließt die UART-Verbindung asynchron."""
        if self.uart and self.uart.is_open:
            try:
                self.uart.close()
                log.info("UART-Verbindung (LD2450) geschlossen.")
            except Exception as e:
                log.error(f"Fehler beim Schließen der UART-Verbindung (LD2450): {e}")