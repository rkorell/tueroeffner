# Program: radar_logic.py
# Purpose: Implementiert die Master-Logik für die Bewegungserkennung, BLE-Identifikation und Türöffnungsentscheidung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 11:45 UTC - Korrektur des Zugriffs auf UART_PORT Fallback-Wert.
# Modified: October 17, 2025, 12:45 UTC - Hinzufügen von Debug-Meldungen zur besseren Verfolgung des Datenflusses.
# Modified: October 17, 2025, 14:10 UTC - Korrektur der config.get() Fallback-Werte.

import asyncio
import time
import logging
import math # Für mögliche Berechnungen, falls nötig

import config
import globals_state as gs
import ble_logic_R
import door_control
from rd03d_async import RD03D_Async, Target # Import der asynchronen Radar-Klasse und des Target-Objekts

# --- Hardcoded Konstanten ---
RADAR_LOOP_DELAY = 0.05 # Sekunden Pause zwischen den Radar-Schleifendurchläufen
BAUDRATE = 256000       # Baudrate für den RD03D Sensor

# --- Modul-globale Variable für Radar-Instanz ---
_radar_device: RD03D_Async = None

async def init_radar_hardware():
    """
    Initialisiert die Radar-Hardware und stellt die Verbindung her.
    """
    global _radar_device
    logging.info("RADAR: Initialisiere Radar-Hardware...")
    
    # Korrektur: Fallback-Wert ist der String-Literal-Default, nicht config.UART_PORT
    uart_port = config.get("radar_config.uart_port", "/dev/ttyAMA2") 
    _radar_device = RD03D_Async(uart_port)
    
    # Verbindung herstellen und Modus setzen (Single-Target-Modus, wie besprochen)
    connected = await _radar_device.connect(multi_mode=False) 
    
    if not connected:
        logging.critical("RADAR: Fehler bei der Radar-Hardware-Initialisierung. System kann nicht starten.")
        raise RuntimeError("Radar-Hardware konnte nicht initialisiert werden.")
    
    logging.info("RADAR: Radar-Hardware erfolgreich initialisiert und im Single-Target-Modus.")

def _is_relevant_target(target: Target) -> bool:
    """
    Prüft, ob ein Target als relevant für die Erkennungslogik gilt.
    """
    if target is None:
        logging.debug("RADAR: _is_relevant_target: Target ist None.")
        return False
    
    # Filterung von statischen Objekten/Rauschen (Level 1, Punkt 5.2.1)
    # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.SPEED_NOISE_THRESHOLD
    speed_noise_threshold = config.get("radar_config.speed_noise_threshold", 5) 
    if abs(target.speed) <= speed_noise_threshold:
        logging.debug(f"RADAR: _is_relevant_target: Target {target.x}/{target.y} ignoriert (Speed {target.speed} <= {speed_noise_threshold}).")
        return False
    
    # Physikalische Reichweite des Sensors (implizite Grenze, hier als 4000mm angenommen)
    # Target.y ist die Distanz entlang der Sensorachse
    PHYSICAL_MAX_RADAR_RANGE = 4000 # mm, basierend auf Diskussion (4m)
    if target.y > PHYSICAL_MAX_RADAR_RANGE or target.y < 0: # Annahme: Y sollte positiv sein und innerhalb der max. Reichweite
        logging.debug(f"RADAR: _is_relevant_target: Target {target.x}/{target.y} ignoriert (Y out of range {target.y}).")
        return False
        
    return True

