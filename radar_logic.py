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
# Modified: November 09, 2025, 13:55 UTC - Großer Umbau: Entkopplung (Queue), explizite State Machine (Enums) & korrigierter BLE-Flow.
# Modified: November 09, 2025, 13:59 UTC - Korrektur: fehlenden 'field'-Import hinzugefügt.
# Modified: November 09, 2025, 14:05 UTC - Korrektur: TypeError durch Entfernen von 'await' vor 'get_nowait()'.

import asyncio
import time
import logging
from collections import deque
import numpy as np
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional

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
RADAR_LOOP_DELAY = 0.05  # Sekunden Pause zwischen den Radar-Schleifendurchläufen (I/O-Task)
BAUDRATE = 256000        # Baudrate für den RD03D Sensor (wird von LD2450 ignoriert, da dort hardcoded)

HISTORY_SIZE = 7         # NEU: Anzahl der Frames für die Trendanalyse (N=7)

# Schwellenwerte für X=0 Vorzeichenwechsel-Validierung (Bleibt erhalten)
SIGN_CHANGE_Y_MAX = 500  # mm - Maximale Y-Distanz für gültigen Vorzeichenwechsel
SIGN_CHANGE_X_MAX = 700  # mm - Maximaler |X|-Wert für gültigen Vorzeichenwechsel bei X=0

# NEU: Schwellenwert für Diagnose-Logging (Phase 3.1)
DIAGNOSTIC_LOG_Y_THRESHOLD = 2200 # mm - Ablehnungen unterhalb dieser Distanz werden als DEBUG geloggt, darüber als TRACE.

# --- Modul-globale Variable für Radar-Instanz ---
_radar_device: RadarDriverClass = None 

# --- NEU: Explizite Zustandsdefinitionen (State Machine) ---
class SystemState(Enum):
    IDLE = auto()      # Wartet auf Objekt
    TRACKING = auto()  # Objekt wird verfolgt, BLE und Intent werden parallel geprüft
    COOLDOWN = auto()  # Tür wurde geöffnet, System pausiert

class BLEStatus(Enum):
    UNKNOWN = auto()   # Initialzustand oder nach Reset (wenn Cache verfällt, optional)
    SCANNING = auto()  # Scan-Task läuft
    SUCCESS = auto()   # Scan erfolgreich, Person ist autorisiert (gecacht)
    FAILED = auto()    # Scan fehlgeschlagen (gecacht)

class IntentStatus(Enum):
    NEUTRAL = auto()   # Zu wenig Daten oder unklare Bewegung
    KOMMEN = auto()    # Trendanalyse (Block A) signalisiert "Kommen"
    GEHEN = auto()     # Trendanalyse (Block A) signalisiert "Gehen"

@dataclass
class _RadarState:
    """Zentrale Datenstruktur zur Verwaltung des Zustands."""
    system_state: SystemState = SystemState.IDLE
    ble_status: BLEStatus = BLEStatus.UNKNOWN
    intent_status: IntentStatus = IntentStatus.NEUTRAL
    
    ble_task: Optional[asyncio.Task] = None
    cooldown_end_time: float = 0.0
    
    # Die "deque" (Historie) bleibt erhalten
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))
    x_sign_changed: bool = False # Für Test-Display

# --- NEU: Globale (modulinterne) Instanzen ---
_state = _RadarState()              # Die einzige Instanz unseres Zustands
_radar_queue = asyncio.Queue(maxsize=1) # Pipeline zwischen I/O und Logik


async def init_radar_hardware():
    """
    Initialisiert die Radar-Hardware und stellt die Verbindung her.
    (Funktion 1:1 aus Original übernommen)
    """
    global _radar_device
    log.info(f"Initialisiere Radar-Hardware (Typ: {SENSOR_TYPE})...")
    
    uart_port = config.get("radar_config.uart_port", "/dev/ttyAMA2") 
    
    _radar_device = RadarDriverClass(uart_port)
    
    connected = await _radar_device.connect() 
    
    if not connected:
        log.critical("Fehler bei der Radar-Hardware-Initialisierung. System kann nicht starten.")
        raise RuntimeError("Radar-Hardware konnte nicht initialisiert werden.")
    
    log.info(f"Radar-Hardware ({SENSOR_TYPE}) erfolgreich initialisiert und im Single-Target-Modus.")


