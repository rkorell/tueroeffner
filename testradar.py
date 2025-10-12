import serial
import time
import logging

# --- Konfiguration ---
SERIAL_PORT = "/dev/ttyAMA2"
BAUDRATE = 115200

# --- Debug Mode Command ---
# Dies ist der Hex-Befehl aus dem Waveshare Wiki, um den Sensor in den "Debug Mode" zu schalten.
DEBUG_MODE_COMMAND = b'\xFD\xFC\xFB\xFA\x08\x00\x12\x00\x00\x00\x00\x00\x00\x00\x04\x03\x02\x01'

# --- Definition des Debug Mode Daten-Frames ---
# Basierend auf der Beschreibung im Waveshare Wiki:
# Header (AA BF 10 14)
# Intra-frame Data (RDMAP: 20(Dopple)*16（number of range gate）*4（square of the amplitude） = 1280 Bytes)
# Tailer (FD FC FB FA)

DEBUG_FRAME_HEADER = b'\xAA\xBF\x10\x14'
DEBUG_FRAME_TAIL = b'\xFD\xFC\xFB\xFA'

# Die Länge der Intra-frame Data (Payload)
DEBUG_PAYLOAD_LEN = 1280 
# Die Gesamtlänge eines vollständigen Debug Mode Frames
# Header (4) + Payload (1280) + Tail (4) = 1288 Bytes
DEBUG_TOTAL_FRAME_LEN = len(DEBUG_FRAME_HEADER) + DEBUG_PAYLOAD_LEN + len(DEBUG_FRAME_TAIL)

# --- Logging-Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_command(ser_port, command_bytes):
    """Sendet einen Byte-Befehl an den seriellen Port."""
    logging.info(f"Sende Befehl ({len(command_bytes)} Bytes): {command_bytes.hex().upper()}")
    ser_port.write(command_bytes)
    # Eine kurze Pause, damit der Sensor den Befehl verarbeiten kann
    time.sleep(0.1) 

def radar_debug_mode_monitor():
    """
    Schaltet den Radarsensor in den Debug Mode und überwacht kontinuierlich dessen Ausgabe.
    """
    logging.info(f"Starte Radarsensor-Monitor im Debug Mode auf {SERIAL_PORT}...")
    ser = None
    try:
        # Erhöhe den Timeout, da die Frames sehr groß sind und das Lesen länger dauern kann
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1) 
        logging.info(f"Serieller Port {SERIAL_PORT} erfolgreich geöffnet.")
        
        ser.flushInput() # Leere den Input-Puffer
        send_command(ser, DEBUG_MODE_COMMAND)
        logging.info("Befehl für Debug Mode gesendet. Überwache Daten...")

        buffer = b''
        
        while True: # Endlosschleife für kontinuierliche Überwachung
            if ser.in_waiting > 0:
                buffer += ser.read(ser.in_waiting)
            
            # Suche nach dem Header im Puffer
            header_index = buffer.find(DEBUG_FRAME_HEADER)
            
            if header_index != -1: # Header gefunden
                # Verwerfe alles vor dem Header
                if header_index > 0:
                    logging.debug(f"Verwerfe {header_index} Bytes vor Header: {buffer[:header_index].hex().upper()}")
                    buffer = buffer[header_index:]
                    header_index = 0 # Header ist jetzt am Anfang des Puffers
                
                # Prüfe, ob genug Bytes für einen vollständigen Frame im Puffer sind
                if len(buffer) >= DEBUG_TOTAL_FRAME_LEN:
                    full_frame = buffer[:DEBUG_TOTAL_FRAME_LEN]
                    
                    # Prüfe, ob der extrahierte Frame mit dem erwarteten Tail endet
                    if full_frame.endswith(DEBUG_FRAME_TAIL):
                        logging.info(f"Vollständiger Debug Mode Frame empfangen ({len(full_frame)} Bytes): {full_frame.hex().upper()}")
                        
                        # Hier würden die 1280 Bytes RDMAP-Daten liegen:
                        # rdmap_data = full_frame[len(DEBUG_FRAME_HEADER) : -len(DEBUG_FRAME_TAIL)]
                        # logging.info(f"  RDMAP-Daten ({len(rdmap_data)} Bytes): {rdmap_data.hex().upper()}")
                        # Wir geben sie hier nicht extra aus, da sie im full_frame bereits enthalten sind.
                        
                        # Entferne den verarbeiteten Frame aus dem Puffer
                        buffer = buffer[DEBUG_TOTAL_FRAME_LEN:] 
                    else:
                        logging.warning(f"Debug Mode Frame-Tail ungültig. Verwerfe {len(full_frame)} Bytes: {full_frame.hex().upper()}")
                        # Wenn der Tail falsch ist, könnte der Header falsch erkannt worden sein oder Datenfehler vorliegen.
                        # Wir verwerfen ihn und suchen weiter nach dem nächsten Header.
                        buffer = buffer[DEBUG_TOTAL_FRAME_LEN:] 
                else:
                    # Nicht genug Daten für einen vollständigen Frame, warte auf mehr Daten
                    pass # Bleibe in der Schleife und warte auf weitere Bytes
            else:
                # Kein Header gefunden, verwerfe ein Byte, um weiter zu suchen
                if len(buffer) > 0:
                    logging.debug(f"Kein Header gefunden, verwerfe 1 Byte: {buffer[0].hex().upper()}")
                    buffer = buffer[1:]
            
            time.sleep(0.01) # Kurze Pause, um CPU nicht zu belasten

    except serial.SerialException as e:
        logging.error(f"Fehler beim Öffnen oder Lesen des seriellen Ports {SERIAL_PORT}: {e}")
        logging.error("Mögliche Ursachen: Port falsch oder nicht verfügbar, Baudrate falsch, Kabel lose, Sensor nicht mit Strom versorgt.")
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
    radar_debug_mode_monitor()