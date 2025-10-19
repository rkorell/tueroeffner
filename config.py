# Program: config.py
# Purpose: Enthält systemweite Konfigurationen und die Logik zum Laden dieser Konfigurationen.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:00 UTC - Erstellung des config-Moduls.

import os
import json
import logging
import board # Für GPIO-Pin-Definitionen

# --- GLOBALE KONFIGURATION (Wird aus system_config.json geladen) ---
# Default-Werte, falls system_config.json fehlt oder fehlerhaft ist
SYSTEM_CONFIG_FILE = "system_config.json"

# System Globals (Initialwerte, die aus der Konfigurationsdatei überschrieben werden)
TARGET_IBEACON_UUID = ""
EDDYSTONE_NAMESPACE_ID = ""
BLE_SCAN_INTERVAL_SEC = 1.0
IDENTIFICATION_TIMEOUT_SEC = 4.0
PROXIMITY_DISTANCE_THRESHOLD = 3.0
PRESENCE_DETECTION_TIME = 3
ABSENCE_DETECTION_TIME = 10
CALIBRATED_MEASURED_POWER_GLOBAL_DEFAULT = -77
PATH_LOSS_EXPONENT_GLOBAL_DEFAULT = 2.5
RELAY_ACTIVATION_DURATION_SEC = 4
FORCE_BEACON_ABSENCE_DURATION_SEC = 10
INITIAL_SCAN_DURATION_SEC = 15
BEACON_ABSENCE_TIMEOUT_FOR_HOME_STATUS_SEC = 3600
MIN_DETECTION_INTERVAL = 5 # Cooldown for codesend

# Weather Config (Initialwerte)
PWS_STATION_ID = ""
PWS_API_KEY = ""
PWS_QUERY_URL = "" # Will be constructed later
PWS_QUERY_INTERVAL_SEC = 5 * 60

# Logging Config (Initialwerte)
LOG_LEVEL = logging.INFO
LOG_FILE_ENABLED = False
LOG_FILE_PATH = "tuer_oeffner.log"

# codesend Konfiguration (hardkodiert, da nicht in JSON ausgelagert)
CODESEND_PATH = "/usr/local/bin/codesend"
CODESEND_CODE_BASIS = 1012
CODESEND_MIN_DURATION_SEC = 3

# Display Konfiguration (hardkodiert, da nicht in JSON ausgelagert)
DISPLAY_WIDTH = 400
DISPLAY_HEIGHT = 240
SHARP_CS_PIN = board.D6
SHARP_EXTCOMIN_PIN = board.D5
SHARP_DISP_PIN = board.D22

# Definition der WEATHER_ICON_SIZE und ICON_DIMENSIONS
WEATHER_ICON_SIZE = (20, 20)
ICON_DIMENSIONS = (32, 32)

# Loaded config from JSON
SYSTEM_CONFIG = None

def read_system_config():
    """
    Liest die Systemkonfigurationsdatei (system_config.json).
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, SYSTEM_CONFIG_FILE)

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logging.info(f"CONFIG: Systemkonfiguration aus '{SYSTEM_CONFIG_FILE}' geladen.")
                return config
        except Exception as e:
            logging.error(f"CONFIG: Fehler beim Laden von '{SYSTEM_CONFIG_FILE}': {e}")
            return None
    else:
        logging.error(f"CONFIG: Systemkonfigurationsdatei '{SYSTEM_CONFIG_FILE}' nicht gefunden.")
        return None

def get(key_path, default=None):
    """
    Ermöglicht den Zugriff auf verschachtelte Konfigurationswerte über einen Punkt-separierten Pfad.
    Beispiel: config.get("system_globals.weather_config.query_interval_sec", 300)
    """
    global SYSTEM_CONFIG
    if SYSTEM_CONFIG is None:
        logging.warning("CONFIG: SYSTEM_CONFIG ist noch nicht geladen. Rückgabe des Default-Wertes.")
        return default

    keys = key_path.split('.')
    current_value = SYSTEM_CONFIG
    for key in keys:
        if isinstance(current_value, dict) and key in current_value:
            current_value = current_value[key]
        else:
            return default
    return current_value

# --- Initialisierungsblock für das config-Modul ---
# Dieser Block wird ausgeführt, sobald das config-Modul importiert wird.
SYSTEM_CONFIG = read_system_config()

if SYSTEM_CONFIG:
    # Logging konfigurieren
    logging_config = SYSTEM_CONFIG.get("system_globals", {}).get("logging_config", {})
    log_level_str = logging_config.get("level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    # Vorhandene Handler entfernen, um Neukonfiguration zu ermöglichen
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    handlers = [logging.StreamHandler()]
    if logging_config.get("file_enabled", False):
        log_file_path = logging_config.get("file_path", "tuer_oeffner.log")
        handlers.append(logging.FileHandler(log_file_path))

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    logging.info(f"CONFIG: Logging-Level auf {log_level_str} gesetzt.")

    # PWS_QUERY_URL konstruieren
    pws_config = SYSTEM_CONFIG.get("system_globals", {}).get("weather_config", {})
    if pws_config.get("station_id") and pws_config.get("api_key"):
        SYSTEM_CONFIG["system_globals"]["weather_config"]["query_url"] = \
            f"https://api.weather.com/v2/pws/observations/current?stationId={pws_config['station_id']}&format=json&units=m&numericPrecision=decimal&apiKey={pws_config['api_key']}"
        logging.info("CONFIG: PWS_QUERY_URL konstruiert.")
    else:
        logging.warning("CONFIG: PWS_STATION_ID oder PWS_API_KEY fehlen in der Konfiguration. Wetterdaten-Abfrage möglicherweise nicht möglich.")
else:
    logging.critical("CONFIG: SYSTEM_CONFIG konnte nicht geladen werden. System wird mit Default-Werten oder unvollständiger Konfiguration laufen.")

    