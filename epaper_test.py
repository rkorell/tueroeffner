# Program: epaper_test.py
# Purpose: Separates Testprogramm für das Waveshare e-Paper Display 2.9'' V2.
#          Zeigt verschiedene Statusmeldungen an, misst die Aktualisierungszeit
#          und dient zur Entwicklung der Display-Inhalte.
# Author: Dr. Ralf Korell
# Creation Date: July 27, 2025

import os
import time
import logging
from PIL import Image, ImageDraw, ImageFont
import datetime # Für zeitabhängige Begrüßung
import requests # Für API-Abfragen
import json # Für JSON-Parsing

# --- e-Paper Display Konfiguration ---
WAVESHARE_BASE_PATH = '/home/pi/e-Paper/RaspberryPi_JetsonNano/python'
E_PAPER_PIC_DIR = os.path.join(WAVESHARE_BASE_PATH, 'pic')
E_PAPER_LIB_DIR = os.path.join(WAVESHARE_BASE_PATH, 'lib')

if os.path.exists(E_PAPER_LIB_DIR):
    import sys
    sys.path.append(E_PAPER_LIB_DIR)
else:
    print(f"Fehler: Waveshare Bibliothekspfad nicht gefunden: {E_PAPER_LIB_DIR}")
    print("Bitte stellen Sie sicher, dass das Waveshare e-Paper Repository korrekt geklont ist.")
    sys.exit(1)

try:
    from waveshare_epd import epd2in9_V2
    from waveshare_epd import epdconfig # Für module_exit
except ImportError as e:
    print(f"Fehler beim Import der Waveshare e-Paper Bibliothek: {e}")
    print("Stellen Sie sicher, dass Sie 'pip install .' im Waveshare-Python-Verzeichnis ausgeführt haben.")
    sys.exit(1)

# --- Logging Konfiguration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Globale Variable für e-Paper Objekt
epd = None
# Globale Variable, um den Zustand des vollständigen Displays zu speichern
current_display_image = None # Speichert das PIL Image des letzten Voll-Updates

# --- Wunderground PWS Konfiguration ---
PWS_STATION_ID = "IGEROL23"
PWS_API_KEY = "d1a8702761c9427fa8702761c9f27fc1"
PWS_QUERY_URL = f"https://api.weather.com/v2/pws/observations/current?stationId={PWS_STATION_ID}&format=json&units=m&numericPrecision=decimal&apiKey={PWS_API_KEY}"
PWS_QUERY_INTERVAL = 5 * 60 # Sekunden (5 Minuten)
last_pws_query_time = 0

# NEU: Globale Variable für die zuletzt erfolgreich abgerufenen Wetterdaten
last_successful_weather_data = {
    "temperature": "N/A",
    "wind_direction": "N/A",
    "wind_speed": "N/A",
    "precipitation": "N/A",
    "is_cached": True # Initial als "cached" markieren
}

# --- Display Layout und Schriftarten ---
# Display Dimensionen für 2.9inch V2 (querformat)
EPD_WIDTH = 128 # Breite des Displays im Hochformat
EPD_HEIGHT = 296 # Höhe des Displays im Hochformat (wird zu Breite im Querformat)

# Schriftarten laden (Priorität auf systemweite, gut lesbare Fonts, dann Waveshare's Font.ttc)
FONT_PATHS_TO_TRY = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    os.path.join(E_PAPER_PIC_DIR, 'Font.ttc')
]

# Funktion zum Laden der Schriftart
def load_font_robust(size, default_font=None):
    for path in FONT_PATHS_TO_TRY:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except IOError:
                logging.warning(f"Konnte Schriftart {path} nicht laden. Versuche nächste.")
    logging.error("Keine der bevorzugten Schriftarten gefunden oder geladen. Verwende Standard-Font.")
    return default_font if default_font else ImageFont.load_default()

# Angepasste Schriftgrößen für das neue Layout
FONT_GREETING = load_font_robust(22) # Für Begrüßung
FONT_TIME_DATE = load_font_robust(18) # Für Uhrzeit und Datum (gleicher Schriftgrad)
FONT_WEATHER_TEMP_BIG = load_font_robust(20) # Für Temperatur (größer)
FONT_WEATHER_DETAIL = load_font_robust(14) # Für Wind/Niederschlag
FONT_MESSAGE_ICON = load_font_robust(32) # NEU: Für "B" oder "S" (32pt)

# --- Icon Konfiguration ---
ICON_DIMENSIONS = (32, 32) # NEU: Standardgröße 32x32 Pixel

