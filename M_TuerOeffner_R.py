# Program: M_TuerOeffner_R.py
# Purpose: Automatisiertes Türöffnungssystem basierend auf Multi-Faktor Radar-Bewegung und BLE-Beacon-Identifikation.
#          Verwendet modulare Komponenten für Konfiguration, globalen Status, BLE, Display und Türsteuerung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 11:45 UTC - Korrektur der Fehlerbehandlung und Task-Verwaltung.
# Modified: October 17, 2025, 12:10 UTC - Korrektur: Sauberes Beenden des Hauptprogramms nach Initialisierungsfehler und Task-Cleanup.

import asyncio
import multiprocessing
import logging

# Import der modularen Komponenten
import config
import globals_state as gs
import ble_logic_R
import display_logic
import radar_logic

# --- Haupt-Asynchrone Funktion ---
async def main():
    logging.info("MAIN_R: Türöffnungssystem (Radar-Version) gestartet.")
    logging.info(f"MAIN_R: System iBeacon UUID: {config.get('system_globals.ibeacon_uuid', config.TARGET_IBEACON_UUID)}")
    logging.info(f"MAIN_R: System Eddystone Namespace ID: {config.get('system_globals.eddystone_namespace_id', config.EDDYSTONE_NAMESPACE_ID)}")

    # Variablen für Tasks, um sie im finally-Block referenzieren zu können
    display_task = None
    radar_task = None
    
    try:
        # --- Initialisierung der Module ---
        # Initialisiere BLE-Beacon-Datenstruktur
        await ble_logic_R._perform_initial_beacon_data_setup()
        
        # Initialisiere Display-Hardware
        # Wenn Display-Initialisierung fehlschlägt, wird der Fehler geloggt und das System ohne Display fortgesetzt.
        try:
            await display_logic.init_display_hardware()
            # Starte den Display-Manager-Task nur, wenn die Hardware erfolgreich initialisiert wurde
            display_task = asyncio.create_task(display_logic.display_manager_task())
            logging.info("MAIN_R: Display-Manager-Task gestartet.")
        except Exception as e:
            logging.error(f"MAIN_R: Fehler bei der Initialisierung der Display-Hardware: {e}. System läuft ohne Display.", exc_info=True)
            # gs.display bleibt None, was vom display_manager_task gehandhabt wird
        
        # Initialisiere Radar-Hardware
        # Wenn Radar-Initialisierung fehlschlägt, ist dies kritisch und das System muss beendet werden.
        await radar_logic.init_radar_hardware()
        
        # --- Starte den Radar-Master-Task (nur wenn Radar-Hardware erfolgreich initialisiert wurde) ---
        radar_task = asyncio.create_task(radar_logic.radar_master_task())
        logging.info("MAIN_R: Radar-Master-Task gestartet.")

        # Warte auf das Beenden aller Tasks (sollte im Normalfall nicht passieren, da sie Endlosschleifen sind)
        # Füge nur Tasks hinzu, die auch tatsächlich gestartet wurden
        tasks_to_gather = [t for t in [radar_task, display_task] if t is not None]
        if tasks_to_gather:
            await asyncio.gather(*tasks_to_gather)
        else:
            logging.warning("MAIN_R: Keine Haupt-Tasks gestartet. System wird beendet.")

    except asyncio.CancelledError:
        logging.info("MAIN_R: System-Tasks werden beendet (CancelledError).")
    except Exception as e:
        logging.critical(f"MAIN_R: Ein kritischer Fehler im Haupt-Loop oder bei der Initialisierung ist aufgetreten: {e}. System wird beendet.", exc_info=True)
        # Wenn ein kritischer Fehler auftritt, muss der Event-Loop beendet werden.
        # Hier wird der Fehler geloggt, und der finally-Block kümmert sich um das Aufräumen.
        # WICHTIG: Wenn hier ein Fehler auftritt, muss der Event-Loop beendet werden,
        # damit das Programm nicht hängen bleibt. asyncio.run() wird den Fehler weitergeben.
        raise # Fehler weitergeben, damit asyncio.run() ihn fängt und den Loop beendet
    finally:
        logging.info("MAIN_R: Starte Cleanup der Asyncio-Tasks...")
        # Tasks abbrechen, falls sie noch laufen
        if radar_task and not radar_task.done():
            radar_task.cancel()
        if display_task and not display_task.done():
            display_task.cancel()
        
        # Warte, bis alle Tasks tatsächlich abgeschlossen sind (mit Timeout, falls sie hängen bleiben)
        try:
            tasks_to_wait_for = [t for t in [radar_task, display_task] if t is not None and not t.done()]
            if tasks_to_wait_for:
                # Warten auf die verbleibenden Tasks mit einem Timeout
                await asyncio.wait_for(asyncio.gather(*tasks_to_wait_for, return_exceptions=True), timeout=5.0)
            logging.info("MAIN_R: Alle Asyncio-Tasks beendet.")
        except asyncio.TimeoutError:
            logging.error("MAIN_R: Timeout beim Warten auf Beendigung der Tasks. Einige Tasks hängen möglicherweise.")
        except asyncio.CancelledError:
            logging.info("MAIN_R: Asyncio-Tasks erfolgreich abgebrochen.")
        except Exception as e:
            logging.error(f"MAIN_R: Fehler beim Beenden der Asyncio-Tasks: {e}")

        # Final cleanup actions (Radar-Verbindung wird im finally-Block von radar_master_task geschlossen)
        logging.info("MAIN_R: System-Haupt-Loop beendet.")

# --- Hauptausführung ---
if __name__ == "__main__":
    multiprocessing.set_start_method('spawn', True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("MAIN_R: Programm beendet durch Benutzer (Strg+C).")
    except Exception as e:
        logging.critical(f"MAIN_R: Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        # cleanup_gpio() ist mit atexit registriert und wird automatisch aufgerufen.
        logging.info("MAIN_R: Programm beendet.")