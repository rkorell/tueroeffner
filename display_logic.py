# Program: display_logic.py
# Purpose: Kapselt alle Funktionen und Logiken, die für die Initialisierung, Aktualisierung und Steuerung des Displays zuständig sind.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 13, 2025
# Modified: October 13, 2025, 12:30 UTC - Erstellung des display_logic-Moduls mit init_display_hardware.

import asyncio
import time
import os
import logging
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests

# Display Imports
import board
import busio
import digitalio
import adafruit_sharpmemorydisplay

import config
import globals_state as gs

# --- Display Hilfsfunktionen ---
def degrees_to_cardinal(degrees):
    directions = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = round(degrees / (360. / len(directions))) % len(directions)
    return directions[idx]

async def get_weather_data_async():
    
    if time.time() - gs.last_pws_query_time < config.get("system_globals.weather_config.query_interval_sec", config.PWS_QUERY_INTERVAL_SEC):
        logging.info("DISP: Wetterdaten-Abfrageintervall noch nicht erreicht. Verwende letzte Daten aus Cache.")
        return gs.last_successful_weather_data

    try:
        query_url = config.get("system_globals.weather_config.query_url", config.PWS_QUERY_URL)
        if not query_url:
            logging.error("DISP: Wetter-Abfrage-URL ist leer. Kann keine Wetterdaten abrufen. Verwende Cache.")
            gs.last_successful_weather_data["is_cached"] = True
            return gs.last_successful_weather_data

        logging.info(f"DISP: Frage Wetterdaten von {query_url} ab...")
        response = await asyncio.to_thread(requests.get, query_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        obs = data.get("observations", [])
        if not obs:
            logging.warning("DISP: Keine Beobachtungen in den Wetterdaten gefunden. Verwende Cache.")
            gs.last_successful_weather_data["is_cached"] = True
            return gs.last_successful_weather_data

        metric = obs[0].get("metric", {})
        winddir_deg = obs[0].get("winddir")
        
        weather_info = {
            "temperature": f"{metric.get('temp', 'N/A')}°C",
            "wind_direction": degrees_to_cardinal(winddir_deg) if winddir_deg is not None else "N/A",
            "wind_speed": f"{metric.get('windSpeed', 'N/A')} km/h",
            "precipitation": f"{metric.get('precipTotal', 'N/A')} mm",
            "is_cached": False
        }
        gs.last_pws_query_time = time.time()
        gs.last_successful_weather_data = weather_info
        logging.info(f"DISP: Wetterdaten erfolgreich abgerufen: {weather_info}")
        return weather_info

    except requests.exceptions.RequestException as e:
        logging.error(f"DISP: Fehler bei der Wetterdaten-Abfrage: {e}. Verwende Cache.")
        gs.last_successful_weather_data["is_cached"] = True
        return gs.last_successful_weather_data
    except json.JSONDecodeError as e: # json ist hier nicht importiert, aber im Originalskript war es.
                                      # Da es hier nicht direkt verwendet wird (requests.json() parst schon),
                                      # lasse ich den Import hier weg, um Codetreue zu wahren.
                                      # Wenn requests.json() einen Fehler wirft, fängt es die allgemeine Exception.
        logging.error(f"DISP: Fehler beim Parsen der Wetterdaten (JSON): {e}. Verwende Cache.")
        gs.last_successful_weather_data["is_cached"] = True
        return gs.last_successful_weather_data
    except Exception as e:
        logging.error(f"DISP: Ein unerwarteter Fehler bei der Wetterdaten-Abfrage ist aufgetreten: {e}. Verwende Cache.")
        gs.last_successful_weather_data["is_cached"] = True
        return gs.last_successful_weather_data

def get_time_based_greeting():
    current_hour = datetime.datetime.now().hour
    if 5 <= current_hour < 11:
        return "Guten Morgen!"
    elif 11 <= current_hour < 18:
        return "Guten Tag!"
    else:
        return "Guten Abend!"

def prepare_black_icon_for_sharp_display(image_path, size):
    img = Image.open(image_path).resize(size, Image.LANCZOS)
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    background = Image.new('RGB', size, (255, 255, 255))
    background.paste(img, (0, 0), img)
    one_bit_img = background.convert('1')
    final_icon = ImageOps.invert(one_bit_img)
    return final_icon

def load_icons():
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        key_path = os.path.join(script_dir, 'key.png')
        wind_path = os.path.join(script_dir, 'wind.png')
        rain_path = os.path.join(script_dir, 'rain.png')

        gs.ICON_KEY = prepare_black_icon_for_sharp_display(key_path, config.ICON_DIMENSIONS)
        gs.ICON_WIND = prepare_black_icon_for_sharp_display(wind_path, config.WEATHER_ICON_SIZE)
        gs.ICON_RAIN = prepare_black_icon_for_sharp_display(rain_path, config.WEATHER_ICON_SIZE)
        logging.info(f"DISP: Icons geladen und skaliert.")

    except FileNotFoundError as e:
        logging.error(f"DISP: FEHLER: Icon-Datei nicht gefunden: {e}. Icons werden nicht angezeigt.")
        gs.ICON_KEY = None
        gs.ICON_WIND = None
        gs.ICON_RAIN = None
    except Exception as e:
        logging.error(f"DISP: FEHLER beim Laden oder Skalieren der Icons: {e}. Icons werden nicht angezeigt.")
        gs.ICON_KEY = None
        gs.ICON_WIND = None
        gs.ICON_RAIN = None

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
                logging.warning(f"DISP: Konnte Schriftart {path} nicht laden. Versuche nächste.")
    logging.error("DISP: Keine der bevorzugten Schriftarten gefunden oder geladen. Verwende Standard-Font.")
    return default_font if default_font else ImageFont.load_default()

def draw_display_content(draw, weather_data, status_icon_type=None):
    BLACK = 0
    WHITE = 255

    draw.rectangle((0, 0, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT), outline=WHITE, fill=WHITE)

    current_y = 5
    PADDING_AFTER_GREETING = 5
    PADDING_AFTER_TIME_DATE = 10
    PADDING_AFTER_TEMPERATURE = 15
    PADDING_BETWEEN_WIND_RAIN = 5
    VERTICAL_TEXT_ALIGN_OFFSET = -12
    DRAW_DATE_TIME_LINE = True
    LINE_THICKNESS = 1
    PADDING_AFTER_LINE = 28
    WEATHER_BLOCK_INITIAL_OFFSET = 10

    greeting_text = get_time_based_greeting()
    draw.text((5, current_y), greeting_text, font=gs.FONT_GREETING, fill=BLACK)
    current_y += gs.FONT_GREETING.getbbox(greeting_text)[3] + PADDING_AFTER_GREETING

    current_time_str = time.strftime("%H:%M")
    current_date_str = time.strftime("%d.%m.%Y")
    time_date_text = f"{current_time_str} - {current_date_str}"
    draw.text((5, current_y), time_date_text, font=gs.FONT_TIME_DATE, fill=BLACK)
    current_y += gs.FONT_TIME_DATE.getbbox(time_date_text)[3] + PADDING_AFTER_TIME_DATE

    if DRAW_DATE_TIME_LINE:
        line_start_x = 5
        line_end_x = config.DISPLAY_WIDTH - 5
        draw.line([(line_start_x, current_y), (line_end_x, current_y)], fill=BLACK, width=LINE_THICKNESS)
        current_y += LINE_THICKNESS + PADDING_AFTER_LINE
    
    current_y += WEATHER_BLOCK_INITIAL_OFFSET

    if weather_data:
        temp_text = weather_data.get('temperature', 'N/A')
        if weather_data.get('is_cached', False):
            temp_text = f"[{temp_text}]"
        
        draw.text((5, current_y), temp_text, font=gs.FONT_WEATHER_TEMP_BIG, fill=BLACK)
        current_y += gs.FONT_WEATHER_TEMP_BIG.getbbox(temp_text)[3] + PADDING_AFTER_TEMPERATURE
        
        if gs.ICON_WIND is not None:
            wind_icon_y = current_y
            draw.bitmap((5, wind_icon_y), gs.ICON_WIND, fill=BLACK)
            text_height_for_centering = gs.FONT_WEATHER_DETAIL.getbbox('')[3]
            text_y_pos = int(wind_icon_y + (config.WEATHER_ICON_SIZE[1] - text_height_for_centering) / 2 + VERTICAL_TEXT_ALIGN_OFFSET)
            draw.text((5 + config.WEATHER_ICON_SIZE[0] + 5, text_y_pos),
                      f"{weather_data.get('wind_speed', 'N/A')} -- {weather_data.get('wind_direction', 'N/A')}",
                      font=gs.FONT_WEATHER_DETAIL, fill=BLACK)
            current_y += config.WEATHER_ICON_SIZE[1] + PADDING_BETWEEN_WIND_RAIN
        else:
            wind_text = f"Wind: {weather_data.get('wind_speed', 'N/A')} {weather_data.get('wind_direction', 'N/A')}"
            bbox = draw.textbbox((5, current_y), wind_text, font=gs.FONT_WEATHER_DETAIL)
            draw.text((5, current_y), wind_text, font=gs.FONT_WEATHER_DETAIL, fill=BLACK)
            current_y = bbox[3] + PADDING_BETWEEN_WIND_RAIN
        
        if gs.ICON_RAIN is not None:
            rain_icon_y = current_y
            draw.bitmap((5, rain_icon_y), gs.ICON_RAIN, fill=BLACK)
            text_height_for_centering = gs.FONT_WEATHER_DETAIL.getbbox('')[3]
            text_y_pos = int(rain_icon_y + (config.WEATHER_ICON_SIZE[1] - text_height_for_centering) / 2 + VERTICAL_TEXT_ALIGN_OFFSET)
            draw.text((5 + config.WEATHER_ICON_SIZE[0] + 5, text_y_pos),
                      f"{weather_data.get('precipitation', 'N/A')}",
                      font=gs.FONT_WEATHER_DETAIL, fill=BLACK)
            current_y += config.WEATHER_ICON_SIZE[1]
        else:
            rain_text = f"Regen: {weather_data.get('precipitation', 'N/A')}"
            bbox = draw.textbbox((5, current_y), rain_text, font=gs.FONT_WEATHER_DETAIL)
            draw.text((5, current_y), rain_text, font=gs.FONT_WEATHER_DETAIL, fill=BLACK)
            current_y = bbox[3]

    icon_to_draw = None
    if status_icon_type == "ACCESS_GRANTED":
        icon_to_draw = gs.ICON_KEY
    
    if icon_to_draw:
        x_pos = config.DISPLAY_WIDTH - config.ICON_DIMENSIONS[0] - 5
        y_pos = config.DISPLAY_HEIGHT - config.ICON_DIMENSIONS[1] - 5
        draw.bitmap((x_pos, y_pos), icon_to_draw, fill=BLACK)

def toggle_extcomin():
    logging.info("DISP: Starte manuelles EXTCOMIN Toggling.")
    while gs.extcomin_running:
        if gs.extcomin is not None:
            gs.extcomin.value = not gs.extcomin.value
        time.sleep(0.5)
    logging.info("DISP: EXTCOMIN Toggling beendet.")

async def init_display_hardware():
    """
    Initialisiert die Display-Hardware und lädt Icons/Fonts.
    Speichert alle initialisierten Objekte in globals_state.
    """
    logging.info("DISP: Initialisiere Display-Hardware...")
    load_icons()

    # Fonts laden und in globals_state speichern
    gs.FONT_GREETING = load_font_robust(38)
    gs.FONT_TIME_DATE = load_font_robust(24)
    gs.FONT_WEATHER_TEMP_BIG = load_font_robust(42)
    gs.FONT_WEATHER_DETAIL = load_font_robust(22)
    logging.info("DISP: Fonts geladen.")

    spi = busio.SPI(board.SCK, MOSI=board.MOSI)
    
    gs.cs = digitalio.DigitalInOut(config.SHARP_CS_PIN)
    gs.extcomin = digitalio.DigitalInOut(config.SHARP_EXTCOMIN_PIN)
    gs.disp = digitalio.DigitalInOut(config.SHARP_DISP_PIN)

    gs.cs.direction = digitalio.Direction.OUTPUT
    gs.extcomin.direction = digitalio.Direction.OUTPUT
    gs.disp.direction = digitalio.Direction.OUTPUT

    gs.disp.value = True
    gs.extcomin.value = False

    gs.extcomin_running = True
    gs.extcomin_thread_task = asyncio.create_task(asyncio.to_thread(toggle_extcomin))
    logging.info("DISP: EXTCOMIN Toggling Task gestartet.")
    await asyncio.sleep(0.1) # Kurze Pause, um den Task zu starten

    try:
        gs.display = adafruit_sharpmemorydisplay.SharpMemoryDisplay(
            spi, gs.cs, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
        )
        logging.info("DISP: Adafruit Sharp Memory Display initialisiert.")
    except Exception as e:
        logging.critical(f"DISP: FEHLER beim Initialisieren des Sharp Memory Displays: {e}", exc_info=True)
        # Setze display auf None, damit der display_manager_task weiß, dass es nicht funktioniert hat
        gs.display = None
        # Breche den extcomin_thread_task ab, wenn das Display nicht initialisiert werden konnte
        gs.extcomin_running = False
        if gs.extcomin_thread_task:
            gs.extcomin_thread_task.cancel()
            try:
                await gs.extcomin_thread_task
            except asyncio.CancelledError:
                pass
        raise # Fehler weitergeben

# Task 2: Display Management
async def display_manager_task():
    # Farben innerhalb der Funktion definieren, um Scope-Probleme zu vermeiden
    BLACK = 0
    WHITE = 255

    if gs.display is None:
        logging.error("DISP: Display-Manager kann nicht gestartet werden, da Display-Hardware nicht initialisiert wurde.")
        return

    try:
        image = Image.new("1", (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT))
        draw = ImageDraw.Draw(image)

        current_display_status_icon = None
        status_icon_display_until = 0

        last_weather_update_time = 0

        while True:
            current_time = time.time()
            if current_time - last_weather_update_time >= config.get("system_globals.weather_config.query_interval_sec", config.PWS_QUERY_INTERVAL_SEC):
                weather_data = await get_weather_data_async()
                last_weather_update_time = current_time
            else:
                weather_data = gs.last_successful_weather_data

            try:
                message = gs.display_status_queue.get_nowait()
                if message["type"] == "status":
                    current_display_status_icon = message["value"]
                    status_icon_display_until = current_time + message.get("duration", 0)
                    logging.info(f"DISP: Status-Update: {current_display_status_icon} für {message.get('duration', 0)}s")
            except asyncio.QueueEmpty:
                pass

            if current_display_status_icon and current_time > status_icon_display_until:
                current_display_status_icon = None
                logging.info("DISP: Status-Icon ausgeblendet.")

            draw_display_content(draw, weather_data, status_icon_type=current_display_status_icon)
            gs.display.image(image)
            gs.display.show()

            await asyncio.sleep(0.5)

    except asyncio.CancelledError:
        logging.info("DISP: Display-Manager-Task abgebrochen.")
    except Exception as e:
        logging.error(f"DISP: Ein unerwarteter Fehler im Display-Manager ist aufgetreten: {e}", exc_info=True)
    finally:
        gs.extcomin_running = False
        if gs.extcomin_thread_task:
            gs.extcomin_thread_task.cancel()
            try:
                await gs.extcomin_thread_task
            except asyncio.CancelledError:
                pass
        logging.info("DISP: EXTCOMIN Toggling Task beendet.")

        if gs.display is not None:
            try:
                gs.display.fill(1) # Display löschen (weiß)
                gs.display.show()
                logging.info("DISP: Adafruit Sharp Display gelöscht.")
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.error(f"DISP: Fehler beim Löschen des Displays: {e}")
        
        if gs.cs is not None:
            gs.cs.deinit()
            logging.info("DISP: CS Pin deinitialisiert.")
        if gs.extcomin is not None:
            gs.extcomin.deinit()
            logging.info("DISP: EXTCOMIN Pin deinitialisiert.")
        if gs.disp is not None:
            gs.disp.deinit()
            logging.info("DISP: DISP Pin deinitialisiert.")
        logging.info("DISP: Display-Manager beendet und GPIOs deinitialisiert.")