# config_web_server.py
from flask import Flask, request, render_template, redirect, url_for, flash
import json
import os
import logging
import subprocess
import sys
import time
import re

# Import des Konfigurationsschemas
from config_schema import CONFIG_SCHEMA

# Konfiguration des Loggings für den Webserver
logging.basicConfig(level=logging.INFO, format='%(asctime)s - WEBSERVER - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = '311263' # Wichtig: Ersetzen Sie dies durch einen echten, zufälligen Schlüssel!

CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'system_config.json')
# MAIN_APP_SCRIPT wird nicht mehr benötigt, da die restart_main_app() Funktion entfernt wird.

# Definition des leeren Beacon-Templates
BLANK_BEACON_TEMPLATE = {
    "name": "Neuer Beacon",
    "is_allowed": True,
    "ibeacon": {
        "major": 0,
        "minor": 0
    },
    "eddystone_uid": {
        "instance_id": "000000000000"
    },
    "eddystone_url": "https://example.com",
    "mac_address": "00:00:00:00:00:00",
    "calibrated_measured_power": -77.0,
    "path_loss_exponent": 2.5
}

def load_config():
    """Lädt die aktuelle Konfiguration aus der JSON-Datei."""
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Konfigurationsdatei '{CONFIG_FILE_PATH}' nicht gefunden. Erstelle leere Konfiguration.")
        return {}
    except json.JSONDecodeError as e:
        logging.error(f"Fehler beim Parsen der Konfigurationsdatei '{CONFIG_FILE_PATH}': {e}. Lade leere Konfiguration.")
        return {}
    except Exception as e:
        logging.error(f"Unerwarteter Fehler beim Laden der Konfigurationsdatei: {e}. Lade leere Konfiguration.")
        return {}

def save_config(config_data):
    """Speichert die Konfiguration in die JSON-Datei."""
    try:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        logging.info("Konfiguration erfolgreich gespeichert.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Speichern der Konfigurationsdatei: {e}")
        return False

# Die Funktion restart_main_app() wird entfernt, wie besprochen.

@app.route('/')
def index():
    """Zeigt das Konfigurationsformular an."""
    current_config = load_config()
    return render_template('config_form.html', schema=CONFIG_SCHEMA, config=current_config, blank_beacon_template=BLANK_BEACON_TEMPLATE)

@app.route('/save_config', methods=['POST'])
def save_config_post():
    """Verarbeitet die Formularübermittlung und speichert die Konfiguration."""
    updated_config = load_config() # Start with existing config to preserve unedited parts or default structure

    # Recursive function to process schema and update config from form data
    def process_schema_and_form_data(schema_part, config_part, form_data_prefix=""):
        for key, data in schema_part.items():
            if data.get("type") == "group":
                # Ensure the nested dictionary exists in config_part
                if key not in config_part or not isinstance(config_part[key], dict):
                    config_part[key] = {}
                # Recursive call for nested groups
                process_schema_and_form_data(data["fields"], config_part[key], form_data_prefix + key + "_")
            elif data.get("type") == "json_array":
                # json_array (like known_beacons) is handled outside this recursive loop
                # as it's a special case with a single textarea
                pass
            else: # Regular field (string, number, boolean, select)
                form_field_name = form_data_prefix + key
                form_value = request.form.get(form_field_name)

                try:
                    processed_value = None
                    if data["type"] == "number":
                        if form_value == '': # Handle empty string for numbers
                            processed_value = None # Or 0, or keep existing value
                        else:
                            processed_value = float(form_value) if '.' in form_value else int(form_value)
                            # Validierung gegen min/max Werte aus dem Schema
                            if "min" in data and processed_value < data["min"]:
                                raise ValueError(f"Wert für '{data['label']}' ist zu klein (min: {data['min']}).")
                            if "max" in data and processed_value > data["max"]:
                                raise ValueError(f"Wert für '{data['label']}' ist zu groß (max: {data['max']}).")
                    elif data["type"] == "boolean":
                        # Checkboxes only send a value if checked. The hidden input sends "false" if unchecked.
                        # Request.form.get will return "true" or "false".
                        processed_value = (form_value == "true")
                    elif data["type"] == "string" or data["type"] == "select":
                        if "pattern" in data and form_value and not re.match(data["pattern"], form_value):
                            raise ValueError(f"Wert für '{data['label']}' entspricht nicht dem erwarteten Format: {data['pattern_description']}")
                        processed_value = form_value
                    
                    config_part[key] = processed_value

                except ValueError as e:
                    flash(f"Fehler bei der Validierung für '{data.get('label', form_field_name)}': {e}", "error")
                    raise # Re-raise to stop processing and redirect
                except Exception as e:
                    flash(f"Unerwarteter Fehler beim Verarbeiten von '{data.get('label', form_field_name)}': {e}", "error")
                    raise # Re-raise to stop processing and redirect

    try:
        # Process all top-level sections (groups and json_arrays)
        for section_key, section_data in CONFIG_SCHEMA.items():
            if section_data.get("type") == "group":
                if section_key not in updated_config or not isinstance(updated_config[section_key], dict):
                    updated_config[section_key] = {} # Ensure top-level group exists as a dict
                process_schema_and_form_data(section_data["fields"], updated_config[section_key], section_key + "_")
            elif section_data.get("type") == "json_array":
                # Handle json_array (like known_beacons) separately
                form_field_name = section_key # This will be "known_beacons"
                raw_json_data = request.form.get(form_field_name)
                try:
                    if raw_json_data:
                        parsed_json = json.loads(raw_json_data)
                        if not isinstance(parsed_json, list):
                            raise ValueError("Muss ein JSON-Array sein.")
                        updated_config[section_key] = parsed_json
                    else:
                        updated_config[section_key] = []
                except json.JSONDecodeError as e:
                    flash(f"Fehler im JSON-Format für '{section_data['label']}': {e}", "error")
                    return redirect(url_for('index'))
                except ValueError as e:
                    flash(f"Fehler bei der Validierung für '{section_data['label']}': {e}", "error")
                    return redirect(url_for('index'))
                except Exception as e:
                    flash(f"Unerwarteter Fehler beim Verarbeiten von '{section_data['label']}': {e}", "error")
                    return redirect(url_for('index'))

    except Exception: # Catch any re-raised exceptions from process_schema_and_form_data
        return redirect(url_for('index')) # Redirect after flashing error

    if save_config(updated_config):
        flash("Konfiguration erfolgreich gespeichert.", "success") # Geänderte Meldung
    else:
        flash("Fehler beim Speichern der Konfiguration.", "error")
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    logging.info("Starte Flask Webserver...")
    try:
        app.run(host='0.0.0.0', port=5000, debug=False) # debug=False, wie besprochen
    except KeyboardInterrupt:
        logging.info("Flask Webserver beendet durch Benutzer (Strg+C).") # Meldung für sauberes Beenden
    finally:
        logging.info("Press CTRL+C to quit") # Die von Ihnen gewünschte Meldung