async def radar_master_task():
    """
    Implementiert die Master-Logik für die Bewegungserkennung, BLE-Identifikation und Türöffnungsentscheidung.
    """
    global _radar_device
    if _radar_device is None:
        logging.critical("RADAR: radar_master_task kann nicht gestartet werden, Radar-Hardware nicht initialisiert.")
        return

    logging.info("RADAR: Starte Radar-Master-Task.")

    # --- Interne Zustandsvariablen ---
    ble_identification_task: asyncio.Task = None
    ble_identification_result: bool = None
    last_target_state: dict = None # {'y': ..., 'x': ..., 'angle': ..., 'speed': ...}
    cooldown_active_until: float = 0.0
    min_y_reached_for_current_cycle: bool = False
    
    # --- Hardcoded Konstante für physikalische Reichweite (als obere Grenze) ---
    PHYSICAL_MAX_RADAR_RANGE = 4000 # mm, basierend auf Diskussion (4m)

    try:
        while True:
            current_time = time.time()

            # --- Cooldown-Prüfung (Level 1, Punkt 5.6) ---
            if current_time < cooldown_active_until:
                # Während des Cooldowns nur Radardaten lesen und Schleife pausieren
                await _radar_device.update_async()
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue # Nächster Schleifendurchlauf

            # Radardaten lesen
            updated = await _radar_device.update_async()
            if not updated:
                logging.debug("RADAR: update_async: Keine neuen gültigen Radar-Frames gefunden.")
                # Wenn keine neuen Daten, aber möglicherweise alte Targets noch gültig
                # Logik unten handhabt das, wenn _radar_device.targets leer ist
            else:
                logging.debug("RADAR: update_async: Gültiger Radar-Frame gefunden.")


            # Relevantestes Target finden (im Single-Target-Modus ist es immer Target 1)
            target: Target = _radar_device.get_target(1)
            
            if not _is_relevant_target(target):
                logging.debug("RADAR: Kein relevantes Target nach Filterung.")
                # Kein relevantes Target gefunden oder Target hat sich entfernt
                if ble_identification_task and not ble_identification_task.done():
                    ble_identification_task.cancel()
                    logging.debug("RADAR: Laufender BLE-Scan abgebrochen, da kein relevantes Target mehr.")
                
                ble_identification_task = None
                ble_identification_result = None
                last_target_state = None
                min_y_reached_for_current_cycle = False
                
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue # Nächster Schleifendurchlauf

            # --- Wenn ein relevantes Target gefunden wurde ---
            logging.debug(f"RADAR: Relevantes Target gefunden: {target}")

            # Sicherstellen, dass last_target_state initialisiert ist, wenn ein neues Target auftaucht
            if last_target_state is None:
                last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
                logging.debug(f"RADAR: last_target_state initialisiert mit {last_target_state}")

            # --- BLE-Identifikation starten/prüfen (Level 1, Punkt 5.2) ---
            # Annäherungskriterien (Level 1, Punkt 5.2.1, 5.2.2, 5.2.3):
            # 5.2.1: Sich aktiv bewegt (bereits durch _is_relevant_target geprüft)
            # 5.2.2: Sich auf den Sensor zubewegt (speed < 0 gemäß rd03d_async Konvention) UND Y abnehmend
            # 5.2.3: Aus der "Kommen"-Richtung (X-Koordinate Vorzeichenprüfung)
            
            is_approaching = (target.speed < 0) # speed < 0 bedeutet "auf Sensor zu"
            
            # Y-Distanz-Abnahme prüfen (nur wenn last_target_state vorhanden)
            is_y_decreasing = False
            if last_target_state and target.y < last_target_state['y']:
                is_y_decreasing = True

            # X-Koordinate für "Kommen"-Richtung
            # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.EXPECTED_X_SIGN
            expected_x_sign_str = config.get("radar_config.expected_x_sign", "negative")
            is_x_direction_correct = False
            if expected_x_sign_str == "positive" and target.x > 0:
                is_x_direction_correct = True
            elif expected_x_sign_str == "negative" and target.x < 0:
                is_x_direction_correct = True
            # Wenn expected_x_sign_str == "any" oder ungültig, ist es immer True
            elif expected_x_sign_str not in ["positive", "negative"]:
                 is_x_direction_correct = True


            logging.debug(f"RADAR: Annäherungskriterien: is_approaching={is_approaching}, is_y_decreasing={is_y_decreasing}, is_x_direction_correct={is_x_direction_correct}")

            # Wenn alle Annäherungskriterien erfüllt sind und BLE-Scan noch nicht läuft/abgeschlossen ist
            if is_approaching and is_y_decreasing and is_x_direction_correct: # Zusätzliche Bedingung: target.y < PHYSICAL_MAX_RADAR_RANGE
                if not ble_identification_task or ble_identification_task.done():
                    if ble_identification_result is not True: # Nur starten, wenn noch nicht erfolgreich identifiziert
                        # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.BLE_SCAN_MAX_DURATION
                        ble_scan_max_duration = config.get("radar_config.ble_scan_max_duration", 0.5)
                        ble_identification_task = asyncio.create_task(
                            ble_logic_R.perform_on_demand_identification(ble_scan_max_duration)
                        )
                        logging.info("RADAR: Annäherung erkannt. Starte BLE-Scan im Hintergrund.")
                
                # Prüfe, ob der Hintergrund-BLE-Scan abgeschlossen ist
                if ble_identification_task and ble_identification_task.done():
                    try:
                        ble_identification_result = ble_identification_task.result()
                        ble_identification_task = None # Task ist abgeschlossen
                        if ble_identification_result:
                            logging.info("RADAR: BLE-Identifikation erfolgreich.")
                        else:
                            logging.info("RADAR: BLE-Identifikation fehlgeschlagen.")
                    except asyncio.CancelledError:
                        logging.info("RADAR: BLE-Scan-Task wurde abgebrochen.")
                        ble_identification_result = False
                        ble_identification_task = None
                    except Exception as e:
                        logging.error(f"RADAR: Fehler im BLE-Scan-Task: {e}", exc_info=True)
                        ble_identification_result = False
                        ble_identification_task = None

            # --- Eintrittsabsicht prüfen und Tür öffnen (Level 1, Punkt 5.4 & 5.5) ---
            if ble_identification_result is True:
                # Minimalabstand Y erreicht? (Level 1, Punkt 5.4)
                # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.MIN_DISTANCE_TO_SENSOR
                min_distance_to_sensor = config.get("radar_config.min_distance_to_sensor", 200)
                if target.y < min_distance_to_sensor:
                    min_y_reached_for_current_cycle = True
                
                # Türöffnungszeitpunkt (Level 1, Punkt 5.5):
                if min_y_reached_for_current_cycle and last_target_state:
                    # Vorzeichenwechsel von X prüfen
                    prev_x = last_target_state['x']
                    current_x = target.x
                    
                    if (prev_x * current_x < 0): # Prüft, ob Vorzeichen unterschiedlich sind
                        logging.info(f"RADAR: X-Vorzeichenwechsel erkannt (von {prev_x} zu {current_x}). Türöffnungszeitpunkt erreicht.")
                        
                        # Optionaler Komfort-Wartezeitraum (Level 1, Punkt 5.5.2)
                        # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.DOOR_OPEN_COMFORT_DELAY
                        comfort_delay = config.get("radar_config.door_open_comfort_delay", 0.5)
                        if comfort_delay > 0:
                            await asyncio.sleep(comfort_delay)
                        
                        # Tür öffnen
                        relay_duration = config.get("system_globals.relay_activation_duration_sec", config.RELAY_ACTIVATION_DURATION_SEC)
                        await door_control.send_door_open_command(relay_duration)
                        await gs.display_status_queue.put({"type": "status", "value": "ACCESS_GRANTED", "duration": 5})
                        
                        # Cooldown starten (Level 1, Punkt 5.6)
                        gs.last_door_opened_timestamp = current_time # Für den Cooldown in door_control
                        # KORREKTUR: Fallback-Wert ist der Literal-Default, nicht config.COOLDOWN_DURATION
                        cooldown_duration = config.get("radar_config.cooldown_duration", 3.0)
                        cooldown_active_until = current_time + cooldown_duration
                        
                        logging.info("RADAR: Tür geöffnet und Cooldown gestartet.")
                        
                        # Zustände für den nächsten Zyklus zurücksetzen
                        ble_identification_result = None
                        last_target_state = None
                        min_y_reached_for_current_cycle = False
                        if ble_identification_task and not ble_identification_task.done():
                            ble_identification_task.cancel()
                        ble_identification_task = None
                        
                        await asyncio.sleep(RADAR_LOOP_DELAY) # Kurze Pause, bevor der Cooldown greift
                        continue # Nächster Schleifendurchlauf (wird dann vom Cooldown abgefangen)
            
            # Aktualisiere last_target_state für den nächsten Schleifendurchlauf
            last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
            
            await asyncio.sleep(RADAR_LOOP_DELAY)

    except asyncio.CancelledError:
        logging.info("RADAR: Radar-Master-Task abgebrochen.")
    except Exception as e:
        logging.critical(f"RADAR: Kritischer Fehler im Radar-Master-Task: {e}", exc_info=True)
    finally:
        if _radar_device:
            await _radar_device.close() # KORREKTUR: close() ist nicht async
        logging.info("RADAR: Radar-Master-Task beendet und Radar-Verbindung geschlossen.")