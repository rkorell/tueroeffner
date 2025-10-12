# Program: analyze_calibration_data.py
# Purpose: Analyzes raw BLE calibration data from CSV, calculates optimal
#          calibrated_measured_power and path_loss_exponent using multiple
#          regression methods, generates plots, and exports results to JSON.
# Author: CircuIT
# Creation Date: August 20, 2025

import pandas as pd
import numpy as np
import os
import glob
import json
import logging
import math
from scipy import stats # For standard linear regression
from scipy.stats import linregress # Explicitly import linregress

import matplotlib.pyplot as plt

# --- Logging Konfiguration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - ANALYZER - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("ble_calibration_analysis.log")
    ]
)

# --- KONFIGURATION ---
ALLOWED_USERS_CONFIG = "Erlaubte_Nutzer.conf"
# Standard-UUID für die Ausgabe-JSON (sollte mit der in BLE_tueroeffner.py übereinstimmen)
TARGET_IBEACON_UUID = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0"

# NEU: Option zur Steuerung der Plot-Generierung
GENERATE_PLOTS = False # Setzen Sie dies auf True, um Plots zu generieren.

# --- Hilfsfunktionen ---

def read_allowed_users_config():
    """
    Liest die Konfigurationsdatei für erlaubte Nutzer und deren Beacons ein.
    Gibt eine Liste von Dictionaries zurück, die die erwarteten Beacons repräsentieren.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, ALLOWED_USERS_CONFIG)

    expected_beacons_list = []
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = line.split(';')
                    if len(parts) < 2:
                        logging.warning(f"Ungültige Zeile in '{ALLOWED_USERS_CONFIG}': '{line}'. Erwarte mindestens Name;Status.")
                        continue
                    
                    name = parts[0].strip()
                    # Wir interessieren uns hier nur für die Major-Werte für die Identifikation
                    for i in range(2, len(parts)):
                        major_str = parts[i].strip()
                        if major_str:
                            try:
                                major_val = int(major_str)
                                expected_beacons_list.append({"name": name, "major": major_val})
                            except ValueError:
                                logging.warning(f"Ungültiger Major-Wert '{major_str}' für Nutzer '{name}' in '{ALLOWED_USERS_CONFIG}'. Ignoriere.")
        except Exception as e:
            logging.error(f"Fehler beim Lesen von '{ALLOWED_USERS_CONFIG}': {e}")
    return expected_beacons_list

def find_latest_raw_data_csv(directory="."):
    """Sucht die neueste ble_calibration_raw_data_*.csv Datei im angegebenen Verzeichnis."""
    list_of_files = glob.glob(os.path.join(directory, "ble_calibration_raw_data_*.csv"))
    if not list_of_files:
        return None
    latest_file = max(list_of_files, key=os.path.getctime)
    return latest_file

def filter_outliers_iqr(data_series, k=1.5):
    """
    Entfernt Ausreißer aus einer Pandas Series basierend auf dem Interquartilsabstand (IQR).
    Werte außerhalb von [Q1 - k*IQR, Q3 + k*IQR] werden als Ausreißer betrachtet.
    Standardmäßig ist k=1.5 (Tukey's Fences).
    """
    Q1 = data_series.quantile(0.25)
    Q3 = data_series.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - k * IQR
    upper_bound = Q3 + k * IQR
    
    filtered_series = data_series[(data_series >= lower_bound) & (data_series <= upper_bound)]
    return filtered_series

# NEU: Manuelle Implementierung des Theil-Sen-Schätzers
def theil_sen_estimator(x, y):
    """
    Berechnet Steigung und Achsenabschnitt mit dem Theil-Sen-Schätzer.
    Referenz: https://en.wikipedia.org/wiki/Theil%E2%80%93Sen_estimator
    """
    if len(x) < 2:
        return None, None

    slopes = []
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            if x[j] != x[i]: # Vermeide Division durch Null
                slopes.append((y[j] - y[i]) / (x[j] - x[i]))
    
    if not slopes: # Alle x-Werte sind gleich
        return None, None # Oder behandeln als vertikale Linie

    # Median der Steigungen ist die Theil-Sen-Steigung
    slope = np.median(slopes)

    # Median der y-Achsenabschnitte (y - slope * x) ist der Achsenabschnitt
    intercepts = y - slope * x
    intercept = np.median(intercepts)

    return slope, intercept


def calculate_regression_params(rssi_values, actual_distances, method="standard"):
    """
    Berechnet kalibrierte Measured Power und Path Loss Exponent.
    Methode: "standard" (lineare Regression) oder "theilsen" (Theil-Sen-Schätzer).
    """
    # Filter out distances <= 0 to avoid log(0)
    valid_data = pd.DataFrame({'rssi': rssi_values, 'distance': actual_distances})
    valid_data = valid_data[valid_data['distance'] > 0]

    if valid_data.empty:
        return None, None

    # Prepare data for regression: x = 10 * np.log10(valid_data['distance']), y = RSSI
    x_data = 10 * np.log10(valid_data['distance'])
    y_data = valid_data['rssi']

    if len(x_data) < 2: # Need at least 2 points for regression
        return None, None

    calibrated_n = None
    calibrated_mp = None

    try:
        if method == "standard":
            # Standard Linear Regression: y = m*x + c
            # Where y = RSSI, x = 10 * log10(distance)
            # RSSI = (-n) * (10 * log10(distance)) + measured_power
            # So, m = -n, c = measured_power
            slope, intercept, r_value, p_value, std_err = linregress(x_data, y_data) # Use linregress directly
            calibrated_n = -slope
            calibrated_mp = intercept
            logging.debug(f"Standard Regression: slope={slope:.2f}, intercept={intercept:.2f}, R^2={r_value**2:.2f}")
        elif method == "theilsen":
            # Theil-Sen Estimator (manuelle Implementierung)
            slope, intercept = theil_sen_estimator(x_data.values, y_data.values) # .values um numpy arrays zu bekommen
            if slope is None or intercept is None:
                raise ValueError("Theil-Sen-Schätzer konnte keine Steigung oder Achsenabschnitt berechnen.")
            calibrated_n = -slope
            calibrated_mp = intercept
            logging.debug(f"Theil-Sen Regression: slope={slope:.2f}, intercept={intercept:.2f}")
        else:
            logging.error(f"Unbekannte Regressionsmethode: {method}")
            return None, None
    except Exception as e:
        logging.error(f"Fehler bei der {method}-Regression: {e}")
        return None, None

    return calibrated_mp, calibrated_n

# KORREKTUR: Plot-Dateinamen verwenden Major und Minor
def generate_and_save_plot(beacon_id, data_df, standard_mp, standard_n, theilsen_mp, theilsen_n, output_dir="."):
    """
    Generiert einen Plot der RSSI-Werte gegen die logarithmierte Distanz
    und zeichnet die Regressionslinien ein.
    beacon_id ist ein Tupel (MAC, Major, Minor).
    """
    mac, major, minor = beacon_id # Entpacken des Tupels
    plt.figure(figsize=(10, 6))
    
    # Prepare data for plotting
    x_plot = 10 * np.log10(data_df['Actual_Distance_Provided'])
    y_plot = data_df['RSSI_Value']

    plt.scatter(x_plot, y_plot, label='Gemessene RSSI-Werte', alpha=0.6)

    # Plot Standard Regression Line
    if standard_mp is not None and standard_n is not None:
        # Sicherstellen, dass x_line innerhalb der Datenbereiche liegt
        x_min_plot = x_plot.min() if not x_plot.empty else -100
        x_max_plot = x_plot.max() if not x_plot.empty else 0
        x_line = np.linspace(x_min_plot, x_max_plot, 100)
        y_line_standard = -standard_n * x_line + standard_mp
        plt.plot(x_line, y_line_standard, color='red', linestyle='-', label=f'Standard Reg. (MP={standard_mp:.2f}, N={standard_n:.2f})')

    # Plot Theil-Sen Regression Line
    if theilsen_mp is not None and theilsen_n is not None:
        # Sicherstellen, dass x_line innerhalb der Datenbereiche liegt
        x_min_plot = x_plot.min() if not x_plot.empty else -100
        x_max_plot = x_plot.max() if not x_plot.empty else 0
        x_line = np.linspace(x_min_plot, x_max_plot, 100)
        y_line_theilsen = -theilsen_n * x_line + theilsen_mp
        plt.plot(x_line, y_line_theilsen, color='green', linestyle='--', label=f'Theil-Sen Reg. (MP={theilsen_mp:.2f}, N={theilsen_n:.2f})')

    plt.title(f'RSSI vs. Log-Distanz für Beacon Major: {major}, Minor: {minor}')
    plt.xlabel('10 * log10(Distanz in Metern)')
    plt.ylabel('RSSI (dBm)')
    plt.grid(True)
    plt.legend()

    # KORREKTUR: Dateiname ohne MAC-Adresse
    plot_filename = os.path.join(output_dir, f"beacon_calibration_plot_{major}_{minor}.png")
    plt.savefig(plot_filename)
    plt.close() # Close the plot to free memory
    logging.info(f"Plot für Beacon {beacon_id} gespeichert: {plot_filename}")


# --- Hauptanalysefunktion ---
def analyze_calibration_data():
    logging.info("Starte Analyse der BLE-Kalibrierungsdaten.")
    
    # 1. Neueste CSV-Datei finden
    script_dir = os.path.dirname(os.path.abspath(__file__))
    latest_csv_file = find_latest_raw_data_csv(script_dir)

    if not latest_csv_file:
        logging.error("Keine Rohdaten-CSV-Datei gefunden. Bitte zuerst Kalibrierung durchführen.")
        print("\nFEHLER: Keine Rohdaten-CSV-Datei gefunden. Bitte zuerst Kalibrierung durchführen.")
        return

    logging.info(f"Analysiere Daten aus: {latest_csv_file}")

    # 2. Rohdaten laden
    try:
        raw_df = pd.read_csv(latest_csv_file)
        if raw_df.empty:
            logging.warning("Die Rohdaten-CSV-Datei ist leer. Keine Daten zur Analyse.")
            print("\nWARNUNG: Die Rohdaten-CSV-Datei ist leer. Keine Daten zur Analyse.")
            return
        logging.info(f"Insgesamt {len(raw_df)} Rohdatenpunkte geladen.")
    except Exception as e:
        logging.error(f"Fehler beim Laden der CSV-Datei '{latest_csv_file}': {e}")
        print(f"\nFEHLER: Fehler beim Laden der CSV-Datei '{latest_csv_file}': {e}")
        return

    # 3. Daten pro Beacon und Distanz gruppieren und filtern
    # Gruppieren nach Beacon_Address, Beacon_Major, Beacon_Minor und Actual_Distance_Provided
    # und dann die RSSI-Werte für jede Gruppe sammeln
    grouped_for_filtering = raw_df.groupby(['Beacon_Address', 'Beacon_Major', 'Beacon_Minor', 'Actual_Distance_Provided'])['RSSI_Value']

    processed_beacon_data = {} # Key: (MAC, Major, Minor), Value: {'distances': [], 'rssis': []}

    for name_tuple, group in grouped_for_filtering:
        beacon_id = (name_tuple[0], name_tuple[1], name_tuple[2]) # MAC, Major, Minor
        distance = name_tuple[3] # Actual_Distance_Provided
        rssi_list = group.tolist() # List of RSSI values for this group

        rssi_series = pd.Series(rssi_list)
        
        # Filter outliers before averaging
        filtered_rssi_series = filter_outliers_iqr(rssi_series)
        
        if not filtered_rssi_series.empty:
            avg_rssi = filtered_rssi_series.mean()
            if beacon_id not in processed_beacon_data:
                processed_beacon_data[beacon_id] = {'distances': [], 'rssis': []}
            processed_beacon_data[beacon_id]['distances'].append(distance)
            processed_beacon_data[beacon_id]['rssis'].append(avg_rssi)
            logging.debug(f"Beacon {beacon_id} Distanz {distance}m: Roh={len(rssi_list)} Filtered={len(filtered_rssi_series)} Avg={avg_rssi:.2f}")
        else:
            logging.warning(f"Beacon {beacon_id} Distanz {distance}m: Nach Filterung keine gültigen RSSI-Werte übrig. Überspringe diesen Punkt.")

    if not processed_beacon_data:
        logging.warning("Nach Datenverarbeitung und Filterung keine gültigen Beacon-Daten übrig.")
        print("\nWARNUNG: Nach Datenverarbeitung und Filterung keine gültigen Beacon-Daten übrig.")
        return

    # 5. Regressionen durchführen und Ergebnisse sammeln
    calibrated_results_theilsen = []
    # calibrated_results_standard = [] # ENTFERNT: Nur noch Theil-Sen

    print("\n--- KALIBRIERUNGSERGEBNISSE ---")
    for beacon_id, data in processed_beacon_data.items():
        mac, major, minor = beacon_id
        distances = data['distances']
        rssis = data['rssis']

        if len(distances) < 2:
            logging.warning(f"Nicht genug gültige Datenpunkte für Beacon {beacon_id} nach Filterung. Überspringe Regression.")
            print(f"Beacon {beacon_id}: Nicht genug Datenpunkte für Regression nach Filterung. Übersprungen.")
            continue

        print(f"\nBeacon: MAC={mac}, Major={major}, Minor={minor}")

        # Standard Linear Regression (nur zur Anzeige, nicht mehr im Export)
        standard_mp, standard_n = calculate_regression_params(rssi_values=rssis, actual_distances=distances, method="standard")
        if standard_mp is not None and standard_n is not None:
            print(f"  Standard Regression: Measured Power={standard_mp:.2f} dBm, Path Loss Exponent={standard_n:.2f}")
        else:
            print("  Standard Regression: Konnte nicht berechnet werden.")

        # Theil-Sen Estimator
        theilsen_mp, theilsen_n = calculate_regression_params(rssi_values=rssis, actual_distances=distances, method="theilsen")
        if theilsen_mp is not None and theilsen_n is not None:
            calibrated_results_theilsen.append({
                "major": int(major), # KORREKTUR: Explizite Umwandlung zu int
                "minor": int(minor), # KORREKTUR: Explizite Umwandlung zu int
                "mac_address": str(mac), # KORREKTUR: Explizite Umwandlung zu str
                "calibrated_measured_power": float(round(theilsen_mp, 2)), # KORREKTUR: Explizite Umwandlung zu float
                "path_loss_exponent": float(round(theilsen_n, 2)) # KORREKTUR: Explizite Umwandlung zu float
            })
            print(f"  Theil-Sen Regression: Measured Power={theilsen_mp:.2f} dBm, Path Loss Exponent={theilsen_n:.2f}")
        else:
            print("  Theil-Sen Regression: Konnte nicht berechnet werden.")
        
        # 6. Plots generieren (nur wenn GENERATE_PLOTS True ist)
        if GENERATE_PLOTS:
            # Erstelle einen temporären DataFrame für den Plot, der die Original-Rohdaten (vor Mittelwertbildung) enthält
            # aber nur die für diesen Beacon und mit gefilterten RSSI-Werten
            plot_df_raw = raw_df[(raw_df['Beacon_Address'] == mac) & 
                                 (raw_df['Beacon_Major'] == major) & 
                                 (raw_df['Beacon_Minor'] == minor)].copy()
            
            # Filter die Roh-RSSI-Werte für den Plot ebenfalls mit IQR
            plot_df_filtered = plot_df_raw.groupby('Actual_Distance_Provided')['RSSI_Value'].transform(lambda x: filter_outliers_iqr(x)).dropna()
            plot_df_raw = plot_df_raw[plot_df_raw['RSSI_Value'].isin(plot_df_filtered)]

            generate_and_save_plot(beacon_id, plot_df_raw, standard_mp, standard_n, theilsen_mp, theilsen_n, script_dir)


    # 7. Ergebnisse in JSON-Dateien exportieren
    output_base_data = {
        "beacon_uuid": TARGET_IBEACON_UUID,
        "global_defaults": {
            "calibrated_measured_power": -77, # Placeholder, as these are beacon-specific
            "path_loss_exponent": 2.5
        }
    }

    # Export Theil-Sen results (primary)
    output_data_theilsen = output_base_data.copy()
    output_data_theilsen["calibrated_beacons"] = calibrated_results_theilsen
    json_path_theilsen_primary = os.path.join(script_dir, "beacon_calibration_params.json")
    # json_path_theilsen_copy = os.path.join(script_dir, "beacon_calibration_params_theilsen.json") # ENTFERNT: Kopie entfällt
    
    try:
        with open(json_path_theilsen_primary, 'w') as f:
            json.dump(output_data_theilsen, f, indent=4)
        logging.info(f"Theil-Sen Kalibrierungsparameter erfolgreich nach '{json_path_theilsen_primary}' exportiert.")
        # Create copy for clarity (ENTFERNT)
        # with open(json_path_theilsen_copy, 'w') as f:
        #     json.dump(output_data_theilsen, f, indent=4)
        # logging.info(f"Kopie der Theil-Sen Parameter nach '{json_path_theilsen_copy}' exportiert.")
    except Exception as e:
        logging.error(f"Fehler beim Export der Theil-Sen JSON-Dateien: {e}")

    # Export Standard Regression results (ENTFERNT)
    # output_data_standard = output_base_data.copy()
    # output_data_standard["calibrated_beacons"] = calibrated_results_standard
    # json_path_standard = os.path.join(script_dir, "beacon_calibration_params_standard.json")
    
    # try:
    #     with open(json_path_standard, 'w') as f:
    #         json.dump(output_data_standard, f, indent=4)
    #     logging.info(f"Standard Regression Kalibrierungsparameter erfolgreich nach '{json_path_standard}' exportiert.")
    # except Exception as e:
    #     logging.error(f"Fehler beim Export der Standard Regression JSON-Datei: {e}")

    print("\nAnalyse abgeschlossen. Ergebnisse in JSON-Dateien und Plots gespeichert.")


# --- Hauptausführung ---
if __name__ == "__main__":
    analyze_calibration_data()