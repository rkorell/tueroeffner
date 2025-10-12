# Program: BLE_Calib_Terminal.py
# Purpose: Guided calibration tool for BLE iBeacon proximity detection.
#          Collects raw RSSI data at known distances and provides confirmation.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: August 19, 2025
# Modified: August 19, 2025 - Initial terminal-only implementation.
# Corrected: August 19, 2025, 16:45 UTC - Fixed BleakScanner initialization (AttributeError) and implemented
#            continuous CSV logging after each measurement phase to prevent data loss on crash.
# Corrected: August 19, 2025, 17:00 UTC - Fixed BleakScanner.is_scanning AttributeError and ensured robust CSV/JSON export.
# Corrected: August 19, 2025, 17:15 UTC - Ensured CSV and JSON files are actually written to disk by awaiting async calls and flushing.
# Corrected: August 19, 2025, 17:30 UTC - Verified file writing logic and data consistency for CSV and JSON export.
# Corrected: August 19, 2025, 17:45 UTC - Refactored to write raw data directly to CSV from callback, removed in-program analysis,
#            and added robust CSV confirmation check with optimized reading.
# Corrected: August 20, 2025, 11:35 UTC - Fixed SyntaxError: f-string: unmatched '[' in confirm_csv_data_integrity.
# Corrected: August 20, 2025, 11:40 UTC - Re-fixed SyntaxError: f-string: unmatched '[' in confirm_csv_data_integrity.
# Corrected: August 20, 2025, 11:45 UTC - Final fix for f-string SyntaxError.
# Corrected: August 20, 2025, 11:50 UTC - Replaced problematic f-string with .format() for robust string formatting.

import asyncio
import time
import os
import csv
import json
import logging
import statistics # For standard deviation (still used in estimate_distance, but not for analysis here)
import numpy as np # For linear regression (removed from this script)
import math # For log10 (still used in estimate_distance)

# BLE Imports
from bleak import BleakScanner
import struct

# --- Logging Konfiguration für den Kalibrator ---
# Log-Meldungen werden in die Konsole und in eine Datei geschrieben.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - BLE_CALIB - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(), # Ausgabe auf die Konsole
        logging.FileHandler("ble_calibrator.log") # Ausgabe in eine Logdatei
    ]
)

# --- Globale Variablen für den BLE Scan ---
# Stores the latest RSSI for each targeted MAC address (for internal use by _run_ble_scan_background_task)
beacon_last_seen_data = {} 

# NEU: Globale Variable für den CSV-Writer und die aktuelle Distanz
csv_writer = None
csv_file = None
current_target_distance = 0.0 # Wird vom Haupt-Workflow gesetzt

# --- KONFIGURATION ---

# BLE iBeacon Konfiguration
TARGET_IBEACON_UUID = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0" # UUID ist für alle Minew Beacons identisch
CALIBRATED_MEASURED_POWER_DEFAULT = -77 # Kalibrierter Measured Power (Tx Power @ 1m vom Beacon)
PATH_LOSS_EXPONENT_DEFAULT = 2.5 # Pfadverlust-Exponent (N): Typischerweise 2.0 für freie Sicht, 2.5-4.0 für Innenräume.

# Proximity und Debouncing Konfiguration (relevant für _run_ble_scan_background_task)
ABSENCE_DETECTION_TIME = 10 # Sekunden: Zeit, die der Beacon nicht erkannt werden darf, um aus der Liste zu fallen

# Konfigurationsdatei für erlaubte Nutzer und deren Beacons (für allowed_majors)
ALLOWED_USERS_CONFIG = "Erlaubte_Nutzer.conf"

# Kalibrierungsspezifische Konfiguration
CALIBRATION_DISTANCES = [
    # Annäherung 1: Start bei 5m, engere Schritte im Nahbereich
    5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.75, 1.5, 1.25, 1.0, 0.75, 0.5, 0.25,
    # Entfernung 1: Rückweg
    0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0,
    # Annäherung 2: Start bei 4m, engere Schritte im Nahbereich
    4.0, 3.5, 3.0, 2.5, 2.0, 1.75, 1.5, 1.25, 1.0, 0.75, 0.5, 0.25
]
PRE_MEASUREMENT_DELAY_SEC = 5 # Sekunden Countdown vor jeder Messphase
MEASUREMENT_DURATION_SEC = 15 # Sekunden Dauer der Datensammlung pro Abstand
BLE_SCAN_INTERVAL_SEC = 1.0 # Sekunden Intervall für den BLE-Scan (für Hintergrund-Scan)

