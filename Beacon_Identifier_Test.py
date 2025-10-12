# Program: Beacon_Identifier_Test.py
# Purpose: Test program to identify beacons using multiple criteria (iBeacon, Eddystone UID, Eddystone URL, MAC).
# Author: Your Name / CircuIT
# Creation Date: August 17, 2025
# Modified: August 17, 2025 - Initial implementation for multi-factor beacon identification.
# Corrected: August 17, 2025 - Adjusted to new beacon_identities.json structure with system_globals.
# Corrected: August 17, 2025, 15:25 UTC - Fixed NameError: 'ble_scan_active' is not defined.
# Corrected: August 17, 2025, 15:30 UTC - Corrected decode_eddystone_url function for better URL parsing.
# Corrected: August 17, 2025, 16:15 UTC - Enhanced logging for beacon identification failures.
# Corrected: August 17, 2025, 16:40 UTC - Further refined decode_eddystone_url to correctly handle inline URL compressions.
# Corrected: August 17, 2025, 17:00 UTC - Robustified Eddystone UID/URL parsing and added more debug prints.
# Corrected: August 17, 2025, 17:15 UTC - Refined Eddystone parsing based on observed log issues (UID=None, URL issues).
# Corrected: August 17, 2025, 20:30 UTC - Applied precise offset corrections for iBeacon, Eddystone UID, and Eddystone URL parsing
#            based on provided Minew Frame Definitions.
# Corrected: August 17, 2025, 21:30 UTC - Implemented multi-packet identification state tracking.
#            Removed TARGET_MAJOR_FILTER. Consolidated config from beacon_identities.json.
# Corrected: August 17, 2025, 22:15 UTC - Fixed initial last_packet_time for beacon_identification_state to prevent immediate timeouts.
# Corrected: August 17, 2025, 22:50 UTC - Moved URL mismatch logging to INFO level with detailed expected/received values.
# Corrected: August 17, 2025, 23:00 UTC - Implemented case-insensitive comparison for Eddystone URL.
# Corrected: August 18, 2025, 09:00 UTC - Adapted to read from system_config.json, loading all global parameters.

import asyncio
import time
import os
import logging
import struct
import json

# BLE Imports
from bleak import BleakScanner

# --- Logging Konfiguration ---
# Initial configuration, will be overridden by system_config.json later
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - IDENTIFIER - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# --- KONFIGURATION ---
SYSTEM_CONFIG_FILE = "system_config.json"

# --- Globale Konstanten (werden aus JSON geladen) ---
# Initialwerte, die durch die Konfiguration überschrieben werden
TARGET_IBEACON_UUID = ""
EDDYSTONE_NAMESPACE_ID = ""
BLE_SCAN_INTERVAL_SEC = 1.0 
IDENTIFICATION_TIMEOUT_SEC = 4.0 

ble_scan_active = True # Control flag for the scan loop

# Global state to track identification progress for each beacon MAC
# { "MAC_ADDRESS": { "name": "Beacon Name", "is_allowed": true/false,
#                    "ibeacon_data": {}, "uid_data": {}, "url_data": "",
#                    "last_packet_time": float, "is_fully_identified": bool,
#                    "known_beacon_config": {} } }
beacon_identification_state = {} 

# --- Hilfsfunktionen ---

def bytes_to_uuid(b):
    # Ensure bytes object has correct length for UUID
    if len(b) != 16:
        logging.warning(f"UUID bytes have incorrect length: {len(b)}. Expected 16.")
        return None # Or raise an error
    return f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}".upper()

