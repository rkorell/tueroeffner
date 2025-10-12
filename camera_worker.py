# Program: camera_worker.py
# Purpose: Separater Prozess für Kamera- und Gesichtserkennung.
#          Kommuniziert mit dem Hauptprozess über Queues.
# Author: Dr. Ralf Korell
# Creation Date: August 15, 2025
# Modified: August 15, 2025 - Integration of Picamera2, face_recognition, and codesend logic
# Corrected: August 15, 2025 - Removed codesend call, now sends FACE_MATCH_CONFIRMED status
# Corrected: August 15, 2025 - Moved Picamera2 import inside camera_worker_process_function to avoid resource busy error
# Corrected: August 15, 2025 - Added extensive debug logging for face recognition process
# Corrected: August 15, 2025 - Moved face_recognition import to global scope for performance, stop scan after match
# Corrected: August 15, 2025 - Refined camera start/stop logic for multiple cycles, removed redundant STOP_CAMERA handling
# Corrected: August 15, 2025 - Implemented MAX_SCAN_DURATION_SEC for self-stopping scan
# Corrected: August 16, 2025, 16:30 UTC - Implemented Blackbox-Prinzip. Worker now only receives PERFORM_SCAN and returns result.
#           Removed CAMERA_STARTED/STOPPED messages. Removed STOP_SCAN handling. Adjusted logging prefixes.

import logging
import time
import os
import sys
import multiprocessing
import pickle # Für das Laden der Encodings
import numpy as np # Für face_recognition
import cv2 # Für cv2.resize

# NEU: face_recognition Import auf globaler Ebene für den Worker-Prozess (einmalige Initialisierung)
import face_recognition 

# Helper function to run face recognition (will be called within the worker process)
def _run_face_recognition_core(small_frame, known_face_encodings, known_face_names_list):
    face_locations = face_recognition.face_locations(small_frame, model="hog")
    
    if len(face_locations) == 0:
        return [] # Keine Gesichter gefunden, nichts zu tun

    face_encodings = face_recognition.face_encodings(small_frame, face_locations)
    
    results = []
    for i, face_encoding in enumerate(face_encodings):
        face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_match_index = np.argmin(face_distances)
        
        name = "Unbekannt"
        if face_distances[best_match_index] <= 0.6: # Direkte Prüfung der Toleranz
            name = known_face_names_list[best_match_index]
            logging.info(f"CAM: Bestes Match gefunden: {name} mit Distanz {face_distances[best_match_index]:.2f}")
        else:
            pass # Nichts tun, wenn kein Match

        results.append({
            "name": name,
            "face_location": face_locations[i] # Use original index for location
        })
    
    return results

