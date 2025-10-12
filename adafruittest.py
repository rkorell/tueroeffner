import board
import busio
import digitalio
import time
import logging
import datetime
import os
from PIL import Image, ImageDraw, ImageFont, ImageOps
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
WEATHER_ICON_SIZE = (20, 20) # Angepasst: Größe für Wind- und Regen-Icons

# --- Icon Globale Variablen ---
ICON_EYE = None
ICON_KEY = None
ICON_WIND = None # NEU: Wind-Icon
ICON_RAIN = None # NEU: Regen-Icon

# NEUE HILFSFUNKTION FÜR ICON-VERARBEITUNG
def prepare_black_icon_for_sharp_display(image_path, size):
    """
    Lädt ein schwarzes Icon auf transparentem Hintergrund, skaliert es,
    und bereitet es für die 1-Bit-Darstellung auf dem Sharp Display vor.
    Das Ergebnis ist ein 1-Bit-Bild, bei dem 1 für Schwarz (Icon) und 0 für Weiß (Hintergrund) steht.
    """
    img = Image.open(image_path).resize(size, Image.LANCZOS)

    # Sicherstellen, dass das Bild einen Alpha-Kanal hat, um Transparenz zu handhaben
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Ein neues Bild mit weißem Hintergrund erstellen.
    # Dies ist wichtig, da convert('1') mit reiner Transparenz unvorhersehbar sein kann.
    # Wir wollen, dass transparente Bereiche zu Weiß werden.
    background = Image.new('RGB', size, (255, 255, 255)) # Weißer Hintergrund

    # Das Icon auf den weißen Hintergrund kopieren.
    # Der Alpha-Kanal des Icons sorgt für korrektes Blending.
    # Ergebnis: Schwarze Linien auf weißem Hintergrund (ohne Graustufen, da nur Schwarz und Weiß).
    # Der Alpha-Kanal des Icons wird hier als Maske verwendet, um die Transparenz korrekt zu handhaben.
    background.paste(img, (0, 0), img) 

    # Dieses Schwarz-auf-Weiß-Bild in 1-Bit konvertieren.
    # Pillow's convert('1') bildet Schwarz (0) auf 0 und Weiß (255) auf 1 ab.
    # Ergebnis nach diesem Schritt: Icon-Pixel sind 0, Hintergrund-Pixel sind 1.
    one_bit_img = background.convert('1')

    # Wir müssen dieses Bild invertieren, damit Icon-Pixel 1 und Hintergrund-Pixel 0 sind.
    # Nur so zeichnet draw.bitmap das Icon schwarz und lässt den Hintergrund weiß.
    final_icon = ImageOps.invert(one_bit_img)
    
    # Optional: Debug-Speicherung der finalen 1-Bit-Icons
    # final_icon.save(f"debug_{os.path.basename(image_path).replace('.png', '')}_final_1bit.png")

    return final_icon

