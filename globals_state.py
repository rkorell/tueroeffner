# Program: globals_state.py
# Purpose: Enthält alle gemeinsam genutzten, veränderlichen globalen Statusvariablen des Systems.
#          Diese Variablen werden von verschiedenen Modulen gelesen und geschrieben.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:05 UTC - Erstellung des globals_state-Moduls.
# Modified: October 26, 2025, 14:00 UTC - TEST_DISPLAY_MODE und display_test_queue für Test-Progressbar hinzugefügt.

import asyncio
import time
import atexit
import logging
import datetime # Für last_successful_weather_data
from PIL import Image # Für Icon-Variablen

TRACE_MODE = True  # temporärer Performance-Trace (False = deaktiviert)
TEST_DISPLAY_MODE = False  # Test-Progressbar aktivieren (True = Testmodus, False = Produktivbetrieb)

# --- Globale Status-Queues und Variablen ---
display_status_queue = asyncio.Queue()
display_test_queue = asyncio.Queue()  # NEU: Für Test-Progressbar-Daten

# beacon_last_seen_data stores for each Beacon: {'timestamp': time.time(), 'rssi': rssi_val, 'distance': distance}
# Initialisiert mit float('inf') für Distanz und 0 für timestamp, um "nicht gesehen" zu signalisieren
beacon_last_seen_data = {} 

beacon_is_present = False # True, wenn mindestens ein relevanter Beacon als "anwesend" gilt (nach Debouncing)

last_door_opened_timestamp = 0 

# Global state to track identification progress for each beacon MAC
# { "MAC_ADDRESS": { "name": "Beacon Name", "is_allowed": true/false,
#                    "ibeacon_data": {}, "uid_data": {}, "url_data": "",
#                    "last_packet_time": float, "is_fully_identified": bool,
#                    "known_beacon_config": {},
#                    "is_in_proximity_raw": bool, "proximity_state_change_time": float, "is_in_proximity_debounced": bool,
#                    "is_currently_inside_house": bool } }
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
            logging.info("GLOBALS_STATE: RPi.GPIO aufgeräumt.")
    except ImportError:
        logging.warning("GLOBALS_STATE: RPi.GPIO nicht importierbar, überspringe GPIO-Cleanup.")
    except Exception as e:
        logging.error(f"GLOBALS_STATE: Fehler beim GPIO-Cleanup: {e}")

# Registriere die Cleanup-Funktion, die beim Beenden des Programms aufgerufen wird
atexit.register(cleanup_gpio)