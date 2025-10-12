import serial
import time
import logging
import struct # Für die Umwandlung von Bytes in Zahlen

# --- Konfiguration ---
SERIAL_PORT = "/dev/ttyAMA2"
BAUDRATE = 115200

# --- Report Mode Command ---
REPORT_MODE_COMMAND = b'\xFD\xFC\xFB\xFA\x08\x00\x12\x00\x00\x00\x04\x00\x00\x00\x04\x03\x02\x01'

# --- Definition des Report Mode Daten-Frames ---
REPORT_FRAME_HEADER = b'\xF4\xF3\xF2\xF1'
REPORT_FRAME_TAIL = b'\xF8\xF7\xF6\xF5'

# Die Länge des Payloads (ohne Header, Length-Feld und Tail)
# Detection Result (1 Byte) + Target Distance (2 Bytes) + Energy Values (32 Bytes) = 35 Bytes
REPORT_PAYLOAD_LEN_EXPECTED = 1 + 2 + 32 

# --- Logging-Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_command(ser_port, command_bytes):
    """Sendet einen Byte-Befehl an den seriellen Port."""
    logging.info(f"Sende Befehl ({len(command_bytes)} Bytes): {command_bytes.hex().upper()}")
    ser_port.write(command_bytes)
    time.sleep(0.1) # Kurze Pause, damit der Sensor den Befehl verarbeiten kann

def parse_report_frame(frame_data: bytes):
    """
    Parst einen vollständigen Report Mode Frame und extrahiert bekannte Informationen.
    Erwartet einen Frame ohne Header und Tail, aber inklusive Length-Feld.
    """
    # Überprüfe die Mindestlänge des Frames
    if len(frame_data) < 2 + REPORT_PAYLOAD_LEN_EXPECTED: # Length-Feld (2) + Payload (35)
        logging.warning(f"Frame zu kurz zum Parsen. Länge: {len(frame_data)} Bytes.")
        return None

    # Length-Feld ist Byte 0 und 1 (Little-Endian)
    # struct.unpack('<H', ...) interpretiert 2 Bytes als unsigned short (little-endian)
    actual_payload_len = struct.unpack('<H', frame_data[0:2])[0]
    
    # Der im Wiki angegebene Payload ist 35 Bytes.
    # Das Length-Feld sollte die Länge des Payloads (ohne sich selbst, Header und Tail) angeben.
    # Es ist wichtig, hier zu prüfen, ob die tatsächliche Payload-Länge mit der Erwartung übereinstimmt.
    if actual_payload_len != REPORT_PAYLOAD_LEN_EXPECTED:
        logging.warning(f"Unerwartete Payload-Länge im Frame. Erwartet: {REPORT_PAYLOAD_LEN_EXPECTED}, Tatsächlich: {actual_payload_len}. Frame: {frame_data.hex().upper()}")
        # Wir versuchen trotzdem weiter zu parsen, aber das ist ein Warnsignal.
        # Es könnte bedeuten, dass sich das Protokoll leicht unterscheidet oder wir einen Fehler haben.
        
    # Payload beginnt nach dem 2-Byte-Length-Feld
    payload_start_index = 2
    
    # Detection Result (1 Byte)
    detection_result = frame_data[payload_start_index] # 0x00 absent, 0x01 present
    
    # Target Distance (2 Bytes, Little-Endian)
    target_distance_bytes = frame_data[payload_start_index + 1 : payload_start_index + 3]
    target_distance = struct.unpack('<H', target_distance_bytes)[0] # Unsigned short
    
    # Energy values for each distance gate (32 Bytes)
    energy_values = frame_data[payload_start_index + 3 : payload_start_index + 3 + 32]

    # Rückgabe der geparsten Daten
    return {
        "detection_result": "Present" if detection_result == 0x01 else "Absent",
        "target_distance": target_distance, # Dies ist ein Rohwert, Einheit noch unbekannt (mm, cm, etc.?)
        "energy_values": energy_values.hex().upper() # Hex-Darstellung der Energiewerte
    }


