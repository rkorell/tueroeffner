# Program: door_control.py
# Purpose: Kapselt die Logik zum Senden des Türöffner-Befehls.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:10 UTC - Erstellung des door_control-Moduls.

import asyncio
import time
import subprocess
import logging

import config
import globals_state as gs

async def send_door_open_command(duration_sec):
    """
    Berechnet den codesend-Code basierend auf der gewünschten Dauer und ruft codesend auf.
    Verhindert Mehrfachauslösung innerhalb von MIN_DETECTION_INTERVAL.
    """
    current_time = time.time()

    # Holen des min_detection_interval aus der Konfiguration
    min_detection_interval = config.get("system_globals.min_detection_interval", config.MIN_DETECTION_INTERVAL)

    if (current_time - gs._last_codesend_time) < min_detection_interval:
        logging.info(f"DOOR_CONTROL: codesend Cooldown aktiv. Nächste Auslösung in {min_detection_interval - (current_time - gs._last_codesend_time):.1f}s.")
        return

    # Holen der codesend-spezifischen Konfiguration aus dem config-Modul
    codesend_min_duration_sec = config.CODESEND_MIN_DURATION_SEC
    codesend_code_basis = config.CODESEND_CODE_BASIS
    codesend_path = config.CODESEND_PATH

    if not (codesend_min_duration_sec <= duration_sec <= 10):
        logging.error(f"DOOR_CONTROL: Ungültige Dauer für codesend: {duration_sec} Sekunden. Muss zwischen {codesend_min_duration_sec} und 10 Sekunden liegen.")
        return

    code_to_send = codesend_code_basis + (duration_sec - codesend_min_duration_sec)
    
    try:
        logging.info(f"DOOR_CONTROL: Sende Türöffner-Befehl: codesend {code_to_send}")
        process = await asyncio.to_thread(
            subprocess.run,
            [codesend_path, str(code_to_send)],
            check=True,
            capture_output=True,
            text=True
        )
        logging.info(f"DOOR_CONTROL: codesend erfolgreich aufgerufen. Output: {process.stdout.strip()}")
        gs._last_codesend_time = current_time
    except FileNotFoundError:
        logging.error(f"DOOR_CONTROL: Fehler: codesend nicht gefunden unter {codesend_path}. Bitte Pfad prüfen.")
    except subprocess.CalledProcessError as e:
        logging.error(f"DOOR_CONTROL: Fehler beim Aufruf von codesend: {e}. Stdout: {e.stdout}, Stderr: {e.stderr}")
    except Exception as e:
        logging.error(f"DOOR_CONTROL: Ein unerwarteter Fehler beim Senden des codesend-Befehls ist aufgetreten: {e}")