# --- Icon Globale Variablen ---
ICON_EYE = None
ICON_KEY = None

def load_icons():
    global ICON_EYE, ICON_KEY
    try:
        # Pfad zu den Icons (im selben Verzeichnis wie das Skript)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        eye_path = os.path.join(script_dir, 'eye.png')
        key_path = os.path.join(script_dir, 'key.png')

        # Lade und skaliere eye.png
        eye_img = Image.open(eye_path).resize(ICON_DIMENSIONS, Image.LANCZOS)
        ICON_EYE = eye_img.convert('1') # Konvertiere zu 1-Bit (Schwarz/Weiß)
        logging.info(f"Icon 'eye.png' geladen und auf {ICON_DIMENSIONS} skaliert.")

        # Lade und skaliere key.png
        key_img = Image.open(key_path).resize(ICON_DIMENSIONS, Image.LANCZOS)
        ICON_KEY = key_img.convert('1') # Konvertiere zu 1-Bit (Schwarz/Weiß)
        logging.info(f"Icon 'key.png' geladen und auf {ICON_DIMENSIONS} skaliert.")

    except FileNotFoundError as e:
        logging.error(f"FEHLER: Icon-Datei nicht gefunden: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None
    except Exception as e:
        logging.error(f"FEHLER beim Laden oder Skalieren der Icons: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None

# --- Layout Bereiche (Koordinaten für 296x128 Bild) ---
# Linker Bereich für statische Infos
STATIC_ZONE_X = 0
STATIC_ZONE_Y = 0
STATIC_ZONE_WIDTH = 150 # Breite des linken Bereichs
STATIC_ZONE_HEIGHT = EPD_WIDTH # Ganze Höhe (128)

# Rechter unterer Nachrichtenbereich (rechter unterer Quadrant)
MESSAGE_ZONE_X = STATIC_ZONE_WIDTH # Startet bei X=150
MESSAGE_ZONE_Y = EPD_WIDTH // 2 # Startet bei Y=64 (128 / 2)
MESSAGE_ZONE_WIDTH = EPD_HEIGHT - STATIC_ZONE_WIDTH # Restliche Breite (296 - 150 = 146)
MESSAGE_ZONE_HEIGHT = EPD_WIDTH - MESSAGE_ZONE_Y # Restliche Höhe (128 - 64 = 64)

# --- Hilfsfunktionen ---

def init_epd_display():
    """Initialisiert das e-Paper Display."""
    global epd
    try:
        epd = epd2in9_V2.EPD()
        logging.info("e-Paper Display Objekt erstellt.")
        load_icons() # Icons beim Display-Start laden
        return True
    except Exception as e:
        logging.error(f"FEHLER: e-Paper Display konnte nicht initialisiert werden: {e}")
        epd = None
        return False

def cleanup_epd_display():
    """Setzt das e-Paper Display in den Schlafmodus und führt Cleanup durch."""
    if epd is not None:
        try:
            logging.info("e-Paper Display geht in den Schlafmodus...")
            epd.sleep() # Display in den Schlafmodus
            epdconfig.module_exit() # Zusätzliches Cleanup für Waveshare-Modul
            logging.info("e-Paper Display im Schlafmodus und Ressourcen freigegeben.")
        except Exception as e:
            logging.error(f"FEHLER beim Versetzen des e-Paper Displays in den Schlafmodus: {e}")

# NEU: Funktion zur Umrechnung von Windrichtung in Grad zu Himmelsrichtung
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
    
    # Prüfen, ob Abfrageintervall erreicht ist
    if time.time() - last_pws_query_time < PWS_QUERY_INTERVAL:
        logging.info("Wetterdaten-Abfrageintervall noch nicht erreicht. Verwende letzte Daten aus Cache.")
        return last_successful_weather_data # Gib die gecachten Daten zurück

    try:
        logging.info(f"Frage Wetterdaten von {PWS_QUERY_URL} ab...")
        response = requests.get(PWS_QUERY_URL, timeout=10)
        response.raise_for_status() # Löst HTTPError für schlechte Statuscodes auf
        data = response.json()

        obs = data.get("observations", [])
        if not obs:
            logging.warning("Keine Beobachtungen in den Wetterdaten gefunden. Verwende Cache.")
            last_successful_weather_data["is_cached"] = True # Markiere als cached
            return last_successful_weather_data

        metric = obs[0].get("metric", {})
        winddir_deg = obs[0].get("winddir")
        
        weather_info = {
            "temperature": f"{metric.get('temp', 'N/A')}°C",
            "wind_direction": degrees_to_cardinal(winddir_deg) if winddir_deg is not None else "N/A",
            "wind_speed": f"{metric.get('windSpeed', 'N/A')} km/h",
            "precipitation": f"{metric.get('precipTotal', 'N/A')} mm",
            "is_cached": False # Markiere als frisch
        }
        last_pws_query_time = time.time()
        last_successful_weather_data = weather_info # Cache aktualisieren
        logging.info(f"Wetterdaten erfolgreich abgerufen: {weather_info}")
        return weather_info

    except requests.exceptions.RequestException as e:
        logging.error(f"Fehler bei der Wetterdaten-Abfrage: {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True # Markiere als cached
        return last_successful_weather_data
    except json.JSONDecodeError as e:
        logging.error(f"Fehler beim Parsen der Wetterdaten (JSON): {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True # Markiere als cached
        return last_successful_weather_data
    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler bei der Wetterdaten-Abfrage ist aufgetreten: {e}. Verwende Cache.")
        last_successful_weather_data["is_cached"] = True # Markiere als cached
        return last_successful_weather_data

def get_time_based_greeting():
    """Gibt eine zeitabhängige Begrüßung zurück."""
    current_hour = datetime.datetime.now().hour
    if 5 <= current_hour < 11:
        return "Guten Morgen!"
    elif 11 <= current_hour < 18:
        return "Guten Tag!"
    else:
        return "Guten Abend!"

def draw_static_info(draw, weather_data):
    """Zeichnet die statischen Informationen im linken Bereich."""
    
    # Zeile 1: Begrüßung (linksbündig)
    greeting_text = get_time_based_greeting()
    draw.text((10, 5), greeting_text, font=FONT_GREETING, fill=0)

    # Zeile 2: Uhrzeit - Datum (linksbündig)
    current_time = time.strftime("%H:%M")
    current_date = time.strftime("%d.%m.%Y")
    time_date_text = f"{current_time} - {current_date}"
    draw.text((10, 35), time_date_text, font=FONT_TIME_DATE, fill=0)

    # Wetterinformationen (linksbündig)
    if weather_data:
        temp_text = weather_data.get('temperature', 'N/A')
        if weather_data.get('is_cached', False):
            temp_text = f"[{temp_text}]" # Temperatur in Klammern, wenn aus Cache
        
        # Temperatur (größer)
        draw.text((10, 70), temp_text, font=FONT_WEATHER_TEMP_BIG, fill=0)
        # Wind und Regen (kleiner)
        draw.text((10, 95), f"Wind: {weather_data.get('wind_direction', 'N/A')} {weather_data.get('wind_speed', 'N/A')}", font=FONT_WEATHER_DETAIL, fill=0)
        draw.text((10, 110), f"Regen: {weather_data.get('precipitation', 'N/A')}", font=FONT_WEATHER_DETAIL, fill=0)


def update_epd_display_content(status_type, person_name=None, weather_data=None, use_partial_update=False):
    """
    Aktualisiert den Inhalt des e-Paper Displays basierend auf dem Status.
    Kann Teilaktualisierung nutzen.
    """
    global current_display_image # Zugriff auf die globale Variable

    if epd is None:
        logging.warning("e-Paper Display ist nicht initialisiert. Überspringe Update.")
        return

    start_time = time.time()
    logging.info(f"Starte e-Paper Update für Status: {status_type} (Partial: {use_partial_update})")

    try:
        # Erstelle ein neues Bild für den gesamten Displayinhalt
        Himage = Image.new('1', (epd.height, epd.width), 255) # 255: weißer Hintergrund
        draw = ImageDraw.Draw(Himage)

        if use_partial_update and current_display_image is not None:
            # Basisbild vom letzten Voll-Update laden
            Himage = current_display_image.copy()
            draw = ImageDraw.Draw(Himage)
            
            # Rechten Nachrichtenbereich im Basisbild weiß machen
            draw.rectangle((MESSAGE_ZONE_X, MESSAGE_ZONE_Y, 
                            MESSAGE_ZONE_X + MESSAGE_ZONE_WIDTH, MESSAGE_ZONE_Y + MESSAGE_ZONE_HEIGHT), 
                            fill=255) # Weiß füllen
            
            # Icon für Nachrichtenbereich
            icon_to_draw = None
            if status_type == "BEACON_DETECTED":
                icon_to_draw = ICON_EYE
                
            elif status_type == "ACCESS_GRANTED":
                icon_to_draw = ICON_KEY
            
            elif status_type == "CLEAR_MESSAGE_ZONE":
                pass # Nachrichtenbereich bleibt weiß, da er oben schon gefüllt wurde

            # Wenn ein Icon vorhanden ist, zeichne es
            if icon_to_draw:
                # Positioniere Icon in der rechten unteren Ecke des MESSAGE_ZONE
                # x_pos: Rechter Rand der MESSAGE_ZONE - Iconbreite - 5 Pixel Abstand
                x_pos = MESSAGE_ZONE_X + MESSAGE_ZONE_WIDTH - ICON_DIMENSIONS[0] - 5
                # y_pos: Unterer Rand der MESSAGE_ZONE - Iconhöhe - 5 Pixel Abstand
                y_pos = MESSAGE_ZONE_Y + MESSAGE_ZONE_HEIGHT - ICON_DIMENSIONS[1] - 5
                Himage.paste(icon_to_draw, (x_pos, y_pos))

            # NEU: Initialisiere den Partial-Update-Modus vor dem Display-Aufruf
            # Sicherstellen, dass epd.init_Fast() existiert
            if hasattr(epd, 'init_Fast'):
                epd.init_Fast() # Setzt das Display in den Partial-Update-Modus
                logging.info("Display initialisiert mit init_Fast().")
            else:
                epd.init() # Fallback zu voller Initialisierung, wenn init_Fast nicht existiert
                logging.warning("init_Fast nicht gefunden. Führe Vollinitialisierung für Partial Update durch.")
            
            epd.display(epd.getbuffer(Himage)) # Aktualisiert das Display mit dem neuen Bild
            
        else: # Vollaktualisierung für IDLE oder Initialisierung
            epd.init() # Vollständige Initialisierung für Full Update
            epd.Clear(0xFF) # Weißer Hintergrund

            # Statische Informationen zeichnen
            draw_static_info(draw, weather_data)

            # Bild auf Display übertragen
            epd.display(epd.getbuffer(Himage))
            
            # Speichere das vollständige Bild für zukünftige Teilaktualisierungen
            current_display_image = Himage.copy()

        end_time = time.time()
        logging.info(f"e-Paper Update für '{status_type}' abgeschlossen in {end_time - start_time:.2f} Sekunden.")
        
        # Display nach dem Schreiben in den Schlafmodus versetzen
        epd.sleep()
        logging.info("e-Paper Display in den Schlafmodus versetzt.")

    except Exception as e:
        logging.error(f"FEHLER beim Aktualisieren des e-Paper Displays: {e}")

# --- Hauptprogramm ---
def main():
    # Icons laden (einmalig beim Start)
    load_icons()

    if not init_epd_display():
        logging.error("Display konnte nicht initialisiert werden. Programm wird beendet.")
        return

    # Initialanzeige (Vollaktualisierung)
    current_weather = get_weather_data() # Erste Abfrage der Wetterdaten
    update_epd_display_content("IDLE", weather_data=current_weather, use_partial_update=False)
    time.sleep(3) # Wartezeit nach Vollaktualisierung

    # Testsequenz der Statusmeldungen mit Teilaktualisierung
    statuses = [
        ("BEACON_DETECTED", None),
        ("ACCESS_GRANTED", "Ralf"), # Hier deinen Namen verwenden
        ("CLEAR_MESSAGE_ZONE", None), # Nachrichtenbereich leeren (um "B" oder "S" zu entfernen)
        ("IDLE", None) # Optional: Vollaktualisierung zurück zum Idle-Zustand
    ]

    for i, (status_type, person_name) in enumerate(statuses):
        logging.info(f"\n--- Test {i+1}: Anzeige von '{status_type}' ---")
        update_epd_display_content(status_type, person_name, use_partial_update=True)
        time.sleep(5) # Warte 5 Sekunden, bevor der nächste Status angezeigt wird

    logging.info("\nAlle Test-Status durchlaufen.")
    logging.info("Zeige abschließend wieder IDLE-Status (Vollaktualisierung).")
    update_epd_display_content("IDLE", weather_data=get_weather_data(), use_partial_update=False)
    time.sleep(3) # Wartezeit nach letzter Vollaktualisierung

# --- Korrekte Platzierung des try...except...finally Blocks ---
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Testprogramm durch Benutzer beendet.")
    except Exception as e:
        logging.error(f"Ein unerwarteter Fehler im Hauptprogramm ist aufgetreten: {e}")
    finally:
        cleanup_epd_display()