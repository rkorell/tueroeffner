# Program: adafruit_display_test.py
# Purpose: Testprogramm für das Adafruit Sharp Memory Display (2.7" 400x240).
#          Stellt statische Informationen (Begrüßung, Uhrzeit, Datum, Wetter)
#          und dynamische Status-Icons dar.
# Author: Dr. Ralf Korell
# Creation Date: July 31, 2025

import board
import busio
import digitalio
import time
import logging
import datetime
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps # NEU: ImageOps für Invertierung
import requests
import json

# RPi.GPIO importieren (für manuelle Pin-Steuerung)
import RPi.GPIO as GPIO

import adafruit_sharpmemorydisplay

# --- Logging Konfiguration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Colors
BLACK = 0
WHITE = 255

# --- Display Konfiguration ---
# Adafruit Sharp Memory Display (2.7" 400x240)
DISPLAY_WIDTH = 400
DISPLAY_HEIGHT = 240

# --- GPIO Pin Konfiguration für Adafruit Sharp ---
# Diese Pins müssen an dein Display angeschlossen werden.
# board.SCK, board.MOSI sind SPI-Pins (fest)
# digitalio.DigitalInOut(board.D6) ist der CS-Pin (Chip Select)
# digitalio.DigitalInOut(board.D5) ist der EXTCOMIN-Pin (External COM In)
# digitalio.DigitalInOut(board.D22) ist der DISP-Pin (Display On/Off)

# Bitte überprüfe deine genaue Verkabelung und passe die Pin-Nummern an!
# board.D6 ist GPIO 6 (phys. Pin 31)
# board.D5 ist GPIO 5 (phys. Pin 29)
# board.D22 ist GPIO 22 (phys. Pin 15)
SHARP_CS_PIN = board.D6 # Chip Select
SHARP_EXTCOMIN_PIN = board.D5 # External COM In
SHARP_DISP_PIN = board.D22 # Display On/Off

# --- Wunderground PWS Konfiguration ---
PWS_STATION_ID = "IGEROL23"
PWS_API_KEY = "d1a8702761c9427fa8702761c9f27fc1"
PWS_QUERY_URL = f"https://api.weather.com/v2/pws/observations/current?stationId={PWS_STATION_ID}&format=json&units=m&numericPrecision=decimal&apiKey={PWS_API_KEY}"
PWS_QUERY_INTERVAL = 5 * 60 # Sekunden (5 Minuten)
last_pws_query_time = 0

# Globale Variable für die zuletzt erfolgreich abgerufenen Wetterdaten
last_successful_weather_data = {
    "temperature": "N/A",
    "wind_direction": "N/A",
    "wind_speed": "N/A",
    "precipitation": "N/A",
    "is_cached": True # Initial als "cached" markieren
}

# --- Icon Konfiguration ---
ICON_DIMENSIONS = (32, 32) # Standardgröße 32x32 Pixel

# --- Icon Globale Variablen ---
ICON_EYE = None
ICON_KEY = None

