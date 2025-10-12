# Program: test_beacon.py
# Purpose: Testprogramm zum Scannen und Erkennen von BLE iBeacons.
#          Sucht nach Beacons mit einem spezifischen Major-Wert und UUID.
# Author: Dr. Ralf Korell
# Creation Date: July 28, 2025
# Modified: August 14, 2025 - Anpassung für Minew Beacons und erweiterte Filterung

import asyncio
from bleak import BleakScanner
import struct # Für die präzisere Extraktion von iBeacon-Daten

# Konfiguration des zu suchenden iBeacons
TARGET_IBEACON_MAJOR = 1701 # Major für Carola, wie besprochen
# NEU: UUID des Minew-Beacons (bitte überprüfen, ob dies die korrekte UUID für DEINE Minew Beacons ist)
TARGET_IBEACON_UUID = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0"

# Funktion zur Umwandlung von Bytes in UUID-String
def bytes_to_uuid(b):
    # iBeacon UUID ist 16 Bytes
    # Format: 4-2-2-2-6 bytes
    return f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}".upper()

async def scan_for_ibeacons():
    print("Starte BLE-Scan nach iBeacons...")
    print(f"Suche nach iBeacon mit Major: {TARGET_IBEACON_MAJOR} und UUID: {TARGET_IBEACON_UUID}")
    print("Drücken Sie Strg+C zum Beenden.")

    def detection_callback(device, advertisement_data):
        rssi_val = advertisement_data.rssi
        
        # iBeacon-Daten sind oft im manufacturer_data (Apple Manufacturer ID ist 0x004C)
        if 0x004C in advertisement_data.manufacturer_data:
            mfg_data = advertisement_data.manufacturer_data[0x004C]
            
            # iBeacon-Format:
            # 0-1: iBeacon Indicator (0x0215)
            # 2-17: UUID (16 bytes)
            # 18-19: Major (2 bytes)
            # 20-21: Minor (2 bytes)
            # 22: Measured Power (1 byte)

            # Prüfe auf iBeacon-Indikator (0x0215) und Mindestlänge (23 Bytes nach Manufacturer ID)
            if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
                try:
                    uuid_bytes, major_val, minor_val, measured_power = struct.unpack_from(">16sHHb", mfg_data, 2)
                except struct.error:
                    # Manchmal sind die Daten nicht vollständig oder korrekt formatiert
                    # print(f"Warnung: Fehler beim Entpacken der iBeacon-Daten für {device.address}")
                    return

                uuid_str = bytes_to_uuid(uuid_bytes)

                # NEU: Filtern nach UUID, um nur die Minew Beacons zu erfassen
                if TARGET_IBEACON_UUID and uuid_str != TARGET_IBEACON_UUID:
                   return

                if major_val == TARGET_IBEACON_MAJOR:
                    #print(f"\n--- iBeacon gefunden! ---")
                    #print(f"  Name: {device.name if device.name else 'Unbekannt'}")
                    #print(f"  Adresse: {device.address}")
                    print(f"  RSSI (aktuell gemessen): {rssi_val} dBm") # Wichtig: Dies ist der aktuell empfangene Wert
                    #print(f"  UUID: {uuid_str}")
                    print(f"  Major: {major_val}")
                    #print(f"  Minor: {minor_val}")
                    print(f"  Measured Power (Tx Power @ 1m vom Beacon): {measured_power} dBm") # Dies ist der vom Beacon angegebene Wert
                    # print(f"  Advertisement Data: {advertisement_data}") # Kann für Debugging nützlich sein
        
        # Für Eddystone-Beacons (falls du diese auch hast) - nicht relevant für iBeacon-Setup
        # if "0000feaa-0000-1000-8000-00805f9b34fb" in advertisement_data.service_data:
        #     pass


    scanner = BleakScanner(detection_callback=detection_callback)
    
    # Starte den Scan im Hintergrund
    await scanner.start()
    
    # Halte den Scan am Laufen, bis das Programm beendet wird
    while True:
        await asyncio.sleep(1.0) # Warte 1 Sekunde, um CPU nicht zu überlasten

# Hauptausführung
if __name__ == "__main__":
    try:
        asyncio.run(scan_for_ibeacons())
    except KeyboardInterrupt:
        print("\nScan durch Benutzer beendet.")
    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
    finally:
        # BleakScanner.stop() wird von asyncio.run() beim Beenden des Tasks aufgerufen
        pass