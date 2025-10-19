# Program: ble_logic.py
# Purpose: Kapselt alle Funktionen und Logiken, die direkt mit dem BLE-Scan und der Beacon-Identifikation zu tun haben.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:20 UTC - Erstellung des ble_logic-Moduls.

import asyncio
import time
import os
import struct
import logging
from time import perf_counter

from bleak import BleakScanner

import config
import globals_state as gs

# --- BLE Hilfsfunktionen ---
def bytes_to_uuid(b):
    if len(b) != 16:
        logging.warning(f"BLE: UUID bytes have incorrect length: {len(b)}. Expected 16.")
        return None
    return f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}".upper()

def estimate_distance(rssi, measured_power, n):
    if rssi == 0:
        return -1.0
    return 10 ** ((measured_power - rssi) / (10 * n))

def decode_eddystone_url(payload_bytes_starting_with_scheme):
    url_schemes = {
        0x00: "http://www.", 0x01: "https://www.", 0x02: "http://", 0x03: "https://",
    }
    url_suffixes = {
        0x00: ".com/", 0x01: ".org/", 0x02: ".edu/", 0x03: ".net/", 0x04: ".info/",
        0x05: ".biz/", 0x06: ".gov/", 0x07: ".com", 0x08: ".org", 0x09: ".edu",
        0x0a: ".net", 0x0b: ".info", 0x0c: ".biz", 0x0d: ".gov",
    }

    if not payload_bytes_starting_with_scheme or len(payload_bytes_starting_with_scheme) < 1:
        logging.debug("BLE: decode_eddystone_url: Empty or too short payload.")
        return None

    scheme_byte = payload_bytes_starting_with_scheme[0]
    url_result = url_schemes.get(scheme_byte, "")
    if not url_result:
        logging.debug(f"BLE: decode_eddystone_url: Unknown scheme byte {hex(scheme_byte)}")
        return None

    i = 1 # Start from the byte after the scheme byte
    while i < len(payload_bytes_starting_with_scheme):
        byte_val = payload_bytes_starting_with_scheme[i]
        if byte_val in url_suffixes:
            url_result += url_suffixes[byte_val]
        else:
            start_segment = i
            while i < len(payload_bytes_starting_with_scheme) and payload_bytes_starting_with_scheme[i] not in url_suffixes:
                i += 1
            try:
                url_result += payload_bytes_starting_with_scheme[start_segment:i].decode('utf-8', errors='ignore')
            except UnicodeDecodeError:
                logging.warning(f"BLE: decode_eddystone_url: Could not decode URL segment: {payload_bytes_starting_with_scheme[start_segment:i].hex()}")
                return None
            i -= 1

        i += 1

    return url_result

# --- Callback für den Initial-Scan ---
def initial_scan_detection_callback(device, advertisement_data):
    current_mac = device.address
    
    # Nur bekannte Beacons verarbeiten
    if current_mac not in gs.beacon_identification_state:
        return

    beacon_state = gs.beacon_identification_state[current_mac]
    beacon_config = beacon_state["known_beacon_config"]

    # Hole die beacon-spezifischen Kalibrierungswerte, mit Fallback auf globale Standardwerte
    beacon_mp = beacon_config.get("calibrated_measured_power", config.get("system_globals.calibrated_measured_power_global_default", config.CALIBRATED_MEASURED_POWER_GLOBAL_DEFAULT))
    beacon_n = beacon_config.get("path_loss_exponent", config.get("system_globals.path_loss_exponent_global_default", config.PATH_LOSS_EXPONENT_GLOBAL_DEFAULT))

    # Aktualisiere die Distanzschätzung mit den korrekten Werten
    distance = estimate_distance(advertisement_data.rssi, beacon_mp, beacon_n)
    
    # Aktualisiere beacon_last_seen_data mit dem aktuellen RSSI und der korrigierten Distanz
    # Nur die Zeit und Distanz sind hier relevant, keine vollständige Identifikation
    gs.beacon_last_seen_data[current_mac] = {
        'timestamp': time.time(),
        'rssi': advertisement_data.rssi,
        'distance': distance
    }
    logging.debug(f"BLE_INITIAL: Beacon {current_mac} ({beacon_state['name']}) gesehen. RSSI: {advertisement_data.rssi}, Distanz: {distance:.2f}m")

