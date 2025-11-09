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
# Modified: November 08, 2025, 15:59 UTC - Hardware-Abstraktion (SENSOR_TYPE Variable) und bedingten Import (LD2450/RD03D) eingeführt.
# Modified: November 08, 2025, 20:57 UTC - Umbau auf Trendanalyse (N-Frame-Historie) statt 2-Punkt-Vergleich zur Behebung des Kalt/Heiß-Drift-Problems. (Entfernt: _is_approaching_target, last_target_state, Y_TOLERANCE_MM, get_sign).

import asyncio
import time
import logging
from collections import deque
import numpy as np

import config # MUSS vor dem bedingten Import geladen werden (Logging-Init)
import globals_state as gs
import ble_logic_R
import door_control
# from rd03d_async import RD03D_Async, Target # ALTE Zeile

# --- NEU: Hardware-Abstraktion (Hardcoded Variable) ---
# HIER den Sensor-Typ manuell festlegen (z.B. "LD2450" oder "RD03D")
SENSOR_TYPE = "RD03D" # Default auf RD03D gesetzt, wie besprochen
    
log = logging.getLogger(__name__) # Logger hier initialisieren

if SENSOR_TYPE == "LD2450":
    try:
        from ld2450_async import LD2450_Async as RadarDriverClass
        from ld2450_async import Target # Target direkt importieren
        log.info("Radar-Treiber: LD2450 geladen.")
    except ImportError:
        log.critical("Radar-Treiber: LD2450 nicht gefunden! Fallback auf RD03D.")
        from rd03d_async import RD03D_Async as RadarDriverClass
        from rd03d_async import Target # Target direkt importieren
        SENSOR_TYPE = "RD03D"
else:
    from rd03d_async import RD03D_Async as RadarDriverClass
    from rd03d_async import Target # Target direkt importieren
    log.info("Radar-Treiber: RD03D geladen.")
# --- Ende Hardware-Abstraktion ---


# --- Hardcoded Konstanten ---
RADAR_LOOP_DELAY = 0.05  # Sekunden Pause zwischen den Radar-Schleifendurchläufen
BAUDRATE = 256000        # Baudrate für den RD03D Sensor (wird von LD2450 ignoriert, da dort hardcoded)
# Y_TOLERANCE_MM = 50    # ENTFERNT (Genehmigt): Wird durch Trendanalyse ersetzt.

HISTORY_SIZE = 7         # NEU: Anzahl der Frames für die Trendanalyse (N=7)

# Schwellenwerte für X=0 Vorzeichenwechsel-Validierung (Bleibt erhalten)
SIGN_CHANGE_Y_MAX = 500  # mm - Maximale Y-Distanz für gültigen Vorzeichenwechsel
SIGN_CHANGE_X_MAX = 700  # mm - Maximaler |X|-Wert für gültigen Vorzeichenwechsel bei X=0

# NEU: Schwellenwert für Diagnose-Logging (Phase 3.1)
DIAGNOSTIC_LOG_Y_THRESHOLD = 2200 # mm - Ablehnungen unterhalb dieser Distanz werden als DEBUG geloggt, darüber als TRACE.

# --- Modul-globale Variable für Radar-Instanz ---
_radar_device: RadarDriverClass = None # NEU: Nutzt den generischen Typ

# --- ENTFERNT (Genehmigt): get_sign ---
# def get_sign(x): ...

async def init_radar_hardware():
    """
    Initialisiert die Radar-Hardware und stellt die Verbindung her.
    """
    global _radar_device
    log.info(f"Initialisiere Radar-Hardware (Typ: {SENSOR_TYPE})...") # NEU: Typ im Log
    
    uart_port = config.get("radar_config.uart_port", "/dev/ttyAMA2") 
    
    # NEU: Verwendet die oben importierte Klasse
    _radar_device = RadarDriverClass(uart_port)
    
    # NEU: Einheitlicher Aufruf.
    # RD03D_Async.connect() hat jetzt Default multi_mode=False
    # LD2450_Async.connect() ignoriert den Parameter und erzwingt Single-Target
    connected = await _radar_device.connect() 
    
    if not connected:
        log.critical("Fehler bei der Radar-Hardware-Initialisierung. System kann nicht starten.")
        raise RuntimeError("Radar-Hardware konnte nicht initialisiert werden.")
    
    log.info(f"Radar-Hardware ({SENSOR_TYPE}) erfolgreich initialisiert und im Single-Target-Modus.")

