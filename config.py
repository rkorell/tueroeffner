# Program: config.py
# Purpose: Enthält systemweite Konfigurationen und die Logik zum Laden dieser Konfigurationen.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:00 UTC - Erstellung des config-Moduls.
# Modified: November 07, 2025, 11:38 UTC - Implementierung TRACE-Level (5), Anpassung der Lade-Logik und Erweiterung Log-Format um [%(name)s].
# Modified: November 07, 2025, 12:11 UTC - Konstante TRACE_LEVEL in Logging-Config-Block verschoben.
# Modified: November 08, 2025, 11:10 UTC - CODESEND_CODE_BASIS in 'private_config.py' ausgelagert (Sicherheit).

import os
import json
import logging
import board # Für GPIO-Pin-Definitionen

# --- NEU: Definition und Registrierung des TRACE-Levels ---
# TRACE (5) liegt unter DEBUG (10)
# (Funktion wird global definiert, damit sie vor basicConfig aufgerufen werden kann)
def _add_trace_level():
    """
    Fügt das TRACE-Level zum logging-Modul hinzu,
    inklusive einer logging.trace()-Methode.
    """
    # Verwende den numerischen Wert 5 direkt, wie besprochen,
    # um die Konstante nur an einer Stelle zu definieren.
    if not hasattr(logging, "TRACE"):
        logging.addLevelName(5, "TRACE")
    
    if not hasattr(logging.Logger, "trace"):
        def trace_method(self, message, *args, **kws):
            if self.isEnabledFor(5):
                # self._log(level, message, args, **kws)
                self._log(5, message, args, **kws)
        logging.Logger.trace = trace_method

# Das neue Level sofort registrieren, bevor basicConfig aufgerufen wird
_add_trace_level()
# --- ENDE NEU ---


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
# --- NEU: Konstante hier platziert ---
TRACE_LEVEL = 5 # (Liegt unter DEBUG = 10)
# --- ENDE NEU ---
LOG_LEVEL = logging.INFO
LOG_FILE_ENABLED = False
LOG_FILE_PATH = "tuer_oeffner.log"

# --- codesend Konfiguration ---
# Der sensible CODESEND_CODE_BASIS wird aus 'private_config.py' geladen.
# Diese Datei ist NICHT Bestandteil des Git-Repositorys (siehe .gitignore)
# und muss manuell auf dem Zielsystem angelegt werden.
#
# Beispiel-Inhalt für 'private_config.py':
# # Code für Testbetrieb
# CODESEND_CODE_BASIS = 1012
# # Code für Produktion
# # CODESEND_CODE_BASIS = Ihr_Tuer_Oeffner_Code

CODESEND_PATH = "/usr/local/bin/codesend"
CODESEND_MIN_DURATION_SEC = 3

try:
    # Versuche, die Datei zu importieren und die Variable zu lesen
    import private_config
    CODESEND_CODE_BASIS = private_config.CODESEND_CODE_BASIS
    
except ImportError:
    # Dieser Fehler tritt auf, wenn 'private_config.py' nicht gefunden wird.
    # WICHTIG: logging ist hier noch nicht konfiguriert!
    print("WARNUNG: 'private_config.py' nicht gefunden.")
    CODESEND_CODE_BASIS = 1012 # Sicherer Fallback-Wert (Test-Empfänger)

except AttributeError:
    # Dieser Fehler tritt auf, wenn die Datei existiert,
    # aber die Variable 'CODESEND_CODE_BASIS' darin fehlt.
    print("WARNUNG: 'private_config.py' gefunden, aber Variable 'CODESEND_CODE_BASIS' fehlt.")
    CODESEND_CODE_BASIS = 1012 # Sicherer Fallback-Wert (Test-Empfänger)

    

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
                # logging.info(f"CONFIG: Systemkonfiguration aus '{SYSTEM_CONFIG_FILE}' geladen.")
                # ^^^ HINWEIS: logging.info() funktioniert hier noch nicht zuverlässig,
                # da basicConfig erst *danach* aufgerufen wird.
                return config
        except Exception as e:
            # logging.error(f"CONFIG: Fehler beim Laden von '{SYSTEM_CONFIG_FILE}': {e}")
            print(f"FATAL CONFIG ERROR: Fehler beim Laden von '{SYSTEM_CONFIG_FILE}': {e}")
            return None
    else:
        # logging.error(f"CONFIG: Systemkonfigurationsdatei '{SYSTEM_CONFIG_FILE}' nicht gefunden.")
        print(f"FATAL CONFIG ERROR: Systemkonfigurationsdatei '{SYSTEM_CONFIG_FILE}' nicht gefunden.")
        return None

