# Program: BLE_Sniffer_Console.py
# Purpose: GUI-less console tool to sniff and display raw BLE advertising data from iBeacons.
#          Designed for detailed analysis of beacon payloads.
# Author: Your Name / CircuIT
# Creation Date: August 16, 2025
# Modified: August 16, 2025 - Initial implementation as a dedicated console-based BLE sniffer.
# Corrected: August 17, 2025, 14:15 UTC - Fixed TypeError in service_data hex conversion.
#            Removed non-existent 'advertisement_data.data' attribute.
#            Set raw advertisement logging to DEBUG level to prevent log flooding.
# Corrected: August 17, 2025, 14:20 UTC - Re-fixed TypeError for service_data keys (they are strings, not ints).

import asyncio
import time
import os
import logging
import struct

# BLE Imports
from bleak import BleakScanner

# --- Logging Konfiguration ---
# Alle Log-Meldungen gehen auf die Konsole und optional in eine Datei.
LOG_FILE_PATH = "ble_sniffer_log.txt" # Optional: Pfad zur Log-Datei

logging.basicConfig(
    level=logging.DEBUG, # Default to INFO. Change to logging.DEBUG for raw advertisement data.
    format='%(asctime)s - BLE - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(), # Ausgabe auf die Konsole
        logging.FileHandler(LOG_FILE_PATH) # Ausgabe in eine Datei
    ]
)

# --- Globale Variablen für den BLE Scan ---
beacon_last_seen_data = {} # Stores for each Beacon: {'timestamp': time.time(), 'mac': mac_addr, 'major': major_val, 'minor': minor_val, 'rssi': rssi_val, 'distance': distance}
ble_scan_active = True # Flag to control the BLE scan asyncio task (will be set to False on shutdown)

# --- KONFIGURATION (kopiert und angepasst aus tueroeffner.py) ---
# Diese Werte dienen der Filterung und grundlegenden Distanzschätzung.

# BLE iBeacon Konfiguration
TARGET_IBEACON_UUID = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0" # UUID ist für alle Minew Beacons identisch
CALIBRATED_MEASURED_POWER_DEFAULT = -77 # Kalibrierter Measured Power (Tx Power @ 1m vom Beacon)
PATH_LOSS_EXPONENT_DEFAULT = 2.5 # Pfadverlust-Exponent (N): Typischerweise 2.0 für freie Sicht, 2.5-4.0 für Innenräume.

# Debouncing Konfiguration (für interne Bereinigung der Beacon-Liste)
ABSENCE_DETECTION_TIME = 10 # Sekunden: Zeit, die der Beacon nicht erkannt werden darf, um als "nicht anwesend" zu gelten

# Konfigurationsdatei für erlaubte Nutzer und deren Beacons (für allowed_majors)
ALLOWED_USERS_CONFIG = "Erlaubte_Nutzer.conf"
BLE_SCAN_INTERVAL_SEC = 1.0 # Sekunden Intervall für den BLE-Scan

# --- Hilfsfunktionen (kopiert aus tueroeffner.py) ---

def cleanup_gpio():
    """Räumt die GPIO-Einstellungen auf."""
    try:
        import RPi.GPIO as GPIO
        if GPIO.getmode() is not None:
            GPIO.cleanup()
            logging.info("GPIO aufgeräumt.")
    except ImportError:
        logging.warning("RPi.GPIO nicht importierbar, überspringe GPIO-Cleanup.")

def bytes_to_uuid(b):
    return f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}".upper()

def estimate_distance(rssi, measured_power, n):
    if rssi == 0:
        return -1.0
    return 10 ** ((measured_power - rssi) / (10 * n))

def read_allowed_users_config():
    """
    Liest die Konfigurationsdatei für erlaubte Nutzer und ihre Beacon-Majors ein.
    Format: Name;wahr/falsch;Major1;Major2;Major3
    """
    allowed_users = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, ALLOWED_USERS_CONFIG)

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'): # Kommentare und leere Zeilen ignorieren
                        continue
                    
                    parts = line.split(';')
                    if len(parts) < 2:
                        logging.warning(f"Ungültige Zeile in '{ALLOWED_USERS_CONFIG}': '{line}'. Erwarte mindestens Name;Status.")
                        continue
                    
                    name = parts[0].strip()
                    status_str = parts[1].strip().lower()
                    allowed = (status_str == 'wahr')
                    
                    beacon_majors = []
                    # Lese Major-Werte ab dem dritten Feld
                    for i in range(2, len(parts)):
                        major_str = parts[i].strip()
                        if major_str:
                            try:
                                beacon_majors.append(int(major_str))
                            except ValueError:
                                logging.warning(f"Ungültiger Major-Wert '{major_str}' für Nutzer '{name}' in '{ALLOWED_USERS_CONFIG}'. Ignoriere.")
                    
                    allowed_users[name] = {
                        'allowed': allowed,
                        'beacon_majors': beacon_majors
                    }
        except Exception as e:
            logging.error(f"Fehler beim Lesen von '{ALLOWED_USERS_CONFIG}': {e}")
    return allowed_users

