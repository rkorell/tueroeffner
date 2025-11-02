# Program: radar_logic.py
# Purpose: Implementiert die Master-Logik für die Bewegungserkennung, BLE-Identifikation und Türöffnungsentscheidung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 11:45 UTC - Korrektur des Zugriffs auf UART_PORT Fallback-Wert.
# Modified: October 17, 2025, 12:45 UTC - Hinzufügen von Debug-Meldungen zur besseren Verfolgung des Datenflusses.
# Modified: October 17, 2025, 14:10 UTC - Korrektur der config.get() Fallback-Werte.
# Modified: October 19, 2025, 22:30 UTC - Radikale Vereinfachung der Logik: Speed-Checks entfernt, _is_approaching_target() eingeführt, min_distance-Prüfung entfernt, BLE-Scan-Start-Bedingung korrigiert, Logging verbessert.

import asyncio
import time
import logging

import config
import globals_state as gs
import ble_logic_R
import door_control
from rd03d_async import RD03D_Async, Target

# --- Hardcoded Konstanten ---
RADAR_LOOP_DELAY = 0.05  # Sekunden Pause zwischen den Radar-Schleifendurchläufen
BAUDRATE = 256000        # Baudrate für den RD03D Sensor

# --- Modul-globale Variable für Radar-Instanz ---
_radar_device: RD03D_Async = None

async def init_radar_hardware():
    """
    Initialisiert die Radar-Hardware und stellt die Verbindung her.
    """
    global _radar_device
    logging.info("RADAR: Initialisiere Radar-Hardware...")
    
    uart_port = config.get("radar_config.uart_port", "/dev/ttyAMA2") 
    _radar_device = RD03D_Async(uart_port)
    
    # Verbindung herstellen und Modus setzen (Single-Target-Modus)
    connected = await _radar_device.connect(multi_mode=False) 
    
    if not connected:
        logging.critical("RADAR: Fehler bei der Radar-Hardware-Initialisierung. System kann nicht starten.")
        raise RuntimeError("Radar-Hardware konnte nicht initialisiert werden.")
    
    logging.info("RADAR: Radar-Hardware erfolgreich initialisiert und im Single-Target-Modus.")

