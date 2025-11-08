# Program: radar_logic.py
# Purpose: Implementiert die Master-Logik für die Bewegungserkennung, BLE-Identifikation und Türöffnungsentscheidung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 11:45 UTC - Korrektur des Zugriffs auf UART_PORT Fallback-Wert.
# Modified: October 17, 2025, 12:45 UTC - Hinzufügen von Debug-Meldungen zur besseren Verfolgung des Datenflusses.
# Modified: October 17, 2025, 14:10 UTC - Korrektur der config.get() Fallback-Werte.
# Modified: October 19, 2025, 22:30 UTC - Radikale Vereinfachung der Logik: Speed-Checks entfernt, _is_approaching_target() eingeführt, min_distance-Prüfung entfernt, BLE-Scan-Start-Bedingung korrigiert, Logging verbessert.
# Modified: October 19, 2025, 23:00 UTC - Debug-Logs hinzugefügt für Fehlersuche bei Vorzeichenwechsel-Erkennung, >= zu > geändert in _is_approaching_target().
# Modified: October 19, 2025, 23:45 UTC - Reihenfolge im Loop korrigiert: Türöffnungs-Check VOR Target-Verlust-Check, damit Vorzeichenwechsel nicht zum Reset führt.
# Modified: October 26, 2025, 12:30 UTC - Korrektur: ble_identification_result wird bei Target-Verlust nicht mehr zurückgesetzt, wenn bereits erfolgreich. Verhindert Mehrfach-BLE-Scans und behält erfolgreiche Identifikation bei intermittierenden Radar-Daten.
# Modified: October 26, 2025, 13:15 UTC - Y-Toleranz (50mm) eingeführt, um Radar-Messschwankungen zu kompensieren und "holpriges" Target-Tracking zu verhindern.
# Modified: October 26, 2025, 14:15 UTC - Test-Display-Integration: Senden von Y-Distanz und X-Vorzeichenwechsel-Status an display_test_queue für Progressbar-Visualisierung.
# Modified: November 02, 2025, 13:30 UTC - X=0 Vorzeichenwechsel-Validierung: Y-Schwellenwert (500mm) und X-Schwellenwert (700mm) hinzugefügt zur Filterung von Radar-Rauschen bei großen Distanzen.
# Modified: November 02, 2025, 19:12 UTC - _is_approaching_target() implementiert Doku-Logik (Speed < 0 ODER Y nimmt ab) zur Rauschfilterung.
# Modified: November 07, 2025, 13:25 UTC - Logging-Refactor: Benannter Logger, Präfixe entfernt, _is_approaching_target gibt Reason zurück, distanzabhängiges Diagnose-Logging implementiert.

import asyncio
import time
import logging

import config
import globals_state as gs
import ble_logic_R
import door_control
from rd03d_async import RD03D_Async, Target

# NEU: Benannter Logger (Phase 3.1)
log = logging.getLogger(__name__)

# --- Hardcoded Konstanten ---
RADAR_LOOP_DELAY = 0.05  # Sekunden Pause zwischen den Radar-Schleifendurchläufen
BAUDRATE = 256000        # Baudrate für den RD03D Sensor
Y_TOLERANCE_MM = 50      # Toleranz für Y-Schwankungen (mm) - verhindert false "Target verloren" bei Messschwankungen

# Schwellenwerte für X=0 Vorzeichenwechsel-Validierung
SIGN_CHANGE_Y_MAX = 500  # mm - Maximale Y-Distanz für gültigen Vorzeichenwechsel
SIGN_CHANGE_X_MAX = 700  # mm - Maximaler |X|-Wert für gültigen Vorzeichenwechsel bei X=0

# NEU: Schwellenwert für Diagnose-Logging (Phase 3.1)
DIAGNOSTIC_LOG_Y_THRESHOLD = 2200 # mm - Ablehnungen unterhalb dieser Distanz werden als DEBUG geloggt, darüber als TRACE.