# --- ENTFERNT (Genehmigt): _is_approaching_target ---
# def _is_approaching_target(target: Target, last_target_state: dict) -> (bool, str): ...

def _analyze_trajectory(history: deque, expected_sign: str, noise_threshold_cm_s: float) -> str:
    """
    Führt eine holistische Trendanalyse (Block A) über die Historie (N Frames) durch.
    Gibt den erkannten Zustand zurück: "COMING", "LEAVING" oder "NEUTRAL".
    Ignoriert den unzuverlässigen gemessenen 'speed'-Wert komplett.
    """
    
    # 1. Daten für Regression extrahieren
    # Wir verwenden Tupel (timestamp, x, y)
    try:
        timestamps = np.array([entry[0] for entry in history])
        y_positions = np.array([entry[2] for entry in history])
        x_positions = np.array([entry[1] for entry in history])
    except IndexError:
        log.warning("_analyze_trajectory: Historie scheint korrupt oder leer.")
        return "NEUTRAL"

    # 2. Y-Trend (Geschwindigkeit) berechnen
    # Zeit normalisieren (verhindert numerische Instabilität bei großen Zeitstempeln)
    timestamps_norm = timestamps - timestamps[0]
    
    # np.polyfit(grad=1) ist eine lineare Regression. [0] ist die Steigung (m).
    # Das Ergebnis ist in [mm / Sekunde], da Y in mm und Zeit in Sekunden ist.
    try:
        y_slope_mm_per_sec = np.polyfit(timestamps_norm, y_positions, 1)[0]
    except np.linalg.LinAlgError:
        log.warning("_analyze_trajectory: Lineare Regression fehlgeschlagen (LinAlgError).")
        return "NEUTRAL"

    # Schwellenwert von cm/s in mm/s umrechnen
    noise_threshold_mm_per_sec = noise_threshold_cm_s * 10.0

    # 3. X-Trend (Seite) berechnen
    avg_x = np.mean(x_positions)

    # 4. Holistische Analyse (Kommen vs. Gehen)
    
    # Fall 1: Signifikante Annäherung (Trend ist negativer als Rauschen)
    if y_slope_mm_per_sec < -noise_threshold_mm_per_sec:
        # Prüfe X-Richtung
        if (expected_sign == "positive" and avg_x > 0) or \
           (expected_sign == "negative" and avg_x < 0):
            return "COMING"
        else:
            # Nähert sich, aber von der falschen Seite (Haus-Innenseite)
            return "LEAVING"
            
    # Fall 2: Signifikante Entfernung (Trend ist positiver als Rauschen)
    elif y_slope_mm_per_sec > noise_threshold_mm_per_sec:
        return "LEAVING"
        
    # Fall 3: Rauschen/Stillstand/Drift (Trend ist innerhalb der Rauschgrenze)
    else:
        return "NEUTRAL"


