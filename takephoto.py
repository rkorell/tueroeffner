# Program: takephoto.py
# Purpose: Skript zum automatischen Aufnehmen von Trainingsbildern für die Gesichtserkennung.
#          Erstellt oder verwaltet Ordner pro Person und speichert eine konfigurierbare
#          Anzahl von Bildern mit einer Pi Camera V3.
# Author: Dr. Ralf Korell
# Creation Date: July 25, 2025 (Updated: July 27, 2025)

import cv2
import os
import shutil
import time
import re

# Picamera2 Importe
from picamera2 import Picamera2
# from libcamera import controls # NICHT IMPORTIEREN, da wir Integer-Werte verwenden

# --- Konfiguration ---
# Basisverzeichnis für die Datensätze (wird für jede Person ein Unterordner)
DATASET_BASE_PATH = "known_faces" # Angepasst, um direkt in den "known_faces" Ordner zu speichern

# Kamera-Einstellungen
CAMERA_RESOLUTION = (640, 480) # Auflösung für die Aufnahme
SET_AUTOFOCUS = True # Setze auf True für Autofokus, False für festen Fokus

# Standardwerte für die automatische Aufnahmeserie
DEFAULT_NUM_IMAGES = 50 # Angepasst auf 50, da das die empfohlene Zahl pro Person war
DEFAULT_WAIT_MS = 250

# --- Hilfsfunktionen ---

def get_valid_input(prompt, type_func=str, default_value=None):
    """
    Hilfsfunktion, um Benutzereingaben zu validieren und Standardwerte zu unterstützen.
    Wenn der Benutzer Enter drückt, wird der Standardwert verwendet.
    """
    while True:
        display_prompt = prompt
        if default_value is not None:
            display_prompt += f" (Standard: {default_value})"
        
        user_input = input(display_prompt + ": ")

        if user_input == "" and default_value is not None:
            print(f"Standardwert '{default_value}' wird verwendet.")
            return default_value
        elif user_input == "" and default_value is None:
            print("Eingabe darf nicht leer sein.")
            continue

        try:
            value = type_func(user_input)
            if type_func == int:
                if value < 0:
                    print("Bitte eine positive Zahl eingeben.")
                    continue
            return value
        except ValueError:
            print(f"Ungültige Eingabe. Bitte geben Sie einen gültigen Wert des Typs {type_func.__name__} ein.")