# --- Modul-globale Variable für Radar-Instanz ---
_radar_device: RD03D_Async = None

def get_sign(x):
    """
    Gibt das Vorzeichen einer Zahl zurück:
    1 für positive Zahlen, -1 für negative Zahlen, 0 für Null.
    """
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0


async def init_radar_hardware():
    """
    Initialisiert die Radar-Hardware und stellt die Verbindung her.
    """
    global _radar_device
    log.info("Initialisiere Radar-Hardware...")
    
    uart_port = config.get("radar_config.uart_port", "/dev/ttyAMA2") 
    _radar_device = RD03D_Async(uart_port)
    
    # Verbindung herstellen und Modus setzen (Single-Target-Modus)
    connected = await _radar_device.connect(multi_mode=False) 
    
    if not connected:
        log.critical("Fehler bei der Radar-Hardware-Initialisierung. System kann nicht starten.")
        raise RuntimeError("Radar-Hardware konnte nicht initialisiert werden.")
    
    log.info("Radar-Hardware erfolgreich initialisiert und im Single-Target-Modus.")

def _is_approaching_target(target: Target, last_target_state: dict) -> (bool, str):
    """
    Prüft, ob ein Target relevant ist UND sich nähert.
    Vereint alle notwendigen Checks in einer Funktion.
    
    Gibt (bool is_approaching, str rejection_reason) zurück.
    rejection_reason ist None bei Erfolg.
    """
    # 1. Target existiert?
    if target is None:
        return (False, "Target ist None")
    
    # 2. X-Richtung gemäß Config (Person KOMMT von der richtigen Seite)
    expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
    if expected_x_sign == "negative" and target.x >= 0:
        return (False, f"Target (x={target.x}) nicht negativ (erwartet).")
    if expected_x_sign == "positive" and target.x <= 0:
        return (False, f"Target (x={target.x}) nicht positiv (erwartet).")
    
    # 3. Annäherung: Implementierung der ODER-Logik (Speed ODER Distanz)
    # (gemäß Doku Level 1, 5.2.2 und Level 3, 89)
    
    # Kriterium A: Annäherung durch Geschwindigkeit (funktioniert auch bei 'last_target_state is None')
    # (Doku Level 3, 89: "target.speed < 0 (Objekt bewegt sich auf den Sensor zu, gemäß rd03d_async Konvention)")
    approaching_by_speed = (target.speed < 0)

    # Kriterium B: Annäherung durch Distanz (nur prüfbar, wenn 'last_target_state' existiert)
    approaching_by_distance = False
    
    if last_target_state is not None:
        # Wir haben einen Referenzwert, wir können Distanz prüfen
        if target.y < (last_target_state['y'] - Y_TOLERANCE_MM):
            # Y nimmt signifikant ab
            approaching_by_distance = True
        elif target.y > (last_target_state['y'] + Y_TOLERANCE_MM):
            # Y nimmt SIGNIFIKANT zu (mehr als Toleranz) → entfernt sich wirklich
            return (False, f"Y nimmt signifikant zu (aktuell={target.y}, vorher={last_target_state['y']}, Toleranz={Y_TOLERANCE_MM}mm).")
    
    # Finale Entscheidung: (A ODER B)
    if approaching_by_speed or approaching_by_distance:
        return (True, None) # Erfolg
    else:
        # Weder Speed noch Distanz zeigen eine Annäherung (z.B. speed=0 und Y ändert sich nicht)
        return (False, f"Hat korrekte X-Richtung (x={target.x}), nähert sich aber nicht (speed={target.speed}, y={target.y}).")


