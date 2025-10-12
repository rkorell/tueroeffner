# Program: training.py
# Purpose: Skript zum Anlernen von Gesichts-Encodings für die Gesichtserkennung.
#          Liest Bilder aus benannten Unterverzeichnissen, berechnet Gesichts-Encodings
#          und speichert diese zusammen mit den Namen. Aktualisiert zudem eine
#          Konfigurationsdatei für erlaubte Nutzer.
# Author: Dr. Ralf Korell
# Creation Date: July 25, 2025

import face_recognition
import os
import pickle
import cv2 # Wird oft für Bildverarbeitung mit face_recognition verwendet
import time # Für sleep, falls nötig

# --- Konfiguration ---
KNOWN_FACES_DIR = "known_faces" # Das Verzeichnis, das die Unterverzeichnisse mit den Bildern enthält
ENCODINGS_FILE = "encodings.pkl" # Der Dateiname, in dem die trainierten Encodings gespeichert werden
ALLOWED_USERS_CONFIG = "Erlaubte_Nutzer.conf" # Konfigurationsdatei für erlaubte Nutzer

# --- Hilfsfunktionen für Konfigurationsdatei ---
def read_allowed_users_config():
    """Liest die Konfigurationsdatei für erlaubte Nutzer ein."""
    allowed_users = {}
    if os.path.exists(ALLOWED_USERS_CONFIG):
        try:
            with open(ALLOWED_USERS_CONFIG, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and ';' in line:
                        name, status = line.split(';', 1)
                        allowed_users[name.strip()] = status.strip().lower()
        except Exception as e:
            print(f"Warnung: Fehler beim Lesen von '{ALLOWED_USERS_CONFIG}': {e}")
    return allowed_users

def write_allowed_users_config(allowed_users_data):
    """Schreibt die Konfigurationsdaten in die Datei für erlaubte Nutzer."""
    try:
        with open(ALLOWED_USERS_CONFIG, 'w') as f:
            for name, status in allowed_users_data.items():
                f.write(f"{name};{status}\n")
        print(f"'{ALLOWED_USERS_CONFIG}' aktualisiert.")
    except Exception as e:
        print(f"Fehler beim Schreiben von '{ALLOWED_USERS_CONFIG}': {e}")

# --- Hauptfunktion zum Anlernen ---
def train_face_recognition_model(known_faces_directory, encodings_output_file, allowed_users_config_file):
    """
    Trainiert das Gesichtserkennungsmodell, indem es Gesichts-Encodings aus Bildern berechnet
    und diese in einer Datei speichert. Aktualisiert auch die Konfigurationsdatei für erlaubte Nutzer.

    Args:
        known_faces_directory (str): Pfad zum Verzeichnis, das Unterverzeichnisse
                                     mit Bildern von bekannten Personen enthält.
        encodings_output_file (str): Pfad zur Datei, in der die Gesichts-Encodings
                                     und Namen gespeichert werden sollen.
        allowed_users_config_file (str): Pfad zur Konfigurationsdatei für erlaubte Nutzer.
    """
    print(f"Starte das Anlernen der Gesichter aus '{known_faces_directory}'...")

    known_face_encodings = []
    known_face_names = []
    
    # Lese aktuelle Konfiguration der erlaubten Nutzer
    current_allowed_users = read_allowed_users_config()

    # Durchlaufe jedes Unterverzeichnis im Hauptverzeichnis
    for person_name in os.listdir(known_faces_directory):
        person_dir = os.path.join(known_faces_directory, person_name)

        # Überspringe Dateien, die keine Verzeichnisse sind
        if not os.path.isdir(person_dir):
            continue

        print(f"\nVerarbeite Bilder für: {person_name}")
        image_count = 0
        faces_found_count = 0

        # Durchlaufe jedes Bild im Personen-Unterverzeichnis
        for filename in os.listdir(person_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                image_path = os.path.join(person_dir, filename)
                image_count += 1

                try:
                    # Lade das Bild
                    image = face_recognition.load_image_file(image_path)

                    # Finde alle Gesichter im Bild
                    face_locations = face_recognition.face_locations(image, model="hog")
                    
                    # Berechne die Gesichts-Encodings für die gefundenen Gesichter
                    encodings = face_recognition.face_encodings(image, face_locations)

                    if len(encodings) > 0:
                        for encoding in encodings:
                            known_face_encodings.append(encoding)
                            known_face_names.append(person_name)
                        faces_found_count += len(encodings)
                    else:
                        print(f"    Kein Gesicht im Bild '{filename}' gefunden. Überspringe.")

                except Exception as e:
                    print(f"Fehler beim Verarbeiten von '{filename}': {e}")
        
        if image_count == 0:
            print(f"Keine unterstützten Bilddateien im Verzeichnis '{person_name}' gefunden.")
        elif faces_found_count == 0:
            print(f"WARNUNG: Keine Gesichter in den Bildern für '{person_name}' gefunden. Überprüfen Sie die Bilder.")
        else:
            # Wenn Gesichter für diese Person gefunden wurden, füge sie zur Konfigurationsdatei hinzu
            if person_name not in current_allowed_users:
                current_allowed_users[person_name] = 'wahr'
                print(f"  Person '{person_name}' zu '{allowed_users_config_file}' hinzugefügt mit Status 'wahr'.")
            else:
                print(f"  Person '{person_name}' bereits in '{allowed_users_config_file}' vorhanden. Status bleibt '{current_allowed_users[person_name]}'.")


    # Speichere die gesammelten Encodings und Namen in einer Datei
    if known_face_encodings:
        with open(encodings_output_file, 'wb') as f:
            pickle.dump((known_face_encodings, known_face_names), f)
        print(f"\nAnlernen abgeschlossen! {len(known_face_encodings)} Gesichts-Encodings von {len(set(known_face_names))} Personen gespeichert in '{encodings_output_file}'.")
    else:
        print("\nKeine Gesichts-Encodings zum Speichern gefunden. Überprüfen Sie Ihre Eingabedaten.")
    
    # Schreibe die aktualisierte Konfiguration der erlaubten Nutzer zurück
    write_allowed_users_config(current_allowed_users)

# --- Ausführung des Skripts ---
if __name__ == "__main__":
    # Erstellen Sie ein Beispielverzeichnis, falls es nicht existiert
    if not os.path.exists(KNOWN_FACES_DIR):
        os.makedirs(os.path.join(KNOWN_FACES_DIR, "Max_Mustermann"))
        os.makedirs(os.path.join(KNOWN_FACES_DIR, "Erika_Musterfrau"))
        print(f"Beispielverzeichnis '{KNOWN_FACES_DIR}' erstellt. Bitte legen Sie Bilder in den Unterverzeichnissen ab.")
        print("Beispiel: ./known_faces/Max_Mustermann/max_1.jpg, ./known_faces/Erika_Musterfrau/erika_1.png")
        print("Skript wird beendet. Bitte Bilder hinzufügen und erneut ausführen.")
        time.sleep(5) 
    else:
        train_face_recognition_model(KNOWN_FACES_DIR, ENCODINGS_FILE, ALLOWED_USERS_CONFIG)