def load_icons():
    global ICON_EYE, ICON_KEY
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        eye_path = os.path.join(script_dir, 'eye.png')
        key_path = os.path.join(script_dir, 'key.png')

        eye_img = Image.open(eye_path).resize(ICON_DIMENSIONS, Image.LANCZOS)
        ICON_EYE = eye_img.convert('1') # 1-Bit (Schwarz/Weiß)
        ICON_EYE = ImageOps.invert(ICON_EYE) # NEU: Icons invertieren, damit sie schwarz auf weißem Grund sind

        key_img = Image.open(key_path).resize(ICON_DIMENSIONS, Image.LANCZOS)
        ICON_KEY = key_img.convert('1') # 1-Bit (Schwarz/Weiß)
        ICON_KEY = ImageOps.invert(ICON_KEY) # NEU: Icons invertieren

        logging.info(f"Icons geladen und auf {ICON_DIMENSIONS} skaliert.")

    except FileNotFoundError as e:
        logging.error(f"FEHLER: Icon-Datei nicht gefunden: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None
    except Exception as e:
        logging.error(f"FEHLER beim Laden oder Skalieren der Icons: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None

# --- Schriftarten laden ---
# Priorität auf systemweite, gut lesbare Fonts
FONT_PATHS_TO_TRY = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSans.ttf'
]

def load_font_robust(size, default_font=None):
    for path in FONT_PATHS_TO_TRY:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except IOError:
                logging.warning(f"Konnte Schriftart {path} nicht laden. Versuche nächste.")
    logging.error("Keine der bevorzugten Schriftarten gefunden oder geladen. Verwende Standard-Font.")
    return default_font if default_font else ImageFont.load_default()

# NEU: Angepasste Schriftgrößen für das neue Layout (größer)
FONT_GREETING = load_font_robust(30) # Für Begrüßung
FONT_TIME_DATE = load_font_robust(24) # Für Uhrzeit und Datum
FONT_WEATHER_TEMP_BIG = load_font_robust(28) # Für Temperatur
FONT_WEATHER_DETAIL = load_font_robust(18) # Für Wind/Niederschlag

# --- Globale Display Instanz ---
display = None
cs = None
extcomin = None
disp = None

# Flag, um den EXTCOMIN-Toggle-Thread zu steuern
extcomin_running = False

# Funktion zum manuellen Togglen des EXTCOMIN-Pins
def toggle_extcomin():
    global extcomin_running
    logging.info("Starte manuelles EXTCOMIN Toggling.")
    while extcomin_running:
        if extcomin is not None:
            extcomin.value = not extcomin.value # Wechselt den Zustand
        time.sleep(0.5) # Toggelt alle 0.5 Sekunden (1Hz)
    logging.info("EXTCOMIN Toggling beendet.")

# --- Hilfsfunktionen ---

def degrees_to_cardinal(degrees):
    directions = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / (360. / len(directions))) % len(directions)
    return directions[idx]