async def radar_master_task():
    """
    Implementiert die Master-Logik für die Bewegungserkennung, BLE-Identifikation und Türöffnungsentscheidung.
    """
    global _radar_device
    if _radar_device is None:
        log.critical("radar_master_task kann nicht gestartet werden, Radar-Hardware nicht initialisiert.")
        return

    log.info("Starte Radar-Master-Task.")

    # --- Interne Zustandsvariablen ---
    ble_identification_task: asyncio.Task = None
    ble_identification_result: bool = None
    last_target_state: dict = None  # {'y': ..., 'x': ..., 'angle': ..., 'speed': ...}
    cooldown_active_until: float = 0.0
    x_sign_changed: bool = False  # Für Test-Display: Hat X Vorzeichen gewechselt?

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
                log.trace("update_async: Keine neuen gültigen Radar-Frames gefunden.")

            # Relevantestes Target finden (im Single-Target-Modus ist es immer Target 1)
            target: Target = _radar_device.get_target(1)
            
            # --- Test-Display: Y-Distanz senden ---
            if gs.TEST_DISPLAY_MODE and target is not None:
                await gs.display_test_queue.put({
                    "y_distance": target.y,
                    "x_sign_changed": x_sign_changed
                })

            # --- ZUERST: Türöffnung prüfen (VOR dem Target-Verlust-Check!) ---
            if ble_identification_result is True:
                log.debug(f"Prüfe Türöffnung. ble_result={ble_identification_result}, last_target_state={'vorhanden' if last_target_state else 'None'}")
            
                # Vorzeichenwechsel von X prüfen
                if last_target_state and target is not None:
                    prev_x = last_target_state['x']
                    current_x = target.x
                    
                    log.debug(f"Vorzeichenwechsel-Check: prev_x={prev_x}, current_x={current_x}, Produkt={prev_x * current_x}")
                    
                    valid_sign_change_detected = False
                    
                    # Fall 1: X=0 mit Validierung
                    if current_x == 0:
                        if not (target.y > SIGN_CHANGE_Y_MAX or abs(prev_x) > SIGN_CHANGE_X_MAX):
                            # Prüfe Richtung
                            expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
                            if (expected_x_sign == "negative" and prev_x < 0 and prev_x > -SIGN_CHANGE_X_MAX) or \
                               (expected_x_sign == "positive" and prev_x > 0 and prev_x < SIGN_CHANGE_X_MAX):
                                valid_sign_change_detected = True
                                log.info(f"X-Vorzeichenwechsel erkannt (von {prev_x} zu 0, y={target.y}mm). Türöffnungszeitpunkt erreicht.")
                            else:
                                log.debug(f"X=0 verworfen (prev_x={prev_x}). Falsche Richtung (expected: {expected_x_sign}).")
                        else:
                            log.debug(f"X=0 verworfen (prev_x={prev_x}, y={target.y}mm). Schwellenwerte überschritten.")
                    
                    # Fall 2: Echter +/- Wechsel
                    elif prev_x * current_x < 0:
                        valid_sign_change_detected = True
                        log.info(f"X-Vorzeichenwechsel erkannt (von {prev_x} zu {current_x}, y={target.y}mm). Türöffnungszeitpunkt erreicht.")
                    
                    if valid_sign_change_detected:
                        # Test-Display: X-Vorzeichenwechsel signalisieren
                        x_sign_changed = True
                        if gs.TEST_DISPLAY_MODE:
                            await gs.display_test_queue.put({
                                "y_distance": target.y,
                                "x_sign_changed": x_sign_changed
                            })
                        
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
                        
                        log.info("Tür geöffnet und Cooldown gestartet.")
                        
                        # Test-Display: Reset-Signal (zurück zu Standard-Display)
                        if gs.TEST_DISPLAY_MODE:
                            await gs.display_test_queue.put({
                                "y_distance": None,
                                "x_sign_changed": False
                            })
                        
                        # Zustände für den nächsten Zyklus zurücksetzen
                        ble_identification_result = None
                        last_target_state = None
                        x_sign_changed = False
                        if ble_identification_task and not ble_identification_task.done():
                            ble_identification_task.cancel()
                        ble_identification_task = None
                        
                        await asyncio.sleep(RADAR_LOOP_DELAY)
                        continue

            # --- DANN: Target-Annäherung prüfen (für BLE-Scan und Target-Tracking) ---
            
            is_approaching, rejection_reason = _is_approaching_target(target, last_target_state)

            if not is_approaching:
                # NEUE DIAGNOSE-LOGIK (distanzabhängig)
                if target and target.y < DIAGNOSTIC_LOG_Y_THRESHOLD:
                    # Das ist ein "plausibler Fehler", den wir im DEBUG-Log sehen wollen
                    log.debug(f"Target verworfen (Plausibel): {rejection_reason}")
                else:
                    # Das ist "Rauschen" (weit weg oder None), das wir nur im TRACE-Log sehen wollen
                    log.trace(f"Target verworfen (Rauschen): {rejection_reason}")
                
                # --- Original-Logik für Target-Verlust ---
                if ble_identification_task and not ble_identification_task.done():
                    ble_identification_task.cancel()
                    log.info("Target verloren. BLE-Scan abgebrochen, Zyklus wird zurückgesetzt.")
                
                ble_identification_task = None
                
                # NUR zurücksetzen, wenn BLE noch nicht erfolgreich war
                if ble_identification_result is not True:
                    ble_identification_result = None
                    log.trace("Zyklus komplett zurückgesetzt (BLE war noch nicht erfolgreich).")
                else:
                    log.trace("Target kurz verloren, aber BLE bereits erfolgreich - behalte Status bei.")
                
                last_target_state = None
                
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue

            # --- Wenn ein relevantes, annäherndes Target gefunden wurde ---
            log.debug(f"Annäherndes Target gefunden: {target}")

            # Sicherstellen, dass last_target_state initialisiert ist, wenn ein neues Target auftaucht
            if last_target_state is None:
                last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
                log.info(f"Neues Target erkannt, Zyklus startet mit: {target}")

            # --- BLE-Identifikation starten/prüfen ---
            # Nur starten, wenn noch kein Task läuft UND noch kein Ergebnis vorliegt
            if (ble_identification_task is None) and (ble_identification_result is None):
                ble_scan_max_duration = config.get("radar_config.ble_scan_max_duration", 1.5)
                ble_identification_task = asyncio.create_task(
                    ble_logic_R.perform_on_demand_identification(ble_scan_max_duration)
                )
                log.info("Annäherung erkannt. Starte BLE-Scan im Hintergrund.")
            
            # Prüfe, ob der Hintergrund-BLE-Scan abgeschlossen ist
            if ble_identification_task and ble_identification_task.done():
                try:
                    ble_identification_result = ble_identification_task.result()
                    ble_identification_task = None
                    if ble_identification_result:
                        log.info("BLE-Identifikation erfolgreich.")
                        log.debug(f"BLE erfolgreich. ble_result={ble_identification_result}, last_target_state={last_target_state}")
                    else:
                        log.info("BLE-Identifikation fehlgeschlagen.")
                except asyncio.CancelledError:
                    log.info("BLE-Scan-Task wurde abgebrochen.")
                    ble_identification_result = False
                    ble_identification_task = None
                except Exception as e:
                    log.error(f"Fehler im BLE-Scan-Task: {e}", exc_info=True)
                    ble_identification_result = False
                    ble_identification_task = None
            
            # Aktualisiere last_target_state für den nächsten Schleifendurchlauf
            log.debug(f"Loop-Ende: Aktualisiere last_target_state auf x={target.x}, y={target.y}")
            last_target_state = {'y': target.y, 'x': target.x, 'angle': target.angle, 'speed': target.speed}
            
            await asyncio.sleep(RADAR_LOOP_DELAY)

    except asyncio.CancelledError:
        log.info("Radar-Master-Task abgebrochen.")
    except Exception as e:
        log.critical(f"Kritischer Fehler im Radar-Master-Task: {e}", exc_info=True)
    finally:
        if _radar_device:
            await _radar_device.close()
        log.info("Radar-Master-Task beendet und Radar-Verbindung geschlossen.")