# Program: globals_state.py
# Purpose: Enthält alle gemeinsam genutzten, veränderlichen globalen Statusvariablen des Systems.
#          Diese Variablen werden von verschiedenen Modulen gelesen und geschrieben.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:05 UTC - Erstellung des globals_state-Moduls.
# Modified: October 26, 2025, 14:00 UTC - TEST_DISPLAY_MODE und display_test_queue für Test-Progressbar hinzugefügt.
# Modified: November 07, 2025, 14:49 UTC - Logging-Refactor: Benannter Logger, Präfixe entfernt, TRACE_MODE entfernt.
# Modified: November 10, 2025, 16:30 UTC - Test-Display-Modus vollständig entfernt (TEST_DISPLAY_MODE, display_test_queue).
# Modified: November 10, 2025, 17:15 UTC - Globale Variablen-Leichen entfernt: beacon_last_seen_data, beacon_is_present, last_door_opened_timestamp (BLE-Scanner-Ära).
# Modified: November 10, 2025, 18:00 UTC - Kommentar-Leichen entfernt: 4 ungenutzte Felder aus beacon_identification_state Dokumentation gelöscht (BLE-Scanner-Ära).
# Modified: November 10, 2025, 18:05 UTC - HOTFIX: beacon_identification_state Variable wiederhergestellt (versehentlich gelöscht).

import asyncio
import time
import atexit
import logging
import datetime # Für last_successful_weather_data
from PIL import Image # Für Icon-Variablen

# NEU: Benannter Logger (Phase 4.1)
log = logging.getLogger(__name__)

# --- Globale Status-Queues und Variablen ---
display_status_queue = asyncio.Queue()

# Global state to track identification progress for each beacon MAC
# { "MAC_ADDRESS": { "name": "Beacon Name", "is_allowed": true/false,
#                    "ibeacon_data": {}, "uid_data": {}, "url_data": "",
#                    "last_packet_time": float, "is_fully_identified": bool,
#                    "known_beacon_config": {} } }
beacon_identification_state = {} 

# --- Globale Display Instanzen (für cleanup) ---
display = None
cs = None
extcomin = None
disp = None
extcomin_running = False # Flag, um den EXTCOMIN-Toggle-Thread zu steuern
extcomin_thread_task = None # NEU: Für den asyncio.Task des EXTCOMIN-Togglings

# --- Globale Icon Variablen ---
ICON_KEY = None
ICON_WIND = None
ICON_RAIN = None

# Globale Variable für die zuletzt erfolgreich abgerufenen Wetterdaten
last_successful_weather_data = {
    "temperature": "N/A",
    "wind_direction": "N/A",
    "wind_speed": "N/A",
    "precipitation": "N/A",
    "is_cached": True # Initial als "cached" markieren
}
last_pws_query_time = 0 # Initialisiere hier, damit es nicht in der Funktion als global deklariert werden muss

# --- codesend Hilfsfunktion Globals ---
_last_codesend_time = 0

# --- Hilfsfunktionen für GPIO-Cleanup ---
def cleanup_gpio():
    """Räumt die GPIO-Einstellungen auf."""
    try:
        import RPi.GPIO as GPIO
        if GPIO.getmode() is not None:
            GPIO.cleanup()
            log.info("RPi.GPIO aufgeräumt.")
    except ImportError:
        log.warning("RPi.GPIO nicht importierbar, überspringe GPIO-Cleanup.")
    except Exception as e:
        log.error(f"Fehler beim GPIO-Cleanup: {e}")

# Registriere die Cleanup-Funktion, die beim Beenden des Programms aufgerufen wird
atexit.register(cleanup_gpio)