def _analyze_trajectory(history: deque, expected_sign: str, noise_threshold_cm_s: float) -> str:
    """
    Führt eine holistische Trendanalyse (Block A) über die Historie (N Frames) durch.
    Gibt den erkannten Zustand zurück: "COMING", "LEAVING" oder "NEUTRAL".
    Ignoriert den unzuverlässigen gemessenen 'speed'-Wert komplett.
    (Funktion 1:1 aus Original übernommen)
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


async def _check_and_trigger_door() -> bool:
    """
    Prüft auf "akuten" X-Vorzeichenwechsel (Block B) und öffnet die Tür.
    Nimmt die Logik aus dem alten radar_master_task (Block B).
    Gibt True zurück, wenn die Tür geöffnet wurde.
    """
    global _state
    
    # Wir brauchen mind. 2 Punkte in der Historie für einen "akuten" Vergleich
    if len(_state.history) < 2:
        return False
            
    # Hole die letzten beiden Frames für den akuten X-Check
    current_entry = _state.history[-1] # (time, x, y)
    prev_entry = _state.history[-2]    # (time, x, y)
    
    current_x = current_entry[1]
    current_y = current_entry[2] # Y-Position des aktuellen Frames
    prev_x = prev_entry[1]
    
    log.debug(f"Block B: Vorzeichenwechsel-Check: prev_x={prev_x}, current_x={current_x}, y={current_y}")
    
    valid_sign_change_detected = False
    
    # Fall 1: X=0 mit Validierung (Logik 1:1 übernommen)
    if current_x == 0:
        if not (current_y > SIGN_CHANGE_Y_MAX or abs(prev_x) > SIGN_CHANGE_X_MAX):
            expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
            if (expected_x_sign == "negative" and prev_x < 0 and prev_x > -SIGN_CHANGE_X_MAX) or \
               (expected_x_sign == "positive" and prev_x > 0 and prev_x < SIGN_CHANGE_X_MAX):
                valid_sign_change_detected = True
                log.info(f"Block B: X-Vorzeichenwechsel erkannt (von {prev_x} zu 0, y={current_y}mm). Türöffnungszeitpunkt erreicht.")
            else:
                log.debug(f"Block B: X=0 verworfen (prev_x={prev_x}). Falsche Richtung (expected: {expected_x_sign}).")
        else:
            log.debug(f"Block B: X=0 verworfen (prev_x={prev_x}, y={current_y}mm). Schwellenwerte überschritten.")
    
    # Fall 2: Echter +/- Wechsel (Logik 1:1 übernommen)
    elif prev_x * current_x < 0:
        valid_sign_change_detected = True
        log.info(f"Block B: X-Vorzeichenwechsel erkannt (von {prev_x} zu {current_x}, y={current_y}mm). Türöffnungszeitpunkt erreicht.")
    
    if valid_sign_change_detected:
        _state.x_sign_changed = True # (Für Test-Display)
        
        # (Restliche Logik 1:1 übernommen)
        comfort_delay = config.get("radar_config.door_open_comfort_delay", 0.5)
        if comfort_delay > 0:
            await asyncio.sleep(comfort_delay)
        
        relay_duration = config.get("system_globals.relay_activation_duration_sec", 4)
        await door_control.send_door_open_command(relay_duration)
        await gs.display_status_queue.put({"type": "status", "value": "ACCESS_GRANTED", "duration": 5})
        
        gs.last_door_opened_timestamp = time.time()
        cooldown_duration = config.get("radar_config.cooldown_duration", 3.0)
        _state.cooldown_end_time = time.time() + cooldown_duration
        
        log.info("Block B: Tür geöffnet und Cooldown-Timer gesetzt.")
        return True
        
    return False


def _reset_to_idle():
    """Setzt den Zustand zurück auf IDLE, behält aber den BLE-Status (Caching)."""
    global _state
    
    _state.system_state = SystemState.IDLE
    _state.intent_status = IntentStatus.NEUTRAL
    _state.history.clear()
    _state.x_sign_changed = False
    
    # WICHTIG: _state.ble_status wird *nicht* zurückgesetzt (Caching-Prämisse)
    # WICHTIG: _state.ble_task wird *nicht* abgebrochen (Lasse ihn für Cache-Update zu Ende laufen)
    
    log.debug("State Machine Reset zu IDLE (BLE-Status bleibt erhalten).")


async def _run_ble_scan_wrapper():
    """Wrapper für den BLE-Scan-Task, um den globalen Status bei Abschluss zu setzen."""
    global _state
    
    try:
        ble_scan_max_duration = config.get("radar_config.ble_scan_max_duration", 1.5)
        log.info(f"Starte BLE-Scan (max. {ble_scan_max_duration}s)...")
        
        result = await ble_logic_R.perform_on_demand_identification(ble_scan_max_duration)
        
        if result:
            _state.ble_status = BLEStatus.SUCCESS
            log.info("BLE-Scan beendet: SUCCESS")
        else:
            _state.ble_status = BLEStatus.FAILED
            log.info("BLE-Scan beendet: FAILED")
            
    except asyncio.CancelledError:
        log.info("BLE-Scan-Wrapper abgebrochen.")
        # Setze Status auf FAILED, wenn Task extern abgebrochen wird
        _state.ble_status = BLEStatus.FAILED
    except Exception as e:
        log.error(f"Fehler im BLE-Scan-Wrapper: {e}", exc_info=True)
        _state.ble_status = BLEStatus.FAILED
    finally:
        _state.ble_task = None


# --- NEU: TASK 1 - Radar I/O (Reader Task) ---
async def radar_reader_task():
    """
    Task 1: Liest Radar-Hardware aus und legt Daten in die Queue.
    (Ersetzt den Lese-Teil des alten radar_master_task)
    """
    global _radar_device, _radar_queue
    if _radar_device is None:
        log.critical("radar_reader_task kann nicht gestartet werden, Radar-Hardware nicht initialisiert.")
        return

    log.info("Starte Radar Reader Task (I/O)...")
    try:
        while True:
            updated = await _radar_device.update_async()
            target: Target = _radar_device.get_target(1) # Target oder None
            
            try:
                # maxsize=1: Wenn die Logik (Task 2) hängt, blockiert
                # dieser Task hier, anstatt die Queue vollzumüllen.
                # Wir verwerfen alte Frames und legen nur den neuesten rein.
                if _radar_queue.full():
                    # KORREKTUR: await entfernt.
                    _radar_queue.get_nowait() # Alten Frame verwerfen
                await _radar_queue.put(target)
            except asyncio.QueueFull:
                 # Sollte durch die Logik oben nie passieren
                log.warning("Radar-Queue ist voll, verwerfe Frame.")
            
            await asyncio.sleep(RADAR_LOOP_DELAY)
    
    except asyncio.CancelledError:
        log.info("Radar Reader Task abgebrochen.")
    except Exception as e:
        log.critical(f"Kritischer Fehler im Radar Reader Task: {e}", exc_info=True)
    finally:
        if _radar_device:
            await _radar_device.close()
        log.info("Radar Reader Task beendet und Radar-Verbindung geschlossen.")


# --- NEU: TASK 2 - Radar Logik (State Machine) ---
async def radar_logic_task():
    """
    Task 2: Verarbeitet Daten aus der Queue und führt die State Machine aus.
    (Ersetzt den Logik-Teil des alten radar_master_task)
    """
    global _state, _radar_queue
    log.info("Starte Radar Logic Task (State Machine)...")

    try:
        while True:
            # 1. Warte auf nächstes Datenpaket (Target oder None)
            target = await _radar_queue.get()
            current_time = time.time()

            # --- Zustand 1: COOLDOWN ---
            if _state.system_state == SystemState.COOLDOWN:
                if current_time > _state.cooldown_end_time:
                    log.info("Cooldown beendet.")
                    _reset_to_idle()
                continue # Ignoriere alle Radar-Daten während Cooldown

            # --- Target-Handling ---
            if target is None:
                # Target verloren
                if _state.system_state == SystemState.TRACKING:
                    log.debug("Target verloren. Reset zu IDLE.")
                    _reset_to_idle()
                continue

            # --- Zustand 2: IDLE (und Target ist vorhanden) ---
            if _state.system_state == SystemState.IDLE:
                _state.system_state = SystemState.TRACKING
                log.info("Objekt erkannt. Wechsle zu TRACKING.")
                # (History wird bei Reset geleert, fängt hier neu an)

            # --- Zustand 3: TRACKING ---
            if _state.system_state == SystemState.TRACKING:
                
                # A. Daten in Historie speichern
                _state.history.append((current_time, target.x, target.y))

                # B. Test-Display-Update (Logik 1:1 übernommen)
                if gs.TEST_DISPLAY_MODE:
                    await gs.display_test_queue.put({
                        "y_distance": target.y,
                        "x_sign_changed": _state.x_sign_changed
                    })

                # C. (Parallel 1) BLE-Logik starten (falls nötig)
                # Startet, wenn Status UNKNOWN oder FAILED ist UND kein Task bereits läuft
                if _state.ble_status in (BLEStatus.UNKNOWN, BLEStatus.FAILED) and _state.ble_task is None:
                    _state.ble_status = BLEStatus.SCANNING
                    _state.ble_task = asyncio.create_task(_run_ble_scan_wrapper())

                # D. (Parallel 2) Intent-Logik (Block A) ausführen
                # Wir brauchen eine volle Historie für eine stabile Trendanalyse
                if len(_state.history) < HISTORY_SIZE:
                    log.trace(f"Warte auf volle Historie ({len(_state.history)}/{HISTORY_SIZE} Frames)...")
                    continue

                # Historie ist voll, Trend analysieren
                noise_threshold = config.get("radar_config.speed_noise_threshold", 5)
                expected_x_sign = config.get("radar_config.expected_x_sign", "negative")
                
                trend_str = _analyze_trajectory(_state.history, expected_x_sign, noise_threshold)

                # Intent-Status aktualisieren
                new_intent = IntentStatus.NEUTRAL
                if trend_str == "COMING":
                    new_intent = IntentStatus.KOMMEN
                elif trend_str == "LEAVING":
                    new_intent = IntentStatus.GEHEN
                
                if _state.intent_status != new_intent and new_intent != IntentStatus.NEUTRAL:
                    log.info(f"Intent-Status: {_state.intent_status.name} -> {new_intent.name}")
                    _state.intent_status = new_intent

                # E. Reset-Bedingungen (Intent = GEHEN)
                if _state.intent_status == IntentStatus.GEHEN:
                    log.info("Intent 'GEHEN' erkannt (NICHT ÖFFNEN FALL 2). Reset zu IDLE.")
                    _reset_to_idle()
                    continue

                # F. Trigger-Prüfung (Block B)
                # Prüfe, ob beide Bedingungen (BLE + Intent) "scharf" sind
                if _state.ble_status == BLEStatus.SUCCESS and _state.intent_status == IntentStatus.KOMMEN:
                    
                    door_opened = await _check_and_trigger_door()
                    
                    if door_opened:
                        # Erfolgreich geöffnet -> COOLDOWN
                        _state.system_state = SystemState.COOLDOWN
                        _reset_to_idle() # Setzt History zurück, behält BLE-Status
                        continue
                
                # G. Reset-Bedingung (BLE = FAILED)
                # (Prüfen wir *nach* dem Trigger, falls BLE erst jetzt fehlschlägt)
                if _state.ble_status == BLEStatus.FAILED:
                    log.info("BLE-Status 'FAILED' erkannt (NICHT ÖFFNEN FALL 1). Reset zu IDLE.")
                    _reset_to_idle()
                    continue

            # Nächste Schleife
            await asyncio.sleep(0) # Gibt Kontrolle kurz ab, falls Queue sofort wieder voll ist

    except asyncio.CancelledError:
        log.info("Radar Logic Task abgebrochen.")
    except Exception as e:
        log.critical(f"Kritischer Fehler im Radar Logic Task: {e}", exc_info=True)
    finally:
        # Wenn dieser Task stirbt, breche auch den BLE-Scan ab, falls er läuft
        if _state.ble_task and not _state.ble_task.done():
            _state.ble_task.cancel()
        log.info("Radar Logic Task beendet.")