def load_icons():
    global ICON_EYE, ICON_KEY, ICON_WIND, ICON_RAIN
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        eye_path = os.path.join(script_dir, 'eye.png')
        key_path = os.path.join(script_dir, 'key.png')
        wind_path = os.path.join(script_dir, 'wind.png') # NEU: Pfad für Wind-Icon
        rain_path = os.path.join(script_dir, 'rain.png') # NEU: Pfad für Regen-Icon

        # Verwenden der neuen Hilfsfunktion für alle Icons
        # Da alle Icons schwarz auf transparent sind, sollte diese Methode für alle funktionieren.
        # Die ursprünglichen eye/key Icons funktionierten, weil ihre convert('1') + invert() Kette
        # zufällig das gleiche Ergebnis lieferte wie unsere präzisere prepare_black_icon_for_sharp_display.
        ICON_EYE = prepare_black_icon_for_sharp_display(eye_path, ICON_DIMENSIONS)
        ICON_KEY = prepare_black_icon_for_sharp_display(key_path, ICON_DIMENSIONS)
        ICON_WIND = prepare_black_icon_for_sharp_display(wind_path, WEATHER_ICON_SIZE)
        ICON_RAIN = prepare_black_icon_for_sharp_display(rain_path, WEATHER_ICON_SIZE) # Korrigierter Funktionsname

        logging.info(f"Icons geladen und auf {ICON_DIMENSIONS} / {WEATHER_ICON_SIZE} skaliert.")

    except FileNotFoundError as e:
        logging.error(f"FEHLER: Icon-Datei nicht gefunden: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None
        ICON_WIND = None
        ICON_RAIN = None
    except Exception as e:
        logging.error(f"FEHLER beim Laden oder Skalieren der Icons: {e}. Icons werden nicht angezeigt.")
        ICON_EYE = None
        ICON_KEY = None
        ICON_WIND = None
        ICON_RAIN = None

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

# Angepasste Schriftgrößen für das neue Layout (größer)
FONT_GREETING = load_font_robust(38) # Für Begrüßung
FONT_TIME_DATE = load_font_robust(24) # Für Uhrzeit und Datum
FONT_WEATHER_TEMP_BIG = load_font_robust(42) # Für Temperatur
FONT_WEATHER_DETAIL = load_font_robust(22) # Für Wind/Niederschlag

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
    """Zeichnet den gesamten Displayinhalt mit relativer Positionierung."""
    
    # Hintergrund löschen (weiß)
    draw.rectangle((0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT), outline=WHITE, fill=WHITE)

    # Define vertical layout parameters
    current_y = 5 # Initial Y position (padding from top edge)

    # Define paddings between elements (these can be adjusted for visual spacing)
    PADDING_AFTER_GREETING = 5
    PADDING_AFTER_TIME_DATE = 10
    # User requested more space between temperature and weather icons/text
    PADDING_AFTER_TEMPERATURE = 15 # Erhöht, um Icons weiter nach unten zu verschieben
    PADDING_BETWEEN_WIND_RAIN = 5

    # Define a vertical adjustment for text alignment next to icons
    VERTICAL_TEXT_ALIGN_OFFSET = -12 # User's current fine-tuning

    # NEU: Konfigurationsparameter für die horizontale Linie und den Wetterblock-Offset
    DRAW_DATE_TIME_LINE = True # Setzen Sie dies auf False, um die Linie zu deaktivieren
    LINE_THICKNESS = 1
    PADDING_AFTER_LINE = 28 # Abstand nach der Linie
    WEATHER_BLOCK_INITIAL_OFFSET = 10 # Zusätzlicher Offset für den gesamten Wetterblock

    # Zeile 1: Begrüßung (linksbündig)
    greeting_text = get_time_based_greeting()
    draw.text((5, current_y), greeting_text, font=FONT_GREETING, fill=BLACK)
    # Aktualisiere current_y für das nächste Element
    current_y += FONT_GREETING.getbbox(greeting_text)[3] + PADDING_AFTER_GREETING

    # Zeile 2: Uhrzeit - Datum (linksbündig)
    current_time = time.strftime("%H:%M")
    current_date = time.strftime("%d.%m.%Y")
    time_date_text = f"{current_time} - {current_date}"
    draw.text((5, current_y), time_date_text, font=FONT_TIME_DATE, fill=BLACK)
    # Aktualisiere current_y für das nächste Element
    current_y += FONT_TIME_DATE.getbbox(time_date_text)[3] + PADDING_AFTER_TIME_DATE

    # NEU: Horizontale Linie unter Uhrzeit/Datum
    if DRAW_DATE_TIME_LINE:
        # draw.line(xy, fill=None, width=0)
        # xy ist eine Liste von (x,y) Tupeln, z.B. [(x1,y1), (x2,y2)]
        line_start_x = 5
        line_end_x = DISPLAY_WIDTH - 5 # 5 Pixel vom rechten Rand
        draw.line([(line_start_x, current_y), (line_end_x, current_y)], fill=BLACK, width=LINE_THICKNESS)
        current_y += LINE_THICKNESS + PADDING_AFTER_LINE
    
    # NEU: Zusätzlicher Offset für den gesamten Wetterblock
    current_y += WEATHER_BLOCK_INITIAL_OFFSET

    # Wetterinformationen (linksbündig)
    if weather_data:
        temp_text = weather_data.get('temperature', 'N/A')
        if weather_data.get('is_cached', False):
            temp_text = f"[{temp_text}]"
        
        draw.text((5, current_y), temp_text, font=FONT_WEATHER_TEMP_BIG, fill=BLACK)
        # Aktualisiere current_y für das nächste Element
        current_y += FONT_WEATHER_TEMP_BIG.getbbox(temp_text)[3] + PADDING_AFTER_TEMPERATURE
        
        # NEU: Wind-Icon und Text
        if ICON_WIND is not None:
            wind_icon_y = current_y # Icon startet an der aktuellen Y-Position
            draw.bitmap((5, wind_icon_y), ICON_WIND, fill=BLACK) # Icon linksbündig

            # Berechnung der Y-Position für den Text zur vertikalen Zentrierung
            text_height_for_centering = FONT_WEATHER_DETAIL.getbbox('')[3]
            text_y_pos = int(wind_icon_y + (WEATHER_ICON_SIZE[1] - text_height_for_centering) / 2 + VERTICAL_TEXT_ALIGN_OFFSET)

            draw.text((5 + WEATHER_ICON_SIZE[0] + 5, text_y_pos),
                      f"{weather_data.get('wind_speed', 'N/A')} -- {weather_data.get('wind_direction', 'N/A')}",
                      font=FONT_WEATHER_DETAIL, fill=BLACK)
            # current_y wird um die Höhe des Icons + Padding aktualisiert
            current_y += WEATHER_ICON_SIZE[1] + PADDING_BETWEEN_WIND_RAIN
        else:
            # KORRIGIERT: Verwende draw.textbbox für präzise Y-Aktualisierung
            wind_text = f"Wind: {weather_data.get('wind_speed', 'N/A')} {weather_data.get('wind_direction', 'N/A')}"
            bbox = draw.textbbox((5, current_y), wind_text, font=FONT_WEATHER_DETAIL)
            draw.text((5, current_y), wind_text, font=FONT_WEATHER_DETAIL, fill=BLACK)
            current_y = bbox[3] + PADDING_BETWEEN_WIND_RAIN # Setze current_y auf den unteren Rand des Textes + Padding
        
        # NEU: Regen-Icon und Text
        if ICON_RAIN is not None:
            rain_icon_y = current_y # Icon startet an der aktuellen Y-Position
            draw.bitmap((5, rain_icon_y), ICON_RAIN, fill=BLACK) # Icon linksbündig

            # Berechnung der Y-Position für den Text zur vertikalen Zentrierung
            text_height_for_centering = FONT_WEATHER_DETAIL.getbbox('')[3]
            text_y_pos = int(rain_icon_y + (WEATHER_ICON_SIZE[1] - text_height_for_centering) / 2 + VERTICAL_TEXT_ALIGN_OFFSET)

            draw.text((5 + WEATHER_ICON_SIZE[0] + 5, text_y_pos),
                      f"{weather_data.get('precipitation', 'N/A')}",
                      font=FONT_WEATHER_DETAIL, fill=BLACK)
            # current_y wird um die Höhe des Icons aktualisiert (kein Padding danach, da es das letzte Wetterelement ist)
            current_y += WEATHER_ICON_SIZE[1]
        else:
            # KORRIGIERT: Verwende draw.textbbox für präzise Y-Aktualisierung
            rain_text = f"Regen: {weather_data.get('precipitation', 'N/A')}"
            bbox = draw.textbbox((5, current_y), rain_text, font=FONT_WEATHER_DETAIL)
            draw.text((5, current_y), rain_text, font=FONT_WEATHER_DETAIL, fill=BLACK)
            current_y = bbox[3] # Setze current_y auf den unteren Rand des Textes
            # Hinweis: Hier kein PADDING_BETWEEN_WIND_RAIN, da dies das letzte Element des Wetterblocks ist.

    # Status Icon (rechts unten)
    # Dieses Icon ist fest an der rechten unteren Ecke positioniert und wird nicht vom "Fluss" beeinflusst.
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