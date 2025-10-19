# Program: M_TuerOeffner.py
# Purpose: Automatisiertes Türöffnungssystem basierend auf Multi-Faktor BLE-Beacon-Identifikation.
#          Verwendet modulare Komponenten für Konfiguration, globalen Status, BLE, Display und Türsteuerung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:45 UTC - Erstellung des modularen Hauptskripts.

import asyncio
import time
import multiprocessing
import logging

# Import der modularen Komponenten
import config
import globals_state as gs
import ble_logic
import display_logic
import door_control

# --- Haupt-Asynchrone Funktion ---
async def main():
    logging.info("MAIN: Türöffnungssystem gestartet.")
    logging.info(f"MAIN: System iBeacon UUID: {config.get('system_globals.ibeacon_uuid', config.TARGET_IBEACON_UUID)}")
    logging.info(f"MAIN: System Eddystone Namespace ID: {config.get('system_globals.eddystone_namespace_id', config.EDDYSTONE_NAMESPACE_ID)}")

    # Pre-fill beacon_identification_state with known beacons from config
    current_time_for_init = time.time() 
    for beacon_cfg in config.SYSTEM_CONFIG["known_beacons"]:
        mac_addr = beacon_cfg.get("mac_address")
        if mac_addr:
            gs.beacon_identification_state[mac_addr] = {
                "name": beacon_cfg.get("name", "Unbekannt"),
                "is_allowed": beacon_cfg.get("is_allowed", False),
                "ibeacon_data": None,
                "uid_data": None,
                "url_data": None,
                "last_packet_time": 0, # Initial 0, wird durch Initial-Scan aktualisiert
                "is_fully_identified": False,
                "known_beacon_config": beacon_cfg, # Store full config for comparison
                "is_in_proximity_raw": False,
                "proximity_state_change_time": current_time_for_init,
                "is_in_proximity_debounced": False,
                "is_currently_inside_house": beacon_cfg.get("is_allowed", False) # NEU: Initial auf True, wenn erlaubt
            }
            # Auch beacon_last_seen_data initialisieren, um die Basis für den Initial-Scan zu schaffen
            gs.beacon_last_seen_data[mac_addr] = {
                'timestamp': 0, # Initial 0, wird durch Initial-Scan aktualisiert
                'rssi': 0,
                'distance': float('inf')
            }
    
    logging.info(f"MAIN: Bekannte Beacons zur Identifikation: {', '.join([s['name'] for s in config.SYSTEM_CONFIG['known_beacons']])}")

    # --- Dedizierter Initial-Scan beim Systemstart ---
    await ble_logic._perform_initial_beacon_scan(config.get("system_globals.initial_scan_duration_sec", config.INITIAL_SCAN_DURATION_SEC))

    # Nach dem Initial-Scan: Falsifizierung des 'is_currently_inside_house'-Status
    initial_scan_end_time = time.time()
    for mac, state in gs.beacon_identification_state.items():
        # Nur für Beacons, die als 'allowed' initial auf True gesetzt wurden
        if state["is_allowed"] and state["is_currently_inside_house"]:
            # Prüfen, ob der Beacon während des Initial-Scans gesehen wurde
            if mac not in gs.beacon_last_seen_data or \
               gs.beacon_last_seen_data[mac]['timestamp'] < (initial_scan_end_time - config.get("system_globals.initial_scan_duration_sec", config.INITIAL_SCAN_DURATION_SEC)):
                state["is_currently_inside_house"] = False
                logging.info(f"MAIN: Beacon '{state['name']}' ({mac}) wurde während des Initial-Scans nicht gesehen. 'is_currently_inside_house' auf False gesetzt.")
            else:
                logging.info(f"MAIN: Beacon '{state['name']}' ({mac}) wurde während des Initial-Scans gesehen. Bleibt 'is_currently_inside_house' auf True.")
    # --- ENDE NEU: Dedizierter Initial-Scan ---

    # Display-Hardware initialisieren
    try:
        await display_logic.init_display_hardware()
    except Exception as e:
        logging.critical(f"MAIN: Kritischer Fehler bei der Initialisierung der Display-Hardware: {e}. Das System wird ohne Display-Funktionalität fortgesetzt.", exc_info=True)
        # Setze gs.display auf None, um den display_manager_task zu signalisieren, dass er nicht laufen kann
        gs.display = None


    # Starte die asynchronen Tasks
    ble_task = asyncio.create_task(ble_logic.scan_for_ibeacons_task())
    display_task = asyncio.create_task(display_logic.display_manager_task())

    # Haupt-Loop für die Zustandsverwaltung (Debouncing für Anwesenheit/Abwesenheit)
    last_beacon_state_change_time = time.time()
    current_beacon_state_raw = False # True, wenn irgendein relevanter Beacon gerade gesehen wird

    try:
        while True:
            current_time = time.time()
            
            # Cleanup/Timeout for identification state (copied from Beacon_Identifier_Test.py)
            beacons_to_remove = []
            for mac, state in gs.beacon_identification_state.items():
                # NEU: Timeout für 'is_currently_inside_house'
                if state["is_currently_inside_house"] and \
                   (current_time - state['last_packet_time']) > config.get("system_globals.beacon_absence_timeout_for_home_status_sec", config.BEACON_ABSENCE_TIMEOUT_FOR_HOME_STATUS_SEC):
                    state["is_currently_inside_house"] = False
                    logging.info(f"MAIN: Beacon '{state['name']}' ({mac}) hat Timeout für 'is_currently_inside_house' überschritten. Status auf False gesetzt.")

                # Standard Identifikations-Timeout
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
                    # Auch aus beacon_last_seen_data entfernen
                    if mac in gs.beacon_last_seen_data:
                        del gs.beacon_last_seen_data[mac]

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
                        "is_currently_inside_house": False # NEU: Initialisierung auf False bei Re-Initialisierung nach Timeout
                    }
                    # beacon_last_seen_data ebenfalls neu initialisieren
                    gs.beacon_last_seen_data[mac] = {
                        'timestamp': current_time,
                        'rssi': 0,
                        'distance': float('inf')
                    }


            # --- Logik für Distanz-Debouncing und Türöffnung ---
            for mac, state in gs.beacon_identification_state.items():
                # 1. Proximity-Status für jeden Beacon aktualisieren
                beacon_data = gs.beacon_last_seen_data.get(mac)
                # Annahme: Wenn keine Daten vorhanden oder Distanz -1.0, ist der Beacon nicht nah genug.
                current_distance = beacon_data['distance'] if beacon_data else float('inf')

                # Roh-Proximity-Status basierend auf Distanz-Schwellenwert bestimmen
                current_is_in_proximity_raw = (current_distance != -1.0 and current_distance <= config.get("system_globals.proximity_distance_threshold", config.PROXIMITY_DISTANCE_THRESHOLD))

                # Roh-Proximity-Status und Änderungszeitpunkt aktualisieren
                if current_is_in_proximity_raw != state['is_in_proximity_raw']:
                    state['is_in_proximity_raw'] = current_is_in_proximity_raw
                    state['proximity_state_change_time'] = current_time
                    logging.debug(f"MAIN: Proximity Roh-Status geändert für {state['name']} ({mac}): {current_is_in_proximity_raw}")

                # Debouncing für den debounced Proximity-Status anwenden
                if current_is_in_proximity_raw and not state['is_in_proximity_debounced']:
                    if (current_time - state['proximity_state_change_time']) >= config.get("system_globals.presence_detection_time", config.PRESENCE_DETECTION_TIME):
                        state['is_in_proximity_debounced'] = True
                        logging.info(f"MAIN: Beacon '{state['name']}' ({mac}) STABIL NAH GENUG.")
                elif not current_is_in_proximity_raw and state['is_in_proximity_debounced']:
                    if (current_time - state['proximity_state_change_time']) >= config.get("system_globals.absence_detection_time", config.ABSENCE_DETECTION_TIME):
                        state['is_in_proximity_debounced'] = False
                        logging.info(f"MAIN: Beacon '{state['name']}' ({mac}) STABIL NICHT MEHR NAH GENUG.")

                # 2. Bedingung für Türöffnung prüfen
                # Türöffnung nur, wenn vollständig identifiziert, erlaubt, nah genug (debounced), NICHT bereits im Haus UND Cooldown vorbei
                if state['is_fully_identified'] and \
                   state['is_allowed'] and \
                   state['is_in_proximity_debounced'] and \
                   not state['is_currently_inside_house'] and \
                   (current_time - gs.last_door_opened_timestamp) > config.get("system_globals.force_beacon_absence_duration_sec", config.FORCE_BEACON_ABSENCE_DURATION_SEC):

                    logging.info(f"MAIN: Berechtigter Beacon '{state['name']}' ({mac}) vollständig identifiziert, nah genug UND nicht im Haus. Öffne Tür.")
                    await door_control.send_door_open_command(config.get("system_globals.relay_activation_duration_sec", config.RELAY_ACTIVATION_DURATION_SEC))
                    await gs.display_status_queue.put({"type": "status", "value": "ACCESS_GRANTED", "duration": 5})

                    gs.last_door_opened_timestamp = current_time # Cooldown für Türöffnung starten
                    state['is_currently_inside_house'] = True # NEU: Beacon als "im Haus" markieren nach erfolgreicher Öffnung

                    # Identifikations- und Proximity-Status für diesen Beacon zurücksetzen,
                    # um sofortiges erneutes Auslösen zu verhindern und einen neuen Zyklus zu erzwingen.
                    # 'is_currently_inside_house' bleibt True, bis es lange genug abwesend ist.
                    gs.beacon_identification_state[mac] = {
                        "name": state["name"],
                        "is_allowed": state["is_allowed"],
                        "ibeacon_data": None,
                        "uid_data": None,
                        "url_data": None,
                        "last_packet_time": current_time,
                        "is_fully_identified": False,
                        "known_beacon_config": state["known_beacon_config"],
                        "is_in_proximity_raw": False, # Proximity-Status zurücksetzen
                        "proximity_state_change_time": current_time,
                        "is_in_proximity_debounced": False,
                        "is_currently_inside_house": True # Bleibt True, da die Person gerade eingetreten ist
                    }
                    # Hier ist kein 'break' nötig, da der Cooldown weitere Öffnungen durch andere Beacons verhindert.

            # --- ENDE Logik für Distanz-Debouncing und Türöffnung ---

            # Debouncing for overall beacon presence (for display logic, etc.)
            # This logic might need refinement if multiple beacons are present and some leave.
            # For now, it means "at least one relevant beacon is present".
            active_known_beacons_in_range = [
                mac for mac, state in gs.beacon_identification_state.items()
                if current_time - state['last_packet_time'] < config.get("system_globals.absence_detection_time", config.ABSENCE_DETECTION_TIME)
            ]
            current_beacon_state_raw = len(active_known_beacons_in_range) > 0

            # Apply debouncing for beacon_is_present
            if current_beacon_state_raw and not gs.beacon_is_present:
                if (current_time - last_beacon_state_change_time) >= config.get("system_globals.presence_detection_time", config.PRESENCE_DETECTION_TIME):
                    gs.beacon_is_present = True
                    logging.info(f"MAIN: *** BEACON STABIL ANWESEND. ***")
            elif not current_beacon_state_raw and gs.beacon_is_present:
                if (current_time - last_beacon_state_change_time) >= config.get("system_globals.absence_detection_time", config.ABSENCE_DETECTION_TIME):
                    gs.beacon_is_present = False
                    logging.info(f"MAIN: --- BEACON STABIL ABWESEND. ---")

            # Enforce beacon absence after door opened (cooldown)
            if (current_time - gs.last_door_opened_timestamp) < config.get("system_globals.force_beacon_absence_duration_sec", config.FORCE_BEACON_ABSENCE_DURATION_SEC):
                if gs.beacon_is_present:
                    logging.info(f"MAIN: Erzwinge Beacon-Abwesenheit für {config.get('system_globals.force_beacon_absence_duration_sec', config.FORCE_BEACON_ABSENCE_DURATION_SEC)}s (Cooldown nach Türöffnung).")
                gs.beacon_is_present = False # Force to false during cooldown

            await asyncio.sleep(0.5) # Kurze Pause für den Haupt-Loop

    except asyncio.CancelledError:
        logging.info("MAIN: System-Tasks werden beendet.")
    except Exception as e:
        logging.critical(f"MAIN: Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        # Sicherstellen, dass alle Tasks abgebrochen und Ressourcen freigegeben werden
        logging.info("MAIN: Starte Cleanup der Asyncio-Tasks...")
        ble_task.cancel()
        display_task.cancel()
        
        # Corrected: Wait for tasks to actually complete cancellation
        try:
            await asyncio.gather(ble_task, display_task, return_exceptions=True)
            logging.info("MAIN: Alle Asyncio-Tasks beendet.")
        except asyncio.CancelledError:
            logging.info("MAIN: Asyncio-Tasks erfolgreich abgebrochen.")
        except Exception as e:
            logging.error(f"MAIN: Fehler beim Beenden der Asyncio-Tasks: {e}")

        # Final cleanup actions
        logging.info("MAIN: Alle System-Tasks beendet.")

# --- Hauptausführung ---
if __name__ == "__main__":
    multiprocessing.set_start_method('spawn', True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("MAIN: Programm beendet durch Benutzer (Strg+C).")
    except Exception as e:
        logging.critical(f"MAIN: Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        # cleanup_gpio() is registered with atexit and will be called automatically.
        logging.info("MAIN: Programm beendet.")
        