def _is_approaching_target(target: Target, last_target_state: dict) -> bool:
    """
    Prüft, ob ein Target relevant ist UND sich nähert.
    Vereint alle notwendigen Checks in einer Funktion.
    
    Prüfungen:
    1. Target existiert
    2. X-Richtung gemäß Config (Person kommt von der erwarteten Seite)
    3. Y nimmt ab (Person nähert sich)
    """
    # 1. Target existiert?
    if target is None:
        logging.debug("RADAR: _is_approaching_target: Target ist None.")
        return False
    
    # 2. X-Richtung gemäß Config (Person KOMMT von der richtigen Seite)
    expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
    if expected_x_sign == "negative" and target.x >= 0:
        logging.debug(f"RADAR: _is_approaching_target: Target x={target.x} nicht negativ (erwartet).")
        return False
    if expected_x_sign == "positive" and target.x <= 0:
        logging.debug(f"RADAR: _is_approaching_target: Target x={target.x} nicht positiv (erwartet).")
        return False
    
    # 3. Annäherung: Y nimmt ab
    if last_target_state is None:
        # Erstes Target → als "approaching" werten (Zyklus beginnt)
        logging.debug("RADAR: _is_approaching_target: Erstes Target, als approaching gewertet.")
        return True
    
    if target.y > last_target_state['y']:
        # Y wird größer oder gleich → entfernt sich oder steht - RKORELL modification: >= zu > -> Gleich erzeugt ein "neues" Target bei aufeianderfolgenden Frames mit gleichem Y.
        logging.debug(f"RADAR: _is_approaching_target: Y nimmt nicht ab (aktuell={target.y}, vorher={last_target_state['y']}).")
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
    last_target_state: dict = None  # {'y': ..., 'x': ..., 'angle': ..., 'speed': ...}
    cooldown_active_until: float = 0.0

    try:
        while True:
            current_time = time.time()

            # --- Cooldown-Prüfung ---
            if current_time < cooldown_active_until:
                # Während des Cooldowns nur Radardaten lesen und Schleife pausieren
                await _radar_device.update_async()
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue

            # Radardaten lesen
            updated = await _radar_device.update_async()
            if not updated:
                logging.debug("RADAR: update_async: Keine neuen gültigen Radar-Frames gefunden.")

            # Relevantestes Target finden (im Single-Target-Modus ist es immer Target 1)
            target: Target = _radar_device.get_target(1)
            
            if not _is_approaching_target(target, last_target_state):
                logging.debug("RADAR: Kein annäherndes Target nach Filterung.")
                # Kein relevantes Target gefunden oder Target hat sich entfernt
                if ble_identification_task and not ble_identification_task.done():
                    ble_identification_task.cancel()
                    logging.info("RADAR: Target verloren. BLE-Scan abgebrochen, Zyklus wird zurückgesetzt.")
                
                ble_identification_task = None
                ble_identification_result = None
                last_target_state = None
                
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue

            # --- Wenn ein relevantes, annäherndes Target gefunden wurde ---
            logging.debug(f"RADAR: Annäherndes Target gefunden: {target}")

            # Sicherstellen, dass last_target_state initialisiert ist, wenn ein neues Target auftaucht
            if last_target_state is None:
                last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
                logging.info("RADAR: Neues Target erkannt, Zyklus startet.")

            # --- BLE-Identifikation starten/prüfen ---
            # Nur starten, wenn noch kein Task läuft UND noch kein Ergebnis vorliegt
            if (ble_identification_task is None) and (ble_identification_result is None):
                ble_scan_max_duration = config.get("radar_config.ble_scan_max_duration", 1.5)
                ble_identification_task = asyncio.create_task(
                    ble_logic_R.perform_on_demand_identification(ble_scan_max_duration)
                )
                logging.info("RADAR: Annäherung erkannt. Starte BLE-Scan im Hintergrund.")
            
            # Prüfe, ob der Hintergrund-BLE-Scan abgeschlossen ist
            if ble_identification_task and ble_identification_task.done():
                try:
                    ble_identification_result = ble_identification_task.result()
                    ble_identification_task = None
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

            # --- Türöffnung prüfen ---
            if ble_identification_result is True:
                # Vorzeichenwechsel von X prüfen
                if last_target_state:
                    prev_x = last_target_state['x']
                    current_x = target.x
                    
                    if (prev_x * current_x < 0):
                        logging.info(f"RADAR: X-Vorzeichenwechsel erkannt (von {prev_x} zu {current_x}). Türöffnungszeitpunkt erreicht.")
                        
                        # Komfort-Wartezeitraum (IMMER warten, auch wenn 0)
                        comfort_delay = config.get("radar_config.door_open_comfort_delay", 0.5)
                        if comfort_delay > 0:
                            await asyncio.sleep(comfort_delay)
                        
                        # Tür öffnen
                        relay_duration = config.get("system_globals.relay_activation_duration_sec", 4)
                        await door_control.send_door_open_command(relay_duration)
                        await gs.display_status_queue.put({"type": "status", "value": "ACCESS_GRANTED", "duration": 5})
                        
                        # Cooldown starten
                        gs.last_door_opened_timestamp = current_time
                        cooldown_duration = config.get("radar_config.cooldown_duration", 3.0)
                        cooldown_active_until = current_time + cooldown_duration
                        
                        logging.info("RADAR: Tür geöffnet und Cooldown gestartet.")
                        
                        # Zustände für den nächsten Zyklus zurücksetzen
                        ble_identification_result = None
                        last_target_state = None
                        if ble_identification_task and not ble_identification_task.done():
                            ble_identification_task.cancel()
                        ble_identification_task = None
                        
                        await asyncio.sleep(RADAR_LOOP_DELAY)
                        continue
            
            # Aktualisiere last_target_state für den nächsten Schleifendurchlauf
            last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
            
            await asyncio.sleep(RADAR_LOOP_DELAY)

    except asyncio.CancelledError:
        logging.info("RADAR: Radar-Master-Task abgebrochen.")
    except Exception as e:
        logging.critical(f"RADAR: Kritischer Fehler im Radar-Master-Task: {e}", exc_info=True)
    finally:
        if _radar_device:
            await _radar_device.close()
        logging.info("RADAR: Radar-Master-Task beendet und Radar-Verbindung geschlossen.")