def get_weather_data():
    """
    Fragt Wetterdaten von der Wunderground PWS API ab.
    Speichert die Daten im Cache und gibt sie zurück.
    """
    global last_pws_query_time, last_successful_weather_data
    
    if time.time() - last_pws_query_time < PWS_QUERY_INTERVAL:
        logging.info("Wetterdaten-Abfrageintervall noch nicht erreicht. Verwende letzte Daten aus Cache.")
        return last_successful_weather_data

    try:
        logging.info(f"Frage Wetterdaten von {PWS_QUERY_URL} ab...")
        response = requests.get(PWS_QUERY_URL, timeout=10)
        response.raise_for_status()
        data = response.json()

        obs = data.get("observations", [])
        if not obs:
            logging.warning("Keine Beobachtungen in den Wetterdaten gefunden. Verwende Cache.")
            last_successful_weather_data["is_cached"] = True
            return last_successful_weather_data

        metric = obs[0].get("metric", {})
        winddir_deg = obs[0].get("winddir")
        
        weather_info = {
            "temperature": f"{metric.get('temp', 'N/A')}°C",
            "wind_direction": degrees_to_cardinal(winddir_deg) if winddir_deg is not None else "N/A",
            "wind_speed": f"{metric.get('windSpeed', 'N/A')} km/h",
            "precipitation": f"{metric.get('precipTotal', 'N/A')} mm",
            "is_cached": False
        }
        last_pws_query_time = time.time()
        last_successful_weather_data = weather_info
        logging.info(f"Wetterdaten erfolgreich abgerufen: {weather_info}")
        return weather_info

    except requests.exceptions.RequestException as e:
        logging.error(f"Fehler bei der Wetterdaten-Abfrage: {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True
        return last_successful_weather_data
    except json.JSONDecodeError as e:
        logging.error(f"Fehler beim Parsen der Wetterdaten (JSON): {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True
        return last_successful_weather_data
    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler bei der Wetterdaten-Abfrage ist aufgetreten: {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True
        return last_successful_weather_data

def get_time_based_greeting():
    current_hour = datetime.datetime.now().hour
    if 5 <= current_hour < 11:
        return "Guten Morgen!"
    elif 11 <= current_hour < 18:
        return "Guten Tag!"
    else:
        return "Guten Abend!"

def draw_display_content(draw, weather_data, status_icon_type=None):
    """Zeichnet den gesamten Displayinhalt."""
    
    # Hintergrund löschen (weiß)
    draw.rectangle((0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT), outline=WHITE, fill=WHITE)

    # Zeile 1: Begrüßung (linksbündig)
    greeting_text = get_time_based_greeting()
    draw.text((5, 5), greeting_text, font=FONT_GREETING, fill=BLACK)

    # Zeile 2: Uhrzeit - Datum (linksbündig)
    current_time = time.strftime("%H:%M")
    current_date = time.strftime("%d.%m.%Y")
    time_date_text = f"{current_time} - {current_date}"
    draw.text((5, 40), time_date_text, font=FONT_TIME_DATE, fill=BLACK) # NEU: Y-Position angepasst

    # Wetterinformationen (linksbündig)
    if weather_data:
        temp_text = weather_data.get('temperature', 'N/A')
        if weather_data.get('is_cached', False):
            temp_text = f"[{temp_text}]"
        
        draw.text((5, 80), temp_text, font=FONT_WEATHER_TEMP_BIG, fill=BLACK) # NEU: Y-Position angepasst
        draw.text((5, 110), f"Wind: {weather_data.get('wind_speed', 'N/A')} km/h {weather_data.get('wind_direction', 'N/A')}", font=FONT_WEATHER_DETAIL, fill=BLACK)
        draw.text((5, 130), f"Regen: {weather_data.get('precipitation', 'N/A')} mm", font=FONT_WEATHER_DETAIL, fill=BLACK)

    # Status Icon (rechts unten)
    icon_to_draw = None
    if status_icon_type == "BEACON_DETECTED":
        icon_to_draw = ICON_EYE
    elif status_icon_type == "ACCESS_GRANTED":
        icon_to_draw = ICON_KEY
    
    if icon_to_draw:
        # Positioniere Icon in der rechten unteren Ecke des Displays
        x_pos = DISPLAY_WIDTH - ICON_DIMENSIONS[0] - 5 # 5 Pixel vom rechten Rand
        y_pos = DISPLAY_HEIGHT - ICON_DIMENSIONS[1] - 5 # 5 Pixel vom unteren Rand
        
        # Füge das Icon in das Bild ein
        # Sharp Displays sind 1-Bit, daher direkt einfügen
        draw.bitmap((x_pos, y_pos), icon_to_draw, fill=BLACK)


# --- Hauptprogramm ---
def main():
    # Icons laden (einmalig beim Start)
    load_icons()

    # SPI-Bus initialisieren
    spi = busio.SPI(board.SCK, MOSI=board.MOSI)
    
    # GPIOs für CS, EXTCOMIN, DISP initialisieren
    global cs, extcomin, disp # Globale Variablen, damit sie im finally-Block geschlossen werden können
    cs = digitalio.DigitalInOut(SHARP_CS_PIN)
    extcomin = digitalio.DigitalInOut(SHARP_EXTCOMIN_PIN)
    disp = digitalio.DigitalInOut(SHARP_DISP_PIN)

    # Pins als Ausgänge konfigurieren (Adafruit-Bibliotheken erwarten dies)
    cs.direction = digitalio.Direction.OUTPUT
    extcomin.direction = digitalio.Direction.OUTPUT
    disp.direction = digitalio.Direction.OUTPUT

    # Initialwerte für DISP und EXTCOMIN setzen (vor Display-Initialisierung)
    disp.value = True # DISP HIGH, um Display einzuschalten
    extcomin.value = False # EXTCOMIN initial LOW

    # Starte den EXTCOMIN-Toggle-Thread
    import threading
    global extcomin_running # Muss global sein, um im finally-Block beendet zu werden
    extcomin_running = True
    extcomin_thread = threading.Thread(target=toggle_extcomin)
    extcomin_thread.daemon = True
    extcomin_thread.start()
    logging.info("EXTCOMIN Toggling Thread gestartet.")
    time.sleep(0.1) # Kurze Pause, damit der Thread starten kann

    global display
    try:
        display = adafruit_sharpmemorydisplay.SharpMemoryDisplay(
            spi, cs, DISPLAY_WIDTH, DISPLAY_HEIGHT
        )
        logging.info("Adafruit Sharp Memory Display initialisiert.")

        # Debug-Ausgaben für Pin-Werte
        logging.info(f"SHARP_CS_PIN ({SHARP_CS_PIN.id}) Wert: {cs.value}")
        logging.info(f"SHARP_EXTCOMIN_PIN ({SHARP_EXTCOMIN_PIN.id}) Wert: {extcomin.value}")
        logging.info(f"SHARP_DISP_PIN ({SHARP_DISP_PIN.id}) Wert: {disp.value}")

        time.sleep(0.5)
        logging.info(f"SHARP_EXTCOMIN_PIN ({SHARP_EXTCOMIN_PIN.id}) Wert nach 0.5s: {extcomin.value}")
        logging.info(f"SHARP_DISP_PIN ({SHARP_DISP_PIN.id}) Wert nach 0.5s: {disp.value}")

        # Create blank image for drawing.
        image = Image.new("1", (display.width, display.height))
        draw = ImageDraw.Draw(image)

        # Testsequenz der Statusmeldungen
        statuses = [
            ("IDLE", None), # Initialanzeige
            ("BEACON_DETECTED", None),
            ("ACCESS_GRANTED", "Ralf"), # Personennamen hier nicht relevant für Icon
            (None, None), # Leert das Icon (kein Typ)
            ("IDLE", None) # Optional: Vollaktualisierung zurück zum Idle-Zustand
        ]

        for i, (status_type, person_name) in enumerate(statuses):
            logging.info(f"\n--- Test {i+1}: Anzeige von '{status_type}' ---")
            
            # Wetterdaten nur im IDLE-Status aktualisieren, sonst die letzten verwenden
            weather_to_display = get_weather_data() if status_type == "IDLE" else last_successful_weather_data

            # Zeichne den gesamten Inhalt neu, da Sharp Displays keine Teilaktualisierung haben
            draw_display_content(draw, weather_to_display, status_icon_type=status_type)
            display.image(image)
            display.show()
            logging.info(f"Display mit '{status_type}' Status aktualisiert.")
            time.sleep(5) # Warte 5 Sekunden, bevor der nächste Status angezeigt wird

        logging.info("\nAlle Test-Status durchlaufen.")

    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler im Hauptprogramm ist aufgetreten: {e}")
    finally:
        # EXTCOMIN-Toggle-Thread beenden
        extcomin_running = False
        if 'extcomin_thread' in locals() and extcomin_thread.is_alive():
            extcomin_thread.join(timeout=1.0)
            logging.info("EXTCOMIN Toggling Thread beendet.")

        if display is not None:
            display.fill(1) # Display löschen (weiß)
            display.show()
            logging.info("Adafruit Sharp Display gelöscht.")
            time.sleep(0.5) # Kurze Wartezeit, damit das Display das Signal verarbeiten kann
        
        # GPIOs sauber deinitialisieren
        if cs is not None:
            cs.deinit()
            logging.info("CS Pin deinitialisiert.")
        if extcomin is not None:
            extcomin.deinit()
            logging.info("EXTCOMIN Pin deinitialisiert.")
        if disp is not None:
            disp.deinit()
            logging.info("DISP Pin deinitialisiert.")
        logging.info("GPIOs sauber deinitialisiert. Programm beendet.")


if __name__ == "__main__":
    main()