# --- Funktion für den dedizierten Initial-Scan ---
async def _perform_initial_beacon_scan(duration_sec):
    logging.info(f"BLE: Starte dedizierten Initial-Scan für {duration_sec} Sekunden...")
    initial_scanner = BleakScanner(detection_callback=initial_scan_detection_callback)
    await initial_scanner.start()
    await asyncio.sleep(duration_sec)
    await initial_scanner.stop()
    logging.info("BLE: Initial-Scan beendet.")

# --- Haupt-BLE-Scan-Logik ---
def detection_callback(device, advertisement_data):
    if gs.TRACE_MODE:
        t0 = perf_counter()

    current_mac = device.address

    parsed_ibeacon = None
    parsed_eddystone_uid = None
    parsed_eddystone_url = None

    # If MAC is not in our known_beacons_config, ignore it for identification purposes
    if current_mac not in gs.beacon_identification_state:
        logging.debug(f"BLE: Unbekannter Beacon (nicht in config): MAC={current_mac}, RSSI={advertisement_data.rssi} dBm.")
        return  # Skip further processing for unknown beacons

    # Get current state for this beacon
    beacon_state = gs.beacon_identification_state[current_mac]
    beacon_cfg = beacon_state["known_beacon_config"]
    auth_criteria = config.get("auth_criteria", {})

    # Parse iBeacon data
    if 0x004C in advertisement_data.manufacturer_data:
        mfg_data = advertisement_data.manufacturer_data[0x004C]
        if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
            try:
                uuid_bytes = mfg_data[2:18]
                major_val = struct.unpack_from(">H", mfg_data, 18)[0]
                minor_val = struct.unpack_from(">H", mfg_data, 20)[0]

                if bytes_to_uuid(uuid_bytes) == config.get("system_globals.ibeacon_uuid", config.TARGET_IBEACON_UUID) and \
                   major_val == beacon_cfg["ibeacon"]["major"] and \
                   minor_val == beacon_cfg["ibeacon"]["minor"]:
                    parsed_ibeacon = {
                        "uuid": bytes_to_uuid(uuid_bytes),
                        "major": major_val,
                        "minor": minor_val
                    }
                else:
                    logging.debug(f"BLE: iBeacon mismatch for {current_mac}: UUID={bytes_to_uuid(uuid_bytes)}, Major={major_val}, Minor={minor_val}")
            except struct.error as e:
                logging.debug(f"BLE: iBeacon struct error for {current_mac}: {e}")
            except Exception as e:
                logging.debug(f"BLE: iBeacon parsing error for {current_mac}: {e}")

    # Parse Eddystone data (UID and URL)
    eddystone_service_uuid_str = "0000feaa-0000-1000-8000-00805f9b34fb"
    if eddystone_service_uuid_str in advertisement_data.service_data:
        eddystone_payload = advertisement_data.service_data[eddystone_service_uuid_str]

        logging.debug(f"BLE: Raw Eddystone Payload for {current_mac}: {eddystone_payload.hex()}")

        if eddystone_payload and len(eddystone_payload) >= 1:
            frame_type = eddystone_payload[0]

            if frame_type == 0x00:  # UID Frame
                if len(eddystone_payload) >= 18:  # Total length including Frame Type and Ranging Data
                    namespace_id_bytes = eddystone_payload[2:12]
                    instance_id_bytes = eddystone_payload[12:18]

                    logging.debug(f"BLE: UID Namespace from payload: {namespace_id_bytes.hex().upper()}")
                    logging.debug(f"BLE: UID Instance from payload: {instance_id_bytes.hex().upper()}")

                    if namespace_id_bytes.hex().upper() == config.get("system_globals.eddystone_namespace_id", config.EDDYSTONE_NAMESPACE_ID) and \
                       instance_id_bytes.hex().upper() == beacon_cfg["eddystone_uid"]["instance_id"]:
                        parsed_eddystone_uid = {
                            "namespace_id": namespace_id_bytes.hex().upper(),
                            "instance_id": instance_id_bytes.hex().upper()
                        }
                    else:
                        logging.debug(f"BLE: UID mismatch for {current_mac}: Expected Namespace {config.get('system_globals.eddystone_namespace_id', config.EDDYSTONE_NAMESPACE_ID)}, Instance {beacon_cfg['eddystone_uid']['instance_id']}, got Namespace {namespace_id_bytes.hex().upper()}, Instance {instance_id_bytes.hex().upper()}")
                else:
                    logging.debug(f"BLE: UID payload too short for {current_mac}: {len(eddystone_payload)} bytes")
            elif frame_type == 0x10:  # URL Frame
                if len(eddystone_payload) >= 3:  # Need at least Frame Type, Ranging Data, URL Scheme Prefix
                    parsed_eddystone_url = decode_eddystone_url(eddystone_payload[2:])
                    logging.debug(f"BLE: Parsed Eddystone URL for {current_mac}: {parsed_eddystone_url}")

                    if parsed_eddystone_url and parsed_eddystone_url.lower() == beacon_cfg["eddystone_url"].lower():
                        pass
                    else:
                        logging.info(f"BLE: URL mismatch for {current_mac}: Expected '{beacon_cfg['eddystone_url']}', got '{parsed_eddystone_url}'")
                        parsed_eddystone_url = None
                else:
                    logging.debug(f"BLE: URL payload too short for {current_mac}: {len(eddystone_payload)} bytes")
            elif frame_type == 0x20:  # TLM Frame
                logging.debug(f"BLE: Eddystone TLM frame detected for {current_mac}. Not parsing.")
            else:
                logging.debug(f"BLE: Unknown Eddystone Frame Type for {current_mac}: {hex(frame_type)}")
        else:
            logging.debug(f"BLE: Empty Eddystone payload for {current_mac}")

    # --- Update Beacon State ---
    if parsed_ibeacon:
        beacon_state['ibeacon_data'] = parsed_ibeacon
        if gs.TRACE_MODE:
            logging.info("TRACE: +%7.3f ms  iBeacon erkannt (MAC=%s)", (perf_counter() - t0) * 1000, current_mac)

    if parsed_eddystone_uid:
        beacon_state['uid_data'] = parsed_eddystone_uid
        if gs.TRACE_MODE:
            logging.info("TRACE: +%7.3f ms  Eddystone UID erkannt (MAC=%s)", (perf_counter() - t0) * 1000, current_mac)

    if parsed_eddystone_url:
        beacon_state['url_data'] = parsed_eddystone_url
        if gs.TRACE_MODE:
            logging.info("TRACE: +%7.3f ms  Eddystone URL erkannt (MAC=%s)", (perf_counter() - t0) * 1000, current_mac)

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
            matched_criteria.append("MAC Address")
        elif is_match and auth_criteria.get("mac_address", "DISABLED") == "OPTIONAL":
            matched_criteria.append("MAC Address (Optional)")

        if is_match:
            beacon_state['is_fully_identified'] = True
            logging.info(f"BLE: *** Beacon '{beacon_state['name']}' ({current_mac}) VOLLSTÄNDIG IDENTIFIZIERT! Kriterien: {', '.join(matched_criteria)} ***")
            if gs.TRACE_MODE and beacon_state.get('is_fully_identified'):
                logging.info(
                    "TRACE: +%7.3f ms  Beacon vollständig identifiziert (MAC=%s)",
                    (perf_counter() - t0) * 1000, device.address
                )
        else:
            missing_criteria = []
            if auth_criteria.get("ibeacon", "DISABLED") == "REQUIRED" and not beacon_state['ibeacon_data']:
                missing_criteria.append("iBeacon")
            if auth_criteria.get("eddystone_uid", "DISABLED") == "REQUIRED" and not beacon_state['uid_data']:
                missing_criteria.append("Eddystone UID")
            if auth_criteria.get("eddystone_url", "DISABLED") == "REQUIRED" and not beacon_state['url_data']:
                missing_criteria.append("Eddystone URL")

            if missing_criteria:
                logging.info(
                    f"BLE: Identifikation für Beacon '{beacon_state['name']}' ({current_mac}) unvollständig. "
                    f"Fehlt: {', '.join(missing_criteria)}. "
                    f"iBeacon: {'OK' if beacon_state['ibeacon_data'] else 'N/A'}, "
                    f"UID: {'OK' if beacon_state['uid_data'] else 'N/A'}, "
                    f"URL: {'OK' if beacon_state['url_data'] else 'N/A'}"
                )
            else:
                logging.debug(f"BLE: Beacon '{beacon_state['name']}' ({current_mac}) not fully identified, but no REQUIRED criteria missing. Check logic.")

    # --- Verwende beacon-spezifische Kalibrierungswerte für Distanzschätzung ---
    beacon_mp = beacon_cfg.get("calibrated_measured_power", config.get("system_globals.calibrated_measured_power_global_default", config.CALIBRATED_MEASURED_POWER_GLOBAL_DEFAULT))
    beacon_n = beacon_cfg.get("path_loss_exponent", config.get("system_globals.path_loss_exponent_global_default", config.PATH_LOSS_EXPONENT_GLOBAL_DEFAULT))
    distance = estimate_distance(advertisement_data.rssi, beacon_mp, beacon_n)

    gs.beacon_last_seen_data[current_mac] = {
        'timestamp': time.time(),
        'rssi': advertisement_data.rssi,
        'distance': distance
    }