def read_system_config():
    """
    Liest die Systemkonfigurationsdatei (system_config.json).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, SYSTEM_CONFIG_FILE)

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logging.info(f"Systemkonfiguration aus '{SYSTEM_CONFIG_FILE}' geladen.")
                return config
        except Exception as e:
            logging.error(f"Fehler beim Laden von '{SYSTEM_CONFIG_FILE}': {e}")
            return None
    else:
        logging.error(f"Systemkonfigurationsdatei '{SYSTEM_CONFIG_FILE}' nicht gefunden.")
        return None

def decode_eddystone_url(payload_bytes_starting_with_scheme):
    """
    Decodes Eddystone URL payload bytes into a human-readable URL.
    This version assumes payload_bytes_starting_with_scheme starts with the URL Scheme Prefix.
    """
    url_schemes = {
        0x00: "http://www.", 0x01: "https://www.", 0x02: "http://", 0x03: "https://",
    }
    url_suffixes = {
        0x00: ".com/", 0x01: ".org/", 0x02: ".edu/", 0x03: ".net/", 0x04: ".info/",
        0x05: ".biz/", 0x06: ".gov/", 0x07: ".com", 0x08: ".org", 0x09: ".edu",
        0x0a: ".net", 0x0b: ".info", 0x0c: ".biz", 0x0d: ".gov",
    }

    if not payload_bytes_starting_with_scheme or len(payload_bytes_starting_with_scheme) < 1:
        logging.debug("decode_eddystone_url: Empty or too short payload.")
        return None

    scheme_byte = payload_bytes_starting_with_scheme[0]
    url_result = url_schemes.get(scheme_byte, "")
    if not url_result:
        logging.debug(f"decode_eddystone_url: Unknown scheme byte {hex(scheme_byte)}")
        return None # Unknown scheme

    # Iterate through the rest of the payload bytes, applying suffix expansions
    i = 1 # Start from the byte after the scheme byte
    while i < len(payload_bytes_starting_with_scheme):
        byte_val = payload_bytes_starting_with_scheme[i]
        if byte_val in url_suffixes:
            url_result += url_suffixes[byte_val]
        else:
            # Decode a segment of bytes until next suffix or end
            start_segment = i
            while i < len(payload_bytes_starting_with_scheme) and payload_bytes_starting_with_scheme[i] not in url_suffixes:
                i += 1
            # Decode the segment as UTF-8
            try:
                url_result += payload_bytes_starting_with_scheme[start_segment:i].decode('utf-8', errors='ignore')
            except UnicodeDecodeError:
                logging.warning(f"decode_eddystone_url: Could not decode URL segment: {payload_bytes_starting_with_scheme[start_segment:i].hex()}")
                return None # Or handle as error
            i -= 1 # Adjust index as loop increments it one too many

        i += 1 # Move to next byte

    return url_result

# --- Haupt-Asynchrone Funktion ---
async def main():
    global ble_scan_active, TARGET_IBEACON_UUID, EDDYSTONE_NAMESPACE_ID, \
           BLE_SCAN_INTERVAL_SEC, IDENTIFICATION_TIMEOUT_SEC, beacon_identification_state # Access global constants

    system_config = read_system_config()
    if not system_config:
        logging.error("Systemkonfiguration konnte nicht geladen werden. Programm beendet.")
        return

    # Load system globals
    system_globals = system_config.get("system_globals", {})
    TARGET_IBEACON_UUID = system_globals.get("ibeacon_uuid", TARGET_IBEACON_UUID)
    EDDYSTONE_NAMESPACE_ID = system_globals.get("eddystone_namespace_id", EDDYSTONE_NAMESPACE_ID)
    BLE_SCAN_INTERVAL_SEC = system_globals.get("ble_scan_interval_sec", BLE_SCAN_INTERVAL_SEC)
    IDENTIFICATION_TIMEOUT_SEC = system_globals.get("identification_timeout_sec", IDENTIFICATION_TIMEOUT_SEC)

    # Configure logging based on system_config.json
    logging_config = system_globals.get("logging_config", {})
    log_level_str = logging_config.get("level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Clear existing handlers to reconfigure
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    handlers = [logging.StreamHandler()]
    if logging_config.get("file_enabled", False):
        log_file_path = logging_config.get("file_path", "tuer_oeffner.log")
        handlers.append(logging.FileHandler(log_file_path))

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - IDENTIFIER - %(levelname)s - %(message)s',
        handlers=handlers
    )
    logging.info(f"Logging-Level auf {log_level_str} gesetzt.")


    if not TARGET_IBEACON_UUID or not EDDYSTONE_NAMESPACE_ID:
        logging.error("Globale System-Konstanten (iBeacon UUID oder Eddystone Namespace ID) fehlen in der Konfigurationsdatei.")
        return

    known_beacons_config = system_config.get("known_beacons", [])
    auth_criteria = system_config.get("auth_criteria", {})

    # Pre-fill beacon_identification_state with known beacons
    current_time_for_init = time.time() 
    for beacon_cfg in known_beacons_config:
        mac_addr = beacon_cfg.get("mac_address")
        if mac_addr:
            beacon_identification_state[mac_addr] = {
                "name": beacon_cfg.get("name", "Unbekannt"),
                "is_allowed": beacon_cfg.get("is_allowed", False),
                "ibeacon_data": None,
                "uid_data": None,
                "url_data": None,
                "last_packet_time": current_time_for_init, 
                "is_fully_identified": False,
                "known_beacon_config": beacon_cfg # Store full config for comparison
            }
    
    logging.info("Beacon Identifier Test gestartet. Drücken Sie Strg+C zum Beenden.")
    logging.info(f"System iBeacon UUID: {TARGET_IBEACON_UUID}")
    logging.info(f"System Eddystone Namespace ID: {EDDYSTONE_NAMESPACE_ID}")
    logging.info(f"Bekannte Beacons zur Identifikation: {', '.join([s['name'] for s in known_beacons_config])}")


    def detection_callback(device, advertisement_data):
        current_mac = device.address
        
        # If MAC is not in our known_beacons_config, ignore it for identification purposes
        if current_mac not in beacon_identification_state:
            # Log unknown beacons only at DEBUG level to avoid flooding
            logging.debug(f"Unbekannter Beacon (nicht in config): MAC={current_mac}, RSSI={advertisement_data.rssi} dBm.")
            # Log raw advertisement data for analysis (DEBUG level)
            manufacturer_data_hex = {hex(k): v.hex() for k, v in advertisement_data.manufacturer_data.items()} if advertisement_data.manufacturer_data else {}
            service_data_hex = {k: v.hex() for k, v in advertisement_data.service_data.items()} if advertisement_data.service_data else {}
            local_name = advertisement_data.local_name if advertisement_data.local_name else "N/A"
            log_msg = (
                f"--- Raw Data for {current_mac} (RSSI: {advertisement_data.rssi} dBm) ---\n"
                f"  Local Name: {local_name}\n"
                f"  Manufacturer Data: {manufacturer_data_hex}\n"
                f"  Service Data: {service_data_hex}\n"
                f"--------------------------------------------------"
            )
            logging.debug(log_msg)
            return # Skip further processing for unknown beacons

        # Get current state for this beacon
        beacon_state = beacon_identification_state[current_mac]
        beacon_config = beacon_state["known_beacon_config"]

        # Parse iBeacon data
        parsed_ibeacon = None
        # Manufacturer Data for Apple iBeacon is 0x004C
        if 0x004C in advertisement_data.manufacturer_data:
            mfg_data = advertisement_data.manufacturer_data[0x004C]
            # Check for iBeacon Type (0x02) and Data Length (0x15) - from Minew spec
            if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
                try:
                    # Minew iBeacon spec: UUID at offset 9 (relative to Manufacturer Data field, after 0x004C, 0x02, 0x15)
                    # This means mfg_data[2:18] are UUID bytes
                    uuid_bytes = mfg_data[2:18] 
                    major_val = struct.unpack_from(">H", mfg_data, 18)[0] # Major at offset 25
                    minor_val = struct.unpack_from(">H", mfg_data, 20)[0] # Minor at offset 27
                    # measured_power = struct.unpack_from(">b", mfg_data, 22)[0] # RSSI at 1m at offset 29
                    
                    # Check against global iBeacon UUID and config's major/minor
                    if bytes_to_uuid(uuid_bytes) == TARGET_IBEACON_UUID and \
                       major_val == beacon_config["ibeacon"]["major"] and \
                       minor_val == beacon_config["ibeacon"]["minor"]:
                        parsed_ibeacon = {
                            "uuid": bytes_to_uuid(uuid_bytes),
                            "major": major_val,
                            "minor": minor_val
                        }
                    else:
                        logging.debug(f"iBeacon mismatch for {current_mac}: UUID={bytes_to_uuid(uuid_bytes)}, Major={major_val}, Minor={minor_val}")
                except struct.error as e:
                    logging.debug(f"iBeacon struct error for {current_mac}: {e}")
                except Exception as e:
                    logging.debug(f"iBeacon parsing error for {current_mac}: {e}")

        # Parse Eddystone data (UID and URL)
        parsed_eddystone_uid = None
        parsed_eddystone_url = None
        # Eddystone Service UUID is 0xFEAA
        eddystone_service_uuid_str = "0000feaa-0000-1000-8000-00805f9b34fb"
        if eddystone_service_uuid_str in advertisement_data.service_data:
            eddystone_payload = advertisement_data.service_data[eddystone_service_uuid_str]
            
            logging.debug(f"Raw Eddystone Payload for {current_mac}: {eddystone_payload.hex()}")

            if eddystone_payload and len(eddystone_payload) >= 1:
                frame_type = eddystone_payload[0]
                
                if frame_type == 0x00: # UID Frame
                    # Minew Eddystone UID spec: Frame Type (0), Ranging Data (1), Namespace (2-11), Instance (12-17)
                    if len(eddystone_payload) >= 18: # Total length including Frame Type and Ranging Data
                        namespace_id_bytes = eddystone_payload[2:12] # Corrected offset
                        instance_id_bytes = eddystone_payload[12:18] # Corrected offset
                        
                        logging.debug(f"UID Namespace from payload: {namespace_id_bytes.hex().upper()}")
                        logging.debug(f"UID Instance from payload: {instance_id_bytes.hex().upper()}")

                        # Check against global Eddystone Namespace ID and config's instance ID
                        if namespace_id_bytes.hex().upper() == EDDYSTONE_NAMESPACE_ID and \
                           instance_id_bytes.hex().upper() == beacon_config["eddystone_uid"]["instance_id"]:
                            parsed_eddystone_uid = {
                                "namespace_id": namespace_id_bytes.hex().upper(),
                                "instance_id": instance_id_bytes.hex().upper()
                            }
                        else:
                            logging.debug(f"UID mismatch for {current_mac}: Expected Namespace {EDDYSTONE_NAMESPACE_ID}, Instance {beacon_config['eddystone_uid']['instance_id']}, got Namespace {namespace_id_bytes.hex().upper()}, Instance {instance_id_bytes.hex().upper()}")
                    else:
                        logging.debug(f"UID payload too short for {current_mac}: {len(eddystone_payload)} bytes")
                elif frame_type == 0x10: # URL Frame
                    # Minew Eddystone URL spec: Frame Type (0), Ranging Data (1), URL Scheme Prefix (2), Encoded URL (3+)
                    if len(eddystone_payload) >= 3: # Need at least Frame Type, Ranging Data, URL Scheme Prefix
                        # Pass payload starting from URL Scheme Prefix to decode_eddystone_url
                        parsed_eddystone_url = decode_eddystone_url(eddystone_payload[2:]) 
                        logging.debug(f"Parsed Eddystone URL for {current_mac}: {parsed_eddystone_url}")
                        
                        # Check against config's URL
                        # Compare URLs case-insensitively
                        if parsed_eddystone_url and parsed_eddystone_url.lower() == beacon_config["eddystone_url"].lower(): # Corrected: Case-insensitive comparison
                            pass # Match, keep parsed_eddystone_url
                        else:
                            # Corrected: Log on INFO level with expected and received
                            logging.info(f"URL mismatch for {current_mac}: Expected '{beacon_config['eddystone_url']}', got '{parsed_eddystone_url}'") 
                            parsed_eddystone_url = None # Mark as not matching if it doesn't match config
                    else:
                        logging.debug(f"URL payload too short for {current_mac}: {len(eddystone_payload)} bytes")
                elif frame_type == 0x20: # TLM Frame
                    logging.debug(f"Eddystone TLM frame detected for {current_mac}. Not parsing.")
                else:
                    logging.debug(f"Unknown Eddystone Frame Type for {current_mac}: {hex(frame_type)}")
            else:
                logging.debug(f"Empty Eddystone payload for {current_mac}")

        # --- Update Beacon State ---
        if parsed_ibeacon:
            beacon_state['ibeacon_data'] = parsed_ibeacon
        if parsed_eddystone_uid:
            beacon_state['uid_data'] = parsed_eddystone_uid
        if parsed_eddystone_url:
            beacon_state['url_data'] = parsed_eddystone_url
        beacon_state['last_packet_time'] = time.time()

        # --- Check for Full Identification ---
        if not beacon_state['is_fully_identified']:
            is_match = True
            matched_criteria = []
            
            # Check iBeacon requirement
            if auth_criteria.get("ibeacon", "DISABLED") == "REQUIRED":
                if beacon_state['ibeacon_data']:
                    matched_criteria.append("iBeacon")
                else:
                    is_match = False
            elif auth_criteria.get("ibeacon", "DISABLED") == "OPTIONAL":
                if beacon_state['ibeacon_data']:
                    matched_criteria.append("iBeacon (Optional)")
            
            # Check Eddystone UID requirement
            if is_match and auth_criteria.get("eddystone_uid", "DISABLED") == "REQUIRED":
                if beacon_state['uid_data']:
                    matched_criteria.append("Eddystone UID")
                else:
                    is_match = False
            elif is_match and auth_criteria.get("eddystone_uid", "DISABLED") == "OPTIONAL":
                if beacon_state['uid_data']:
                    matched_criteria.append("Eddystone UID (Optional)")

            # Check Eddystone URL requirement
            if is_match and auth_criteria.get("eddystone_url", "DISABLED") == "REQUIRED":
                if beacon_state['url_data']:
                    matched_criteria.append("Eddystone URL")
                else:
                    is_match = False
            elif is_match and auth_criteria.get("eddystone_url", "DISABLED") == "OPTIONAL":
                if beacon_state['url_data']:
                    matched_criteria.append("Eddystone URL (Optional)")
            
            # Check MAC Address requirement
            if is_match and auth_criteria.get("mac_address", "DISABLED") == "REQUIRED":
                # MAC is already used as key, so it implicitly matches.
                # This check is more about if it's required for auth.
                matched_criteria.append("MAC Address")
            elif is_match and auth_criteria.get("mac_address", "DISABLED") == "OPTIONAL":
                matched_criteria.append("MAC Address (Optional)") # MAC is always present if beacon_state exists


            if is_match:
                beacon_state['is_fully_identified'] = True
                logging.info(f"*** Beacon '{beacon_state['name']}' ({current_mac}) VOLLSTÄNDIG IDENTIFIZIERT! Kriterien: {', '.join(matched_criteria)} ***")
            else:
                # Log current state if not fully identified yet
                missing_criteria = []
                # Check REQUIRED criteria that are missing
                if auth_criteria.get("ibeacon", "DISABLED") == "REQUIRED" and not beacon_state['ibeacon_data']: missing_criteria.append("iBeacon")
                if auth_criteria.get("eddystone_uid", "DISABLED") == "REQUIRED" and not beacon_state['uid_data']: missing_criteria.append("Eddystone UID")
                if auth_criteria.get("eddystone_url", "DISABLED") == "REQUIRED" and not beacon_state['url_data']: missing_criteria.append("Eddystone URL")
                # MAC address is always present if the beacon is in beacon_identification_state

                if missing_criteria:
                    logging.info(f"Identifikation für Beacon '{beacon_state['name']}' ({current_mac}) unvollständig. Fehlt: {', '.join(missing_criteria)}. "
                                 f"iBeacon: {'OK' if beacon_state['ibeacon_data'] else 'N/A'}, UID: {'OK' if beacon_state['uid_data'] else 'N/A'}, URL: {'OK' if beacon_state['url_data'] else 'N/A'}")
                else:
                    # This case should ideally not be reached if all requirements are checked and some are missing.
                    # It might indicate that all REQUIRED criteria are met, but OPTIONAL ones are missing,
                    # or there's a logic error.
                    logging.debug(f"Beacon '{beacon_state['name']}' ({current_mac}) not fully identified, but no REQUIRED criteria missing. Check logic.")


        # Log raw advertisement data for analysis (DEBUG level)
        manufacturer_data_hex = {hex(k): v.hex() for k, v in advertisement_data.manufacturer_data.items()} if advertisement_data.manufacturer_data else {}
        service_data_hex = {k: v.hex() for k, v in advertisement_data.service_data.items()} if advertisement_data.service_data else {}
        local_name = advertisement_data.local_name if advertisement_data.local_name else "N/A"

        log_msg = (
            f"--- Raw Data for {current_mac} (RSSI: {advertisement_data.rssi} dBm) ---\n"
            f"  Local Name: {local_name}\n"
            f"  Manufacturer Data: {manufacturer_data_hex}\n"
            f"  Service Data: {service_data_hex}\n"
            f"--------------------------------------------------"
        )
        logging.debug(log_msg)

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    
    try:
        while ble_scan_active:
            current_time = time.time()
            # Cleanup/Timeout for identification state
            beacons_to_remove = []
            for mac, state in beacon_identification_state.items():
                if current_time - state['last_packet_time'] > IDENTIFICATION_TIMEOUT_SEC:
                    if not state['is_fully_identified']:
                        logging.info(f"Identifikation für Beacon '{state['name']}' ({mac}) abgelaufen. Nicht vollständig identifiziert.")
                    beacons_to_remove.append(mac)
            
            for mac in beacons_to_remove:
                del beacon_identification_state[mac]
                # Re-initialize the state for this beacon if it's a known beacon from config
                # This ensures it can be re-identified if it comes back into range
                for beacon_cfg in known_beacons_config:
                    if beacon_cfg.get("mac_address") == mac:
                        beacon_identification_state[mac] = {
                            "name": beacon_cfg.get("name", "Unbekannt"),
                            "is_allowed": beacon_cfg.get("is_allowed", False),
                            "ibeacon_data": None,
                            "uid_data": None,
                            "url_data": None,
                            "last_packet_time": current_time, # Corrected: Initialize with current time
                            "is_fully_identified": False,
                            "known_beacon_config": beacon_cfg
                        }
                        break # Found and re-initialized

            await asyncio.sleep(BLE_SCAN_INTERVAL_SEC)
    except asyncio.CancelledError:
        logging.info("Scan-Loop abgebrochen.")
    finally:
        await scanner.stop()
        logging.info("BLE Scanner gestoppt.")

# --- Hauptausführung ---
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Programm beendet durch Benutzer (Strg+C).")
        ble_scan_active = False # Signal to the asyncio task to stop
        time.sleep(1) # Give the asyncio loop a moment to process the stop signal
    except Exception as e:
        logging.critical(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        logging.info("Programm beendet.")