def get(key_path, default=None):
    """
    Ermöglicht den Zugriff auf verschachtelte Konfigurationswerte über einen Punkt-separierten Pfad.
    Beispiel: config.get("system_globals.weather_config.query_interval_sec", 300)
    """
    global SYSTEM_CONFIG
    if SYSTEM_CONFIG is None:
        # logging.warning("CONFIG: SYSTEM_CONFIG ist noch nicht geladen. Rückgabe des Default-Wertes.")
        # ^^^ Logging hier noch nicht verfügbar
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

# Temporärer Logger für den Fall, dass SYSTEM_CONFIG fehlt
_temp_handlers = [logging.StreamHandler()]
_temp_format = '%(asctime)s - [%(name)s] - %(levelname)s - %(message)s'

if SYSTEM_CONFIG:
    # Logging konfigurieren
    logging_config = SYSTEM_CONFIG.get("system_globals", {}).get("logging_config", {})
    log_level_str = logging_config.get("level", "INFO").upper()
    
    # --- NEU: Angepasste Log-Level-Erkennung für TRACE ---
    log_level = logging.INFO # Default
    if log_level_str == "TRACE":
        log_level = TRACE_LEVEL
    else:
        # Standard-Weg für DEBUG, INFO, WARNING, etc.
        log_level = getattr(logging, log_level_str, logging.INFO)
    # --- ENDE NEU ---
    
    # Vorhandene Handler entfernen, um Neukonfiguration zu ermöglichen
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    
    handlers = [logging.StreamHandler()]
    if logging_config.get("file_enabled", False):
        log_file_path = logging_config.get("file_path", "tuer_oeffner.log")
        handlers.append(logging.FileHandler(log_file_path))

    logging.basicConfig(
        level=log_level,
        # --- NEU: Angepasstes Log-Format mit [%(name)s] ---
        format='%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
        # --- ENDE NEU ---
        handlers=handlers
    )
    
    # Hole einen Logger, NACHDEM basicConfig aufgerufen wurde
    log = logging.getLogger(__name__) # __name__ ist 'config'
    log.info(f"Logging-Level auf {log_level_str} (Wert: {log_level}) gesetzt.")
    if SYSTEM_CONFIG_FILE:
         log.info(f"Systemkonfiguration aus '{SYSTEM_CONFIG_FILE}' geladen.")


    # PWS_QUERY_URL konstruieren
    pws_config = SYSTEM_CONFIG.get("system_globals", {}).get("weather_config", {})
    if pws_config.get("station_id") and pws_config.get("api_key"):
        SYSTEM_CONFIG["system_globals"]["weather_config"]["query_url"] = \
            f"https://api.weather.com/v2/pws/observations/current?stationId={pws_config['station_id']}&format=json&units=m&numericPrecision=decimal&apiKey={pws_config['api_key']}"
        log.info("PWS_QUERY_URL konstruiert.")
    else:
        log.warning("PWS_STATION_ID oder PWS_API_KEY fehlen in der Konfiguration. Wetterdaten-Abfrage möglicherweise nicht möglich.")
else:
    # Fallback-Logging, falls SYSTEM_CONFIG nicht geladen werden konnte
    logging.basicConfig(
        level=logging.CRITICAL,
        format='%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    log = logging.getLogger(__name__)
    log.critical("SYSTEM_CONFIG konnte nicht geladen werden. System wird mit Default-Spezifikationen oder unvollständiger Konfiguration laufen.")