# --- Hauptprogramm ---
def main():
    # --- Phase 1: Alle Parameter abfragen ---

    # 1. Name der Person abfragen und Ordner erstellen/verwalten
    person_name = get_valid_input("Bitte geben Sie den Namen der aufzunehmenden Person ein")
    person_folder_path = os.path.join(DATASET_BASE_PATH, person_name)

    img_counter = 0

    if os.path.exists(person_folder_path):
        print(f"Der Ordner '{person_folder_path}' existiert bereits.")
        while True:
            choice = get_valid_input("Möchten Sie die vorhandenen Bilder behalten (b) oder löschen (l)", str, 'b').lower()
            if choice == 'b':
                print("Vorhandene Bilder werden behalten.")
                # Maximale Numerierung ermitteln
                max_img_num = -1
                for filename in os.listdir(person_folder_path):
                    match = re.match(r"image_(\d+)\.jpg", filename)
                    if match:
                        num = int(match.group(1))
                        if num > max_img_num:
                            max_img_num = num
                img_counter = max_img_num + 1
                print(f"Die Nummerierung wird ab {img_counter} fortgesetzt.")
                break
            elif choice == 'l':
                print("Vorhandene Bilder werden gelöscht.")
                try:
                    shutil.rmtree(person_folder_path)
                    os.makedirs(person_folder_path)
                    img_counter = 0
                    print(f"Ordner '{person_folder_path}' wurde geleert.")
                    break
                except OSError as e:
                    print(f"Fehler beim Löschen des Ordners: {e}")
                    exit() # Programm beenden, wenn der Ordner nicht gelöscht werden kann
            else:
                print("Ungültige Eingabe. Bitte 'b' für behalten oder 'l' für löschen eingeben.")
    else:
        # Ordner erstellen, wenn er nicht existiert
        try:
            os.makedirs(person_folder_path)
            print(f"Ordner '{person_folder_path}' wurde erstellt.")
        except OSError as e:
            print(f"Fehler beim Erstellen des Ordners: {e}")
            exit() # Programm beenden, wenn der Ordner nicht erstellt werden kann

    # 2. Konfigurationsparameter für die automatische Aufnahmeserie abfragen
    print("\n--- Konfiguration für automatische Aufnahmeserie ---")

    num_images = get_valid_input("Anzahl der aufzunehmenden Bilder", int, DEFAULT_NUM_IMAGES)
    wait_time_ms = get_valid_input("Wartezeit zwischen den Aufnahmen in Millisekunden", int, DEFAULT_WAIT_MS)
    wait_time_sec = wait_time_ms / 1000.0 # Umrechnung in Sekunden für time.sleep()

    print(f"\nAlle Parameter eingestellt:")
    print(f"  Personenordner: {person_folder_path}")
    print(f"  Bilder pro Serie: {num_images}")
    print(f"  Wartezeit zwischen Bildern: {wait_time_ms} ms")

    # --- Phase 2: Kamera-Vorschau und Warten auf Startsignal ---

    # Kamera initialisieren mit Picamera2
    picam2 = Picamera2()
    camera_config = picam2.create_video_configuration(main={"size": CAMERA_RESOLUTION, "format": "RGB888"})
    picam2.configure(camera_config)

    try:
        picam2.start()
        time.sleep(1) # Kurze Pause, damit die Kamera bereit ist

        # Autofokus konfigurieren und starten, falls aktiviert
        if SET_AUTOFOCUS:
            picam2.set_controls({"AfMode": 2}) # NEU: 2 entspricht controls.AfMode.Continuous
            print("Kontinuierlicher Autofokus aktiviert.")
        else:
            picam2.set_controls({"AfMode": 0}) # NEU: 0 entspricht controls.AfMode.Manual
            print("Autofokus deaktiviert.")

        cv2.namedWindow("Kamera-Vorschau (Leertaste zum Starten, ESC zum Beenden)", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Kamera-Vorschau (Leertaste zum Starten, ESC zum Beenden)", 600, 400)

        print("\n--- Kamera-Vorschau gestartet ---")
        print("Richten Sie die Kamera aus.")
        print("Drücken Sie die Leertaste, um die Aufnahmeserie zu starten.")
        print("Drücken Sie ESC, um das Programm zu beenden.")

        # Vorschau-Schleife: Warten auf Leertaste
        while True:
            # Frame von Picamera2 erfassen
            frame = picam2.capture_array()
            if frame is None:
                print("Fehler: Konnte keinen Frame von der Kamera empfangen. Programm wird beendet.")
                break # Schleife verlassen, um Programm zu beenden

            # Text auf dem Bild einblenden
            text = "Leertaste druecken zum Starten"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 1
            font_thickness = 2
            text_size = cv2.getTextSize(text, font, font_scale, font_thickness)[0]
            text_x = (frame.shape[1] - text_size[0]) // 2
            text_y = (frame.shape[0] + text_size[1]) // 2

            cv2.putText(frame, text, (text_x, text_y), font, font_scale, (0, 0, 0), font_thickness + 2, cv2.LINE_AA)
            cv2.putText(frame, text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness, cv2.LINE_AA)

            cv2.imshow("Kamera-Vorschau (Leertaste zum Starten, ESC zum Beenden)", frame)

            k = cv2.waitKey(1) # Warte 1ms und prüfe auf Tastendruck

            if k % 256 == 27: # ESC-Taste
                print("Programm durch Benutzer abgebrochen.")
                break # Schleife verlassen
            elif k % 256 == 32: # Leertaste
                print("Leertaste gedrückt. Starte Aufnahmeserie...")
                break

        # --- Phase 3: Automatische Aufnahmeserie starten ---
        if k % 256 == 32: # Nur starten, wenn Leertaste gedrückt wurde
            print(f"\nStarte automatische Aufnahmeserie für '{person_name}'...")
            print(f"{num_images} Bilder werden mit einer Wartezeit von {wait_time_ms} ms aufgenommen.")
            print("Drücken Sie ESC im Fenster, um die Aufnahme vorzeitig zu beenden.")

            for i in range(num_images):
                frame = picam2.capture_array()
                if frame is None:
                    print("Fehler: Konnte keinen Frame von der Kamera empfangen während der Aufnahme.")
                    break

                # Bild speichern
                img_name = os.path.join(person_folder_path, "image_{:03d}.jpg".format(img_counter))
                cv2.imwrite(img_name, frame)
                print(f"Bild {i+1}/{num_images}: '{img_name}' wurde gespeichert.")
                img_counter += 1

                # Live-Vorschau anzeigen
                cv2.imshow("Kamera-Vorschau (Leertaste zum Starten, ESC zum Beenden)", frame) 

                # Wartezeit und ESC-Erkennung
                k = cv2.waitKey(max(1, wait_time_ms)) 
                if k % 256 == 27: # ESC-Taste
                    print("Aufnahme durch Benutzer abgebrochen.")
                    break
                
                if wait_time_ms > 0:
                    time.sleep(wait_time_sec)

            print("\nAufnahmeserie beendet.")

    except Exception as e:
        print(f"Ein Fehler ist aufgetreten: {e}")
    finally:
        # Ressourcen freigeben
        picam2.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
    