async def scan_for_ibeacons_task():
    logging.info("BLE: Starte BLE-Scan nach iBeacons...")
    logging.info(f"BLE: Suche nach iBeacon UUID: {config.get('system_globals.ibeacon_uuid', config.TARGET_IBEACON_UUID)}")

    # Collect all allowed major values from known_beacons for filtering
    allowed_majors = set()
    for beacon_cfg in config.SYSTEM_CONFIG["known_beacons"]:
        allowed_majors.add(beacon_cfg["ibeacon"]["major"])
    logging.info(f"BLE: Erlaubte Major-Werte für BLE-Erkennung: {allowed_majors}")

    scanner = BleakScanner(detection_callback=detection_callback)
    await scanner.start()
    
    try:
        while True:
            current_time = time.time()
            # Cleanup/Timeout for identification state
            beacons_to_remove = []
            for mac, state in gs.beacon_identification_state.items():
                if current_time - state['last_packet_time'] > config.get("system_globals.identification_timeout_sec", config.IDENTIFICATION_TIMEOUT_SEC):
                    if not state['is_fully_identified']:
                        logging.info(f"BLE: Identifikation für Beacon '{state['name']}' ({mac}) abgelaufen. Nicht vollständig identifiziert.")
                    beacons_to_remove.append(mac)
            
            for mac in beacons_to_remove:
                # Holen Sie sich die ursprüngliche Konfiguration, um is_allowed zu erhalten
                original_beacon_config = None
                for cfg in config.SYSTEM_CONFIG["known_beacons"]:
                    if cfg.get("mac_address") == mac:
                        original_beacon_config = cfg
                        break

                if mac in gs.beacon_identification_state: # Prüfen, ob der MAC noch existiert
                    del gs.beacon_identification_state[mac] # Entfernen des alten Eintrags

                if original_beacon_config: # Nur neu initialisieren, wenn es ein bekannter Beacon ist
                    gs.beacon_identification_state[mac] = {
                        "name": original_beacon_config.get("name", "Unbekannt"),
                        "is_allowed": original_beacon_config.get("is_allowed", False),
                        "ibeacon_data": None,
                        "uid_data": None,
                        "url_data": None,
                        "last_packet_time": current_time,
                        "is_fully_identified": False,
                        "known_beacon_config": original_beacon_config,
                        "is_in_proximity_raw": False,
                        "proximity_state_change_time": current_time,
                        "is_in_proximity_debounced": False,
                        "is_currently_inside_house": False
                    }

            await asyncio.sleep(config.get("system_globals.ble_scan_interval_sec", config.BLE_SCAN_INTERVAL_SEC))
    except asyncio.CancelledError:
        logging.info("BLE: Scan-Loop abgebrochen.")
    finally:
        # Ensure scanner is stopped even if loop is cancelled
        await scanner.stop()
        logging.info("BLE: Scanner gestoppt.")