async def radar_master_task():
    """
    Implementiert die Master-Logik (State Machine) basierend auf holistischer Trendanalyse.
    """
    global _radar_device
    if _radar_device is None:
        log.critical("radar_master_task kann nicht gestartet werden, Radar-Hardware nicht initialisiert.")
        return

    log.info("Starte Radar-Master-Task (Version: Trendanalyse).")

    # --- Interne Zustandsvariablen ---
    ble_identification_task: asyncio.Task = None
    ble_identification_result: bool = None
    # last_target_state: dict = None  # ERSETZT (Genehmigt)
    cooldown_active_until: float = 0.0
    x_sign_changed: bool = False  # Für Test-Display

    # NEU: Zustandsvariablen für Trendanalyse
    # "Rollierende" Historie (speichert Tupel: (timestamp, x, y))
    target_history = deque(maxlen=HISTORY_SIZE) 
    # Startzustand der State Machine
    current_tracking_state = "IDLE" 

    try:
        while True:
            current_time = time.time()

            # --- Cooldown-Prüfung ---
            if current_time < cooldown_active_until:
                await _radar_device.update_async() # Puffer weiterlesen
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue

            # Radardaten lesen
            updated = await _radar_device.update_async()
            target: Target = _radar_device.get_target(1)
            
            # --- Target Handling ---
            if target is None:
                # Target verloren
                if current_tracking_state != "IDLE":
                    log.debug(f"Target verloren. Status wechselt zu IDLE. (BLE-Ergebnis: {ble_identification_result} bleibt erhalten)")
                    current_tracking_state = "IDLE"
                
                # HINWEIS: target_history wird *nicht* geleert, damit der "akute" X-Check (Block B)
                # bei kurzem Jitter (1-2 Frames Verlust) robust bleibt und auf history[-1] zugreifen kann.
                # (Ein Timer zum Zurücksetzen von ble_identification_result ist hier noch nicht implementiert)
            
            else:
                # Target vorhanden
                # Füge Tupel (timestamp, x, y) zur Historie hinzu
                target_history.append((current_time, target.x, target.y))
                
                # Test-Display: Y-Distanz senden (nutze das akute Target)
                if gs.TEST_DISPLAY_MODE:
                    await gs.display_test_queue.put({
                        "y_distance": target.y,
                        "x_sign_changed": x_sign_changed
                    })


            # --- Block B: Türöffnungs-Trigger (AKUT) ---
            # (Diese Logik muss VOR Block A bleiben, um sofort auf den X-Wechsel zu reagieren,
            # auch wenn der Trend-Status noch nicht aktualisiert wurde)
            if ble_identification_result is True:
                # Wir brauchen mind. 2 Punkte in der Historie für einen "akuten" Vergleich
                if len(target_history) >= 2:
                    
                    # Hole die letzten beiden Frames für den akuten X-Check
                    current_entry = target_history[-1] # (time, x, y)
                    prev_entry = target_history[-2]    # (time, x, y)
                    
                    current_x = current_entry[1]
                    current_y = current_entry[2] # Y-Position des aktuellen Frames
                    prev_x = prev_entry[1]
                    
                    log.debug(f"Vorzeichenwechsel-Check: prev_x={prev_x}, current_x={current_x}, y={current_y}")
                    
                    valid_sign_change_detected = False
                    
                    # Fall 1: X=0 mit Validierung (Logik 1:1 übernommen)
                    if current_x == 0:
                        if not (current_y > SIGN_CHANGE_Y_MAX or abs(prev_x) > SIGN_CHANGE_X_MAX):
                            expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
                            if (expected_x_sign == "negative" and prev_x < 0 and prev_x > -SIGN_CHANGE_X_MAX) or \
                               (expected_x_sign == "positive" and prev_x > 0 and prev_x < SIGN_CHANGE_X_MAX):
                                valid_sign_change_detected = True
                                log.info(f"X-Vorzeichenwechsel erkannt (von {prev_x} zu 0, y={current_y}mm). Türöffnungszeitpunkt erreicht.")
                            else:
                                log.debug(f"X=0 verworfen (prev_x={prev_x}). Falsche Richtung (expected: {expected_x_sign}).")
                        else:
                            log.debug(f"X=0 verworfen (prev_x={prev_x}, y={current_y}mm). Schwellenwerte überschritten.")
                    
                    # Fall 2: Echter +/- Wechsel (Logik 1:1 übernommen)
                    elif prev_x * current_x < 0:
                        valid_sign_change_detected = True
                        log.info(f"X-Vorzeichenwechsel erkannt (von {prev_x} zu {current_x}, y={current_y}mm). Türöffnungszeitpunkt erreicht.")
                    
                    if valid_sign_change_detected:
                        x_sign_changed = True # (Für Test-Display)
                        
                        # (Restliche Logik 1:1 übernommen)
                        comfort_delay = config.get("radar_config.door_open_comfort_delay", 0.5)
                        if comfort_delay > 0:
                            await asyncio.sleep(comfort_delay)
                        
                        relay_duration = config.get("system_globals.relay_activation_duration_sec", 4)
                        await door_control.send_door_open_command(relay_duration)
                        await gs.display_status_queue.put({"type": "status", "value": "ACCESS_GRANTED", "duration": 5})
                        
                        gs.last_door_opened_timestamp = current_time
                        cooldown_duration = config.get("radar_config.cooldown_duration", 3.0)
                        cooldown_active_until = current_time + cooldown_duration
                        
                        log.info("Tür geöffnet und Cooldown gestartet.")
                        
                        # Zustände für den nächsten Zyklus zurücksetzen
                        ble_identification_result = None
                        target_history.clear() # NEU: Historie leeren
                        current_tracking_state = "IDLE" # NEU: Status zurücksetzen
                        x_sign_changed = False
                        
                        if ble_identification_task and not ble_identification_task.done():
                            ble_identification_task.cancel()
                        ble_identification_task = None
                        
                        await asyncio.sleep(RADAR_LOOP_DELAY)
                        continue


            # --- Block A: BLE-Scan-Trigger (TRENDANALYSE) ---
            
            # Wir benötigen eine volle Historie für eine stabile Trendanalyse
            if len(target_history) < HISTORY_SIZE:
                log.trace(f"Warte auf volle Historie ({len(target_history)}/{HISTORY_SIZE} Frames)...")
                await asyncio.sleep(RADAR_LOOP_DELAY)
                continue

            # --- Historie ist voll (N=HISTORY_SIZE) ---
            
            # 1. Parameter holen
            noise_threshold = config.get("radar_config.speed_noise_threshold", 5)
            expected_x_sign = config.get("radar_config.expected_x_sign", "negative")

            # 2. Trend analysieren (Block A)
            new_state = _analyze_trajectory(target_history, expected_x_sign, noise_threshold)

            # 3. State Machine (Zustandsübergänge)
            if new_state != "NEUTRAL":
                # Nur bei echter Bewegungsänderung Status wechseln
                if new_state != current_tracking_state:
                    log.info(f"Tracking-Status: {current_tracking_state} -> {new_state}")
                    current_tracking_state = new_state
                    
                    if new_state == "LEAVING":
                        # Wenn wir "Gehen" erkennen, Scan abbrechen und Ergebnis verwerfen
                        if ble_identification_task and not ble_identification_task.done():
                            log.info("Status 'LEAVING' erkannt, breche laufenden BLE-Scan ab.")
                            ble_identification_task.cancel()
                        ble_identification_result = None # Wichtig!
            
            # 4. Aktionen basierend auf Zustand (BLE-Scan)
            if current_tracking_state == "COMING":
                # Nur starten, wenn noch kein Task läuft UND noch kein Ergebnis vorliegt
                if (ble_identification_task is None) and (ble_identification_result is None):
                    ble_scan_max_duration = config.get("radar_config.ble_scan_max_duration", 1.5)
                    ble_identification_task = asyncio.create_task(
                        ble_logic_R.perform_on_demand_identification(ble_scan_max_duration)
                    )
                    log.info("Status 'COMING' erkannt. Starte BLE-Scan im Hintergrund.")
                
                # Prüfe, ob der Hintergrund-BLE-Scan abgeschlossen ist
                if ble_identification_task and ble_identification_task.done():
                    try:
                        ble_identification_result = ble_identification_task.result()
                        ble_identification_task = None
                        if ble_identification_result:
                            log.info("BLE-Identifikation erfolgreich.")
                        else:
                            log.info("BLE-Identifikation fehlgeschlagen (Timeout oder kein Beacon).")
                            # Setze Status zurück, damit bei nächster "COMING"-Erkennung neu gescannt wird
                            current_tracking_state = "IDLE" 
                    except asyncio.CancelledError:
                        log.info("BLE-Scan-Task wurde abgebrochen (z.B. durch 'LEAVING').")
                        ble_identification_result = False
                        ble_identification_task = None
                    except Exception as e:
                        log.error(f"Fehler im BLE-Scan-Task: {e}", exc_info=True)
                        ble_identification_result = False
                        ble_identification_task = None

            # --- (Alte Logik für _is_approaching_target und last_target_state ist entfernt) ---

            await asyncio.sleep(RADAR_LOOP_DELAY)

    except asyncio.CancelledError:
        log.info("Radar-Master-Task abgebrochen.")
    except Exception as e:
        log.critical(f"Kritischer Fehler im Radar-Master-Task: {e}", exc_info=True)
    finally:
        if _radar_device:
            await _radar_device.close()
        log.info("Radar-Master-Task beendet und Radar-Verbindung geschlossen.")