def radar_report_mode_monitor():
    """
    Schaltet den Radarsensor in den Report Mode und überwacht kontinuierlich dessen Ausgabe.
    """
    logging.info(f"Starte Radarsensor-Monitor im Report Mode auf {SERIAL_PORT}...")
    ser = None
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0.01) # Sehr kurzer Timeout für nicht-blockierendes Lesen
        logging.info(f"Serieller Port {SERIAL_PORT} erfolgreich geöffnet.")
        
        ser.flushInput() # Leere den Input-Puffer
        send_command(ser, REPORT_MODE_COMMAND)
        logging.info("Befehl für Report Mode gesendet. Überwache Daten...")

        buffer = b''
        
        while True: # Endlosschleife für kontinuierliche Überwachung
            if ser.in_waiting > 0:
                buffer += ser.read(ser.in_waiting)
            
            # Suche nach dem Header im Puffer
            header_index = buffer.find(REPORT_FRAME_HEADER)
            
            if header_index != -1: # Header gefunden
                # Verwerfe alles vor dem Header
                if header_index > 0:
                    logging.debug(f"Verwerfe {header_index} Bytes vor Header: {buffer[:header_index].hex().upper()}")
                    buffer = buffer[header_index:]
                    header_index = 0 # Header ist jetzt am Anfang des Puffers
                
                # Wenn der Puffer lang genug ist, um das Length-Feld zu lesen
                if len(buffer) >= len(REPORT_FRAME_HEADER) + 2:
                    # Lese die erwartete Payload-Länge aus dem Frame (nach Header, 2 Bytes)
                    # Dies ist die Länge der Daten zwischen dem Length-Feld und dem Tail.
                    # Das Length-Feld selbst ist 2 Bytes.
                    # Der Header ist 4 Bytes.
                    
                    # Die tatsächliche Payload-Länge (ohne Header, Length-Feld und Tail)
                    # wird an Byte 4 und 5 (Little-Endian) des Frames angegeben.
                    # Also buffer[4:6]
                    try:
                        # Das Length-Feld ist das 5. und 6. Byte im Frame (Index 4 und 5)
                        # Example frame: FD FC FB FA [0C 00] 00 01 ...
                        # Hier: F4 F3 F2 F1 [LL LL] ...
                        actual_payload_len_from_frame = struct.unpack('<H', buffer[len(REPORT_FRAME_HEADER):len(REPORT_FRAME_HEADER)+2])[0]
                        
                        # Die Gesamtlänge des Frames, basierend auf dem gelesenen Payload-Längenfeld
                        # Header (4) + Length-Feld (2) + actual_payload_len_from_frame + Tail (4)
                        total_frame_len_dynamic = len(REPORT_FRAME_HEADER) + 2 + actual_payload_len_from_frame + len(REPORT_FRAME_TAIL)

                        # Prüfe, ob genug Daten für den gesamten Frame vorhanden sind
                        if len(buffer) >= total_frame_len_dynamic:
                            full_frame = buffer[:total_frame_len_dynamic]
                            
                            # Prüfe den Tail
                            if full_frame.endswith(REPORT_FRAME_TAIL):
                                logging.info(f"Vollständiger Report Mode Frame empfangen ({len(full_frame)} Bytes): {full_frame.hex().upper()}")
                                
                                # Extrahiere den Teil des Frames, der geparst werden soll:
                                # Start nach Header (4 Bytes) und Length-Feld (2 Bytes)
                                parsable_data = full_frame[len(REPORT_FRAME_HEADER): total_frame_len_dynamic - len(REPORT_FRAME_TAIL)]
                                
                                parsed_info = parse_report_frame(parsable_data)
                                if parsed_info:
                                    logging.info(f"  Geparsed: Detektion: {parsed_info['detection_result']}, Distanz: {parsed_info['target_distance']} (Einheit?), Energiewerte: {parsed_info['energy_values']}")
                                else:
                                    logging.warning("  Fehler beim Parsen des Frames.")
                                
                                # Entferne den verarbeiteten Frame aus dem Puffer
                                buffer = buffer[total_frame_len_dynamic:]
                            else:
                                logging.warning(f"Frame-Tail ungültig. Verwerfe {len(full_frame)} Bytes: {full_frame.hex().upper()}")
                                # Wenn der Tail falsch ist, ist der gesamte Frame wahrscheinlich korrupt.
                                # Wir verwerfen ihn und suchen weiter nach dem nächsten Header.
                                buffer = buffer[total_frame_len_dynamic:] # Oder buffer = buffer[1:] um Byte für Byte zu verschieben
                        else:
                            # Nicht genug Daten für den vollständigen Frame, warte auf mehr
                            pass # Bleibe in der Schleife und warte auf weitere Bytes
                    except struct.error:
                        logging.error(f"Fehler beim Entpacken der Payload-Länge. Puffer: {buffer.hex().upper()}")
                        buffer = buffer[1:] # Verschiebe um ein Byte, um aus dem Fehlerzustand zu kommen
                else:
                    # Nicht genug Daten, um das Length-Feld zu lesen, warte auf mehr
                    pass # Bleibe in der Schleife und warte auf weitere Bytes
            else:
                # Kein Header gefunden, verwerfe ein Byte, um weiter zu suchen
                if len(buffer) > 0:
                    logging.debug(f"Kein Header gefunden, verwerfe 1 Byte: {buffer[0].hex().upper()}")
                    buffer = buffer[1:]
            
            time.sleep(0.01) # Kurze Pause, um CPU nicht zu belasten

    except serial.SerialException as e:
        logging.error(f"Fehler beim Öffnen oder Lesen des seriellen Ports {SERIAL_PORT}: {e}")
        logging.error("Mögliche Ursachen: Port falsch, Baudrate falsch, Kabel lose, Sensor nicht mit Strom versorgt.")
    except KeyboardInterrupt:
        logging.info("Monitor durch Benutzer beendet.")
    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
    finally:
        if ser and ser.is_open:
            ser.close()
            logging.info(f"Serieller Port {SERIAL_PORT} geschlossen.")

# --- Hauptausführung ---
if __name__ == "__main__":
    radar_report_mode_monitor()