# --- Hilfsfunktionen ---

def cleanup_gpio():
    """Räumt die GPIO-Einstellungen auf. (Platzhalter, da nicht direkt verwendet)"""
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
    Liest die Konfigurationsdatei für erlaubte Nutzer und deren Beacons ein.
    Format: Name;wahr/falsch;Major1;Major2;Major3
    Gibt eine Liste von Dictionaries zurück, die die erwarteten Beacons repräsentieren.
    """
    allowed_users = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, ALLOWED_USERS_CONFIG)

    expected_beacons_list = [] # NEU: Liste der erwarteten Beacons

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
                                major_val = int(major_str)
                                beacon_majors.append(major_val)
                                # NEU: Füge den erwarteten Beacon zur Liste hinzu
                                # Annahme: Minor ist nicht relevant für die Identifikation im Calibrator,
                                # aber wir könnten hier eine Liste von Major/Minor Paaren erwarten,
                                # wenn die Konfiguration das hergibt. Fürs Erste nur Major.
                                expected_beacons_list.append({"name": name, "major": major_val})
                            except ValueError:
                                logging.warning(f"Ungültiger Major-Wert '{major_str}' für Nutzer '{name}' in '{ALLOWED_USERS_CONFIG}'. Ignoriere.")
                    
                    allowed_users[name] = {
                        'allowed': allowed,
                        'beacon_majors': beacon_majors
                    }
        except Exception as e:
            logging.error(f"Fehler beim Lesen von '{ALLOWED_USERS_CONFIG}': {e}")
    return allowed_users, expected_beacons_list # NEU: Gibt auch die Liste der erwarteten Beacons zurück

# --- BLE Scan Callback und Schreiblogik ---
# NEU: bleak_detection_callback schreibt direkt in die CSV
def bleak_detection_callback(device, advertisement_data):
    global csv_writer, csv_file, current_target_distance # Zugriff auf globale Variablen

    if csv_writer is None or csv_file is None:
        logging.error("CSV-Writer oder -Datei ist nicht initialisiert. Kann keine Daten schreiben.")
        return

    rssi_val = advertisement_data.rssi
    
    if 0x004C in advertisement_data.manufacturer_data:
        mfg_data = advertisement_data.manufacturer_data[0x004C]
        
        if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
            try:
                uuid_bytes, major_val, minor_val, measured_power = struct.unpack_from(">16sHHb", mfg_data, 2)
            except struct.error:
                return

            uuid_str = bytes_to_uuid(uuid_bytes)

            global allowed_majors_for_scan # Muss in main_calibration_workflow gesetzt werden
            
            if uuid_str == TARGET_IBEACON_UUID and major_val in allowed_majors_for_scan:
                # Die Distanzschätzung hier ist nur zur Information, nicht für die Kalibrierung der Rohdaten
                distance = estimate_distance(rssi_val, CALIBRATED_MEASURED_POWER_DEFAULT, PATH_LOSS_EXPONENT_DEFAULT)
                
                # NEU: Datenpunkt für direkte CSV-Schreibung
                data_point_entry = {
                    'Timestamp': time.time(),
                    'Beacon_Address': device.address,
                    'Beacon_Major': major_val,
                    'Beacon_Minor': minor_val,
                    'RSSI_Value': rssi_val, # Roh-RSSI-Wert
                    'Calculated_Distance': distance, # Geschätzte Distanz zur Info
                    'Actual_Distance_Provided': current_target_distance # Aktuelle, physikalische Distanz
                }
                
                try:
                    csv_writer.writerow(data_point_entry)
                    csv_file.flush() # Daten sofort auf die Festplatte schreiben
                    os.fsync(csv_file.fileno()) # Sicherstellen, dass der OS-Puffer geleert wird
                    logging.debug(f"Rohdaten von {device.address}/{major_val}/{minor_val} (RSSI: {rssi_val}) bei {current_target_distance}m geschrieben.")
                except Exception as e:
                    logging.error(f"Fehler beim Schreiben von Rohdaten in CSV: {e}")
                
                # Aktualisiere beacon_last_seen_data (für interne Bereinigung im Scan-Task)
                beacon_last_seen_data[device.address] = {
                    'timestamp': time.time(),
                    'mac': device.address,
                    'major': major_val,
                    'minor': minor_val,
                    'rssi': rssi_val,
                    'distance': distance
                }

# NEU: _run_ble_scan_background_task vereinfacht, da Schreiblogik im Callback ist
async def _run_ble_scan_background_task(scanner_instance):
    """
    Führt den BLE-Scan kontinuierlich im Hintergrund aus und pflegt beacon_last_seen_data.
    """
    logging.info("BLE Scan Hintergrund-Task gestartet.")
    
    try:
        while True: 
            current_time = time.time()
            addresses_to_remove = [
                addr for addr, data in beacon_last_seen_data.items()
                if current_time - data['timestamp'] > ABSENCE_DETECTION_TIME
            ]
            for addr in addresses_to_remove:
                del beacon_last_seen_data[addr]
                logging.debug(f"Beacon {addr} aus Liste entfernt (zu alt oder zu weit weg).")

            await asyncio.sleep(BLE_SCAN_INTERVAL_SEC)
    except asyncio.CancelledError:
        logging.info("BLE Scan Hintergrund-Task beendet.")
    finally:
        pass # Scanner wird außerhalb dieses Tasks gestoppt


# --- Bestätigungsfunktion für CSV-Daten ---
def confirm_csv_data_integrity(csv_path, expected_beacons_list):
    print("\n")
    print("--- ÜBERPRÜFE ROHDATEN-CSV ---")
    logging.info(f"Überprüfe Rohdaten-CSV: '{csv_path}' auf erwartete Beacons.")
    
    found_beacons_in_csv_majors = set() # Set von Major-Werten, die in der CSV gefunden wurden
    
    # Konvertiere erwartete Beacons in ein Set von Major-Werten für effiziente Prüfung
    expected_majors_set = {b['major'] for b in expected_beacons_list}
    
    if not expected_majors_set:
        logging.warning("Keine erwarteten Beacons in der Konfiguration gefunden. Kann keine spezifische Bestätigung durchführen.")
        print("WARNUNG: Keine erwarteten Beacons konfiguriert. Überprüfung übersprungen.")
        return True # Nichts zu prüfen, also als erfolgreich ansehen

    # KORREKTUR: f-string Syntax behoben - Verwendung von .format() für Robustheit
    expected_beacons_str = ', '.join(['{} (Major: {})'.format(b['name'], b['major']) for b in expected_beacons_list])
    print(f"Erwartete Beacons (aus Konfiguration): {expected_beacons_str}")
    
    try:
        with open(csv_path, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Überprüfe, ob der Header korrekt ist
            expected_fieldnames = ['Timestamp', 'Beacon_Address', 'Beacon_Major', 'Beacon_Minor', 
                                   'RSSI_Value', 'Calculated_Distance', 'Actual_Distance_Provided']
            if reader.fieldnames != expected_fieldnames:
                logging.error(f"CSV-Header stimmt nicht überein. Erwartet: {expected_fieldnames}, Gefunden: {reader.fieldnames}")
                print("FEHLER: CSV-Datei hat unerwarteten Header. Überprüfung fehlgeschlagen.")
                return False

            for row in reader:
                try:
                    beacon_major = int(row['Beacon_Major'])
                    found_beacons_in_csv_majors.add(beacon_major)

                    # Optimierung: Wenn alle erwarteten Majors gefunden wurden, breche ab
                    if expected_majors_set.issubset(found_beacons_in_csv_majors):
                        logging.info("Alle erwarteten Major-Werte in CSV gefunden. Abbruch des Lesens.")
                        break 
                except ValueError:
                    logging.warning(f"Ungültiger numerischer Major-Wert in Zeile: {row.get('Beacon_Major', 'N/A')}. Zeile: {row}")
                except KeyError as ke:
                    logging.warning(f"Fehlender Schlüssel in CSV-Zeile: {ke} in {row}")
                except Exception as e:
                    logging.warning(f"Fehler beim Parsen einer CSV-Zeile: {e} in {row}")

        print("--- ERGEBNIS DER ÜBERPRÜFUNG ---")
        if not found_beacons_in_csv_majors:
            print("WARNUNG: Keine Beacon-Einträge in der CSV-Datei gefunden.")
            return False

        print(f"Tatsächlich in der CSV gefundene Major-Werte: {', '.join(map(str, sorted(list(found_beacons_in_csv_majors))))}")

        missing_majors = expected_majors_set - found_beacons_in_csv_majors
        
        if not missing_majors:
            print("\nERFOLG: Alle erwarteten Beacons wurden in der CSV-Datei gefunden!")
            return True
        else:
            print(f"\nWARNUNG: Folgende erwartete Beacons (Major-Werte) wurden NICHT in der CSV-Datei gefunden:")
            for major_id in missing_majors:
                # Versuche, den Namen des Beacons zu finden
                beacon_name = next((b['name'] for b in expected_beacons_list if b['major'] == major_id), f"Major: {major_id}")
                print(f"  - {beacon_name}")
            return False

    except FileNotFoundError:
        logging.error(f"Fehler: Rohdaten-CSV-Datei nicht gefunden unter '{csv_path}'.")
        print(f"FEHLER: Rohdaten-CSV-Datei nicht gefunden. Pfad: '{csv_path}'")
        return False
    except Exception as e:
        logging.error(f"Unerwarteter Fehler bei der CSV-Überprüfung: {e}", exc_info=True)
        print(f"FEHLER: Unerwarteter Fehler bei der CSV-Überprüfung: {e}")
        return False

# --- Haupt-Kalibrierungs-Workflow (Terminal-basiert) ---
# NEU: Globale Variable für erlaubte Major-Werte, zugänglich für bleak_detection_callback
allowed_majors_for_scan = set()

async def main_calibration_workflow():
    global allowed_majors_for_scan # Muss hier als global deklariert werden, um sie zu setzen
    global csv_writer, csv_file, current_target_distance # Zugriff auf globale Variablen

    print("\n" * 2) # Leerzeilen für bessere Sichtbarkeit
    print("=" * 60)
    print("      STARTE BLE BEACON KALIBRIERUNG (TERMINAL-MODUS)")
    print("=" * 60)
    print("\n")

    # Initialisiere allowed_majors_for_scan und erhalte erwartete Beacons
    allowed_users_data, expected_beacons_for_confirmation = read_allowed_users_config()
    for user_data in allowed_users_data.values():
        if user_data['allowed']:
            allowed_majors_for_scan.update(user_data['beacon_majors'])
    logging.info(f"Erlaubte Major-Werte für BLE-Filterung: {allowed_majors_for_scan}")
    
    if not allowed_majors_for_scan:
        logging.error("Keine erlaubten Major-Werte in 'Erlaubte_Nutzer.conf' gefunden. Bitte konfigurieren Sie mindestens einen Beacon.")
        print("\n" * 2)
        print("FEHLER: Keine Beacons zur Kalibrierung konfiguriert. Bitte 'Erlaubte_Nutzer.conf' prüfen.")
        print("\n" * 2)
        return

    # NEU: Pfad für die CSV-Rohdaten festlegen
    csv_output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"ble_calibration_raw_data_{int(time.time())}.csv")
    
    # NEU: CSV-Datei öffnen und Writer initialisieren
    try:
        csv_file = open(csv_output_path, 'w', newline='', encoding='utf-8')
        fieldnames = ['Timestamp', 'Beacon_Address', 'Beacon_Major', 'Beacon_Minor', 
                      'RSSI_Value', 'Calculated_Distance', 'Actual_Distance_Provided']
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        csv_writer.writeheader()
        csv_file.flush()
        os.fsync(csv_file.fileno())
        logging.info(f"Rohdaten-CSV-Datei '{csv_output_path}' initialisiert.")
    except Exception as e:
        logging.critical(f"Kritischer Fehler beim Initialisieren der CSV-Datei: {e}", exc_info=True)
        print("\n" * 2)
        print("Kritischer FEHLER: Konnte Rohdaten-CSV-Datei nicht initialisieren. Programmabbruch.")
        print("\n" * 2)
        return

    # NEU: BleakScanner korrekt initialisieren (Callback ist jetzt global)
    scanner = BleakScanner(bleak_detection_callback)
    
    # Start the BLE scanner
    await scanner.start()
    logging.info("BLE Scanner gestartet.")

    # Start the background scan task (now only manages cleanup of beacon_last_seen_data)
    scan_task = asyncio.create_task(_run_ble_scan_background_task(scanner), name="background_scan_task")

    try:
        # Set task name for current workflow to allow detection_callback to know if calibration is active
        asyncio.current_task().set_name("calibration_workflow_task")

        print("\n" * 2)
        print("--- KALIBRIERUNG STARTET ---")
        print("Folgen Sie den Anweisungen und bewegen Sie den Beacon entsprechend.")
        print("Das Programm wartet automatisch zwischen den Schritten.")
        print("\n" * 2)

        for i, target_distance in enumerate(CALIBRATION_DISTANCES):
            global current_target_distance # Aktualisiere die globale Variable
            current_target_distance = target_distance

            print("=" * 60)
            print(f"SCHRITT {i+1}/{len(CALIBRATION_DISTANCES)}")
            print(f"PLATZIEREN SIE DEN BEACON AUF: {target_distance:.1f} METER ENTFERNUNG ZUM RASPBERRY PI")
            print("=" * 60)
            print("\n")
            logging.info(f"Nächster Messpunkt: {target_distance:.1f} Meter.")
            
            # Countdown phase
            for count in range(PRE_MEASUREMENT_DELAY_SEC, 0, -1):
                print(f"Bereit in... {count} Sekunden")
                await asyncio.sleep(1)
            print("LOS!\n")

            # Measurement phase
            print(f"Messe bei {target_distance:.1f} Meter für {MEASUREMENT_DURATION_SEC} Sekunden.")
            print("Bewegen Sie den Beacon leicht, um verschiedene Signalpfade zu erfassen.")
            logging.info(f"Starte Messung bei {target_distance:.1f} Meter für {MEASUREMENT_DURATION_SEC} Sekunden.")
            
            # Wait for measurement duration, allowing background scan to fill buffer
            measurement_start_time = time.time()
            while time.time() - measurement_start_time < MEASUREMENT_DURATION_SEC:
                await asyncio.sleep(0.1) # Small sleep to yield control

            logging.info(f"Messphase bei {target_distance:.1f}m abgeschlossen.")
            
            print("\n")
            print("-" * 60)
            print("MESSUNG ABGESCHLOSSEN. BEREIT FÜR NÄCHSTEN SCHRITT.")
            print("-" * 60)
            print("\n" * 2)

        # Calibration finished successfully
        print("=" * 60)
        print("      KALIBRIERUNG ABGESCHLOSSEN!")
        print("      Rohdaten-Sammlung beendet.")
        print("=" * 60)
        logging.info("Geführte BLE Kalibrierung erfolgreich abgeschlossen.")
        
    except asyncio.CancelledError:
        logging.info("Kalibrierungs-Workflow abgebrochen.")
        print("\n" * 2)
        print("--- KALIBRIERUNG ABGEBROCHEN ---")
        print("\n" * 2)
    except Exception as e:
        logging.critical(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
        print("\n" * 2)
        print("=" * 60)
        print("      FEHLER WÄHREND DER KALIBRIERUNG!")
        print(f"      Details im Log: {e}")
        print("=" * 60)
        print("\n" * 2)
    finally:
        # Sicherstellen, dass Scanner und Tasks beendet werden
        if scan_task:
            scan_task.cancel()
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
        await scanner.stop()
        logging.info("BLE Scanner gestoppt.")

        # NEU: CSV-Datei schließen
        if csv_file:
            csv_file.close()
            logging.info(f"Rohdaten-CSV-Datei '{csv_output_path}' geschlossen.")
        
        # NEU: Bestätigung der CSV-Datenintegrität
        confirm_csv_data_integrity(csv_output_path, expected_beacons_for_confirmation)

        logging.info("Alle Tasks beendet. Programmende.")
        cleanup_gpio()


# --- Hauptausführung ---
if __name__ == "__main__":
    # Ensure multiprocessing is set to spawn for compatibility
    # This must be done at the very beginning of the main process
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)

    try:
        asyncio.run(main_calibration_workflow())
    except KeyboardInterrupt:
        logging.info("Programm beendet durch Benutzer (Strg+C).")
    except Exception as e:
        logging.critical(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)