def camera_worker_process_function(command_queue, result_queue, initial_config):
    """
    Diese Funktion wird als separater Prozess ausgeführt.
    Sie empfängt Befehle über command_queue und sendet Ergebnisse über result_queue.
    initial_config enthält die einmalig benötigten Konfigurationsdaten.
    """
    # Konfiguriere Logging für diesen Worker-Prozess, um seine Ausgaben zu sehen
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - CAM - %(levelname)s - %(message)s')
    logging.info("CAM: Worker-Prozess gestartet.")

    # Import Picamera2 and libcamera.controls here, inside the function,
    # so they are initialized within the worker process when needed.
    from picamera2 import Picamera2
    from libcamera import controls

    # Konfiguration entpacken
    encodings_file = initial_config['encodings_file']
    allowed_users_data = initial_config['allowed_users_data']
    camera_resolution = initial_config['camera_resolution']
    frame_resize_factor = initial_config['frame_resize_factor']
    min_detection_interval = initial_config['min_detection_interval']
    set_autofocus = initial_config['set_autofocus']
    camera_debug = initial_config['camera_debug']
    max_scan_duration_sec = initial_config['max_scan_duration_sec'] # NEU: Maximale Scan-Dauer

    # Lade die bekannten Gesichts-Encodings und Namen (jetzt im Worker-Prozess)
    known_face_encodings = []
    known_face_names = []
    try:
        logging.info(f"CAM: Lade Gesichts-Encodings von '{encodings_file}'...")
        with open(encodings_file, 'rb') as f:
            known_face_encodings, known_face_names = pickle.load(f)
        logging.info(f"CAM: {len(known_face_encodings)} Encodings von {len(set(known_face_names))} Personen geladen.")
    except FileNotFoundError:
        logging.error(f"CAM: Fehler: Die Datei '{encodings_file}' wurde nicht gefunden.")
        result_queue.put({"status": "ERROR", "message": f"Encodings-Datei '{encodings_file}' nicht gefunden."})
        return # Worker beenden
    except Exception as e:
        logging.error(f"CAM: Fehler beim Laden der Encodings: {e}")
        result_queue.put({"status": "ERROR", "message": f"Fehler beim Laden der Encodings: {e}"})
        return # Worker beenden

    picam2 = None
    camera_is_running_in_worker = False
    last_recognition_time = 0 # Für MIN_DETECTION_INTERVAL

    try:
        while True: # Äußere Schleife: Wartet auf Befehle
            # Prüfe auf Befehle vom Hauptprozess (nicht-blockierend, damit Schleife weiterläuft)
            try:
                command_message = command_queue.get_nowait()
                command = command_message.get("command")
                logging.info(f"CAM: Befehl erhalten: {command}")

                if command == "PERFORM_SCAN": # Geänderter Befehlsname
                    expected_names = command_message.get("expected_names", [])
                    logging.info(f"CAM: Befehl PERFORM_SCAN erhalten. Erwartete Namen: {expected_names}")
                    
                    if not camera_is_running_in_worker: # Nur starten, wenn Kamera nicht bereits läuft
                        try:
                            # Kamera initialisieren und starten
                            picam2 = Picamera2()
                            camera_config = picam2.create_video_configuration(main={"size": camera_resolution, "format": "RGB888"})
                            picam2.configure(camera_config)
                            picam2.start()
                            time.sleep(1) # Wartezeit für Kamera-Bereitschaft
                            if set_autofocus:
                                picam2.set_controls({"AfMode": 2}) # Numerischer Wert für Continuous Autofocus
                            camera_is_running_in_worker = True
                            logging.info("CAM: Kamera physisch gestartet.")
                        except Exception as cam_e:
                            logging.error(f"CAM: Fehler beim Starten der Kamera: {cam_e}", exc_info=True)
                            result_queue.put({"status": "ERROR", "message": f"Kamera-Startfehler: {cam_e}"})
                            # Gehe zurück zur äußeren Schleife und warte auf neuen Befehl
                            camera_is_running_in_worker = False # Setze Zustand zurück
                            picam2 = None # Stelle sicher, dass Objekt freigegeben wird
                            continue # Springe zum nächsten Schleifendurchlauf der äußeren while True Schleife
                    else:
                        logging.warning("CAM: PERFORM_SCAN Befehl erhalten, obwohl Kamera bereits läuft. Starte Scan.")
                        # Wenn Kamera bereits läuft, aber PERFORM_SCAN erneut gesendet wurde,
                        # bedeutet das, dass der Hauptprozess eine neue Erkennung anfordert.
                        # Wir müssen nur die innere Schleife erneut betreten.


                    # Haupt-Loop für Frame-Erfassung und Gesichtserkennung
                    match_found_and_reported = False
                    scan_start_time = time.time() # Zeitpunkt des Scan-Starts
                    
                    while camera_is_running_in_worker and not match_found_and_reported:
                        # Prüfe erneut auf TERMINATE Befehle, damit wir die Schleife verlassen können
                        try:
                            next_command_message = command_queue.get_nowait()
                            next_command = next_command_message.get("command")
                            if next_command == "TERMINATE":
                                logging.info("CAM: TERMINATE Befehl während des Betriebs erhalten. Beende Prozess.")
                                raise SystemExit # Beende den Worker komplett
                        except multiprocessing.queues.Empty:
                            pass # Kein neuer Befehl, weiter mit Frame

                        # Prüfe, ob Scan-Zeitlimit erreicht ist
                        if (time.time() - scan_start_time) > max_scan_duration_sec:
                            logging.info(f"CAM: Scan-Zeitlimit von {max_scan_duration_sec}s erreicht. Kein Match gefunden.")
                            result_queue.put({"status": "NO_FACE_MATCH", "reason": "ScanTimeout", "name": "N/A"})
                            break # Beende den inneren Loop (Scan-Timeout)

                        try:
                            frame = picam2.capture_array() # Frame erfassen
                            small_frame = cv2.resize(frame, (0, 0), fx=frame_resize_factor, fy=frame_resize_factor)
                            
                            # Führe Gesichtserkennung aus
                            recognition_results = _run_face_recognition_core(small_frame, known_face_encodings, known_face_names)
                            
                            if not recognition_results: # Keine Gesichter im Frame gefunden
                                pass # Nichts tun, wenn keine Gesichter gefunden
                            else:
                                for result in recognition_results:
                                    identified_name = result['name']
                                    
                                    # Überprüfe, ob die Person in der Konfiguration erlaubt ist
                                    is_allowed_in_config = allowed_users_data.get(identified_name, {}).get('allowed', False)

                                    # Überprüfe die "Gesicht-Beacon Übereinstimmung" und Konfigurationserlaubnis
                                    if identified_name in expected_names and is_allowed_in_config:
                                        if (time.time() - last_recognition_time) > min_detection_interval:
                                            logging.info(f"CAM: *** Person erkannt: {identified_name}. Match bestätigt. Melde an Hauptprozess. ***")
                                            # Sende Bestätigung an Hauptprozess, DASS ein Match gefunden wurde
                                            result_queue.put({"status": "FACE_MATCH_CONFIRMED", "name": identified_name})
                                            last_recognition_time = time.time()
                                            match_found_and_reported = True # Setze Flag, um Loop zu verlassen
                                            break # Verlasse die Schleife über die Ergebnisse, da Match gefunden
                                        else:
                                            logging.info(f"CAM: Person {identified_name} erkannt, aber MIN_DETECTION_INTERVAL noch nicht abgelaufen.")
                                    else: # Person ist unbekannt oder nicht erwartet/erlaubt
                                        if identified_name != "Unbekannt":
                                            if not is_allowed_in_config:
                                                logging.warning(f"CAM: Person erkannt: {identified_name}. Aber nicht in Konfiguration erlaubt. Zugang verweigert.")
                                                result_queue.put({"status": "NO_FACE_MATCH", "reason": "NotAllowedInConfig", "name": identified_name})
                                            elif identified_name not in expected_names:
                                                logging.warning(f"CAM: Person erkannt: {identified_name}. Aber nicht unter erwarteten Namen ({expected_names}). Zugang verweigert.")
                                                result_queue.put({"status": "NO_FACE_MATCH", "reason": "NotExpected", "name": identified_name})
                                        else:
                                            logging.info(f"CAM: Unbekanntes Gesicht erkannt.")
                                            result_queue.put({"status": "NO_FACE_MATCH", "reason": "Unknown", "name": identified_name})

                            # Kurze Pause, um CPU zu entlasten und die Schleife nicht zu schnell laufen zu lassen
                            time.sleep(0.1) # 100ms Pause zwischen Frames
                        except Exception as frame_e:
                            logging.error(f"CAM: Fehler bei Frame-Erfassung/Verarbeitung: {frame_e}", exc_info=True)
                            # Hier könnte man eine Fehler-Nachricht an den Hauptprozess senden
                            # result_queue.put({"status": "ERROR", "message": f"Frame-Fehler: {frame_e}"})
                            time.sleep(1) # Kurze Pause, um Endlosschleife bei Hardware-Fehler zu vermeiden
                            continue # Nächsten Frame versuchen
                    
                    # Kamera stoppen, wenn Scan-Loop beendet (egal ob Match oder Timeout)
                    logging.info("CAM: Scan-Loop beendet. Stoppe Kamera.")
                    if camera_is_running_in_worker:
                        picam2.stop()
                        picam2.close()
                        picam2 = None
                        camera_is_running_in_worker = False
                        logging.info("CAM: Kamera physisch gestoppt.")
                    # CAMERA_STOPPED Nachricht wird nicht mehr gesendet, da Hauptprozess dies nicht benötigt.

                elif command == "TERMINATE":
                    logging.info("CAM: Befehl TERMINATE erhalten. Beende Prozess.")
                    raise SystemExit # Beende den Worker komplett

                else:
                    logging.warning(f"CAM: Unbekannter Befehl: {command}")

            except multiprocessing.queues.Empty:
                # Kein Befehl erhalten, Worker wartet auf nächsten Befehl
                time.sleep(0.5) # Kurze Pause, um CPU zu entlasten
            
    except SystemExit: # Sauberes Beenden durch TERMINATE Befehl
        logging.info("CAM: SystemExit ausgelöst, beende sauber.")
    except Exception as e:
        logging.error(f"CAM: Ein unerwarteter Fehler ist aufgetreten: {e}", exc_info=True)
        result_queue.put({"status": "ERROR", "message": f"Worker-Fehler: {e}"})
    finally:
        # Sicherstellen, dass die Kamera auch bei Fehlern gestoppt und geschlossen wird
        if camera_is_running_in_worker and picam2:
            try:
                picam2.stop()
                picam2.close()
                logging.info("CAM: Kamera im finally gestoppt und geschlossen.")
            except Exception as fe:
                logging.error(f"CAM: Fehler beim Stoppen/Schließen der Kamera im finally-Block: {fe}")
        logging.info("CAM: Worker-Prozess beendet.")