# --- Haupt-Asynchrone Funktion ---
async def main():
    global ble_scan_active

    allowed_users_data = read_allowed_users_config()
    allowed_majors = set()
    for user_data in allowed_users_data.values():
        if user_data['allowed']:
            allowed_majors.update(user_data['beacon_majors'])
    logging.info(f"Erlaubte Major-Werte für BLE-Filterung: {allowed_majors}")

    logging.info("BLE Sniffer gestartet. Drücken Sie Strg+C zum Beenden.")

    def detection_callback(device, advertisement_data):
        rssi_val = advertisement_data.rssi
        
        # Log basic iBeacon info if available and matches our criteria
        is_ibeacon = False
        if 0x004C in advertisement_data.manufacturer_data:
            mfg_data = advertisement_data.manufacturer_data[0x004C]
            if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
                try:
                    uuid_bytes, major_val, minor_val, measured_power = struct.unpack_from(">16sHHb", mfg_data, 2)
                    uuid_str = bytes_to_uuid(uuid_bytes)
                    if uuid_str == TARGET_IBEACON_UUID and major_val in allowed_majors:
                        is_ibeacon = True
                        distance = estimate_distance(rssi_val, CALIBRATED_MEASURED_POWER_DEFAULT, PATH_LOSS_EXPONENT_DEFAULT)
                        beacon_last_seen_data[device.address] = {
                            'timestamp': time.time(),
                            'mac': device.address,
                            'major': major_val,
                            'minor': minor_val,
                            'rssi': rssi_val,
                            'distance': distance
                        }
                        logging.info(f"iBeacon erkannt: MAC={device.address}, Major={major_val}, Minor={minor_val}, RSSI={rssi_val} dBm, Distanz={distance:.2f}m")
                except struct.error:
                    pass # Not a valid iBeacon packet structure

        # Log raw advertisement data for analysis (DEBUG level)
        # Manufacturer data keys are integers (manufacturer IDs), service data keys are strings (UUIDs).
        manufacturer_data_hex = {hex(k): v.hex() for k, v in advertisement_data.manufacturer_data.items()} if advertisement_data.manufacturer_data else "{}"
        # Corrected: Service data keys are strings (UUIDs), so no hex() conversion needed for the key.
        service_data_hex = {k: v.hex() for k, v in advertisement_data.service_data.items()} if advertisement_data.service_data else "{}"
        local_name = advertisement_data.local_name if advertisement_data.local_name else "N/A"

        log_msg = (
            f"--- Raw Data for {device.address} (RSSI: {rssi_val} dBm) ---\n"
            f"  Local Name: {local_name}\n"
            f"  Manufacturer Data: {manufacturer_data_hex}\n"
            f"  Service Data: {service_data_hex}\n"
            f"--------------------------------------------------"
        )
        logging.debug(log_msg) # Changed to DEBUG level

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    
    try:
        while ble_scan_active:
            current_time = time.time()
            addresses_to_remove = [
                addr for addr, data in beacon_last_seen_data.items()
                if current_time - data['timestamp'] > ABSENCE_DETECTION_TIME
            ]
            for addr in addresses_to_remove:
                del beacon_last_seen_data[addr]
                logging.info(f"Beacon {addr} aus interner Liste entfernt (zu alt oder zu weit weg).")

            await asyncio.sleep(BLE_SCAN_INTERVAL_SEC)
    except asyncio.CancelledError:
        logging.info("Scan-Loop abgebrochen.")
    finally:
        await scanner.stop()
        logging.info("BLE Scanner gestoppt.")

# --- Hauptausführung ---
if __name__ == "__main__":
    # Ensure multiprocessing is set to spawn for compatibility
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Programm beendet durch Benutzer (Strg+C).")
        ble_scan_active = False # Signal to the asyncio task to stop
        # Give the asyncio loop a moment to process the stop signal
        time.sleep(1) 
    except Exception as e:
        logging.critical(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        cleanup_gpio()
        logging.info("Programm beendet.")