if __name__ == '__main__':
    # Dieser Block wird nur ausgeführt, wenn camera_worker.py direkt gestartet wird,
    # nicht wenn es als Prozess von tueroeffner.py gestartet wird.
    # Nützlich für isolierte Tests.
    print("Dies ist der camera_worker.py. Er sollte normalerweise nicht direkt ausgeführt werden.")
    print("Er wird als separater Prozess von tueroeffner.py gestartet.")
    print("Für einen Test können Sie hier eine Dummy-Kommunikation einrichten.")
    # Beispiel für einen Dummy-Test:
    # from multiprocessing import Queue
    # cmd_q = Queue()
    # res_q = Queue()
    # # Dummy-Konfiguration
    # dummy_config = {
    #     'encodings_file': 'encodings.pkl', # Muss existieren für Test
    #     'allowed_users_data': {'Ralf': {'allowed': True, 'beacon_majors': [3112]}},
    #     'camera_resolution': (640, 480),
    #     'frame_resize_factor': 0.25,
    #     'min_detection_interval': 5,
    #     'codesend_path': '/usr/local/bin/codesend',
    #     'codesend_code_basis': 9128374,
    #     'codesend_min_duration_sec': 3,
    #     'relay_activation_duration_sec': 4,
    #     'set_autofocus': True,
    #     'camera_debug': True
    # }
    # worker_process = multiprocessing.Process(target=camera_worker_process_function, args=(cmd_q, res_q, dummy_config))
    # worker_process.start()
    # cmd_q.put({"command": "PERFORM_SCAN", "expected_names": ["Ralf"]})
    # print(res_q.get()) # Should print FACE_MATCH_CONFIRMED or NO_FACE_MATCH
    # # Warten auf Erkennungsergebnisse
    # time.sleep(20) # Genug Zeit für Kamera und Erkennung (über MAX_SCAN_DURATION_SEC)
    # cmd_q.put({"command": "TERMINATE"})
    # worker_process.join()
    # print("Dummy-Test beendet.")
    