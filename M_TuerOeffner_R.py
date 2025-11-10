# Program: M_TuerOeffner_R.py
# Purpose: Automatisiertes Türöffnungssystem basierend auf Multi-Faktor Radar-Bewegung und BLE-Beacon-Identifikation.
#          Verwendet modulare Komponenten für Konfiguration, globalen Status, BLE, Display und Türsteuerung.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 16, 2025
# Modified: October 17, 2025, 11:45 UTC - Korrektur der Fehlerbehandlung und Task-Verwaltung.
# Modified: October 17, 2025, 12:10 UTC - Korrektur: Sauberes Beenden des Hauptprogramms nach Initialisierungsfehler und Task-Cleanup.
# Modified: November 07, 2025, 15:05 UTC - Logging-Refactor: Benannter Logger, Präfixe entfernt, redundante Log-Konfig entfernt.
# Modified: November 09, 2025, 13:55 UTC - Anpassung an neue Task-Struktur von radar_logic.py (reader/logic).

import asyncio
import multiprocessing
import logging

# Import der modularen Komponenten
import config
import globals_state as gs
import ble_logic_R
import display_logic
import radar_logic
import sys
import shutil
from pathlib import Path

# NEU: Benannter Logger (Phase 3.5)
log = logging.getLogger(__name__)

# Cache vor dem Start löschen
def clear_pycache():
    project_dir = Path(__file__).parent
    for pycache in project_dir.rglob('__pycache__'):
        shutil.rmtree(pycache, ignore_errors=True)
    log.info("Bytecode-Cache gelöscht.") # Logging-Aufruf angepasst

# HINWEIS: Redundante Konfiguration entfernt, da dies nun von config.py gehandhabt wird.

# --- Haupt-Asynchrone Funktion ---
async def main():
    log.info("Türöffnungssystem (Radar-Version) gestartet.")
    #log.info(f"System iBeacon UUID: {config.get('system_globals.ibeacon_uuid', config.TARGET_IBEACON_UUID)}")
    #log.info(f"System Eddystone Namespace ID: {config.get('system_globals.eddystone_namespace_id', config.EDDYSTONE_NAMESPACE_ID)}")

    # Variablen für Tasks, um sie im finally-Block referenzieren zu können
    display_task = None
    radar_reader_task = None # NEU
    radar_logic_task = None  # NEU
    
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
            log.info("Display-Manager-Task gestartet.")
        except Exception as e:
            log.error(f"Fehler bei der Initialisierung der Display-Hardware: {e}. System läuft ohne Display.", exc_info=True)
            # gs.display bleibt None, was vom display_manager_task gehandhabt wird
        
        # Initialisiere Radar-Hardware
        # Wenn Radar-Initialisierung fehlschlägt, ist dies kritisch und das System muss beendet werden.
        await radar_logic.init_radar_hardware()
        
        # --- Starte die neuen Radar-Tasks (Leser und Logik getrennt) ---
        radar_reader_task = asyncio.create_task(radar_logic.radar_reader_task())
        radar_logic_task = asyncio.create_task(radar_logic.radar_logic_task())
        log.info("Radar Reader und Logic Tasks gestartet.")

        # Warte auf das Beenden aller Tasks (sollte im Normalfall nicht passieren, da sie Endlosschleifen sind)
        # Füge nur Tasks hinzu, die auch tatsächlich gestartet wurden
        tasks_to_gather = [t for t in [radar_reader_task, radar_logic_task, display_task] if t is not None]
        if tasks_to_gather:
            await asyncio.gather(*tasks_to_gather)
        else:
            log.warning("Keine Haupt-Tasks gestartet. System wird beendet.")

    except asyncio.CancelledError:
        log.info("System-Tasks werden beendet (CancelledError).")
    except Exception as e:
        log.critical(f"Ein kritischer Fehler im Haupt-Loop oder bei der Initialisierung ist aufgetreten: {e}. System wird beendet.", exc_info=True)
        # Wenn ein kritischer Fehler auftritt, muss der Event-Loop beendet werden.
        # Hier wird der Fehler geloggt, und der finally-Block kümmert sich um das Aufräumen.
        # WICHTIG: Wenn hier ein Fehler auftritt, muss der Event-Loop beendet werden,
        # damit das Programm nicht hängen bleibt. asyncio.run() wird den Fehler weitergeben.
        raise # Fehler weitergeben, damit asyncio.run() ihn fängt und den Loop beendet
    finally:
        log.info("Starte Cleanup der Asyncio-Tasks...")
        # Tasks abbrechen, falls sie noch laufen
        if radar_reader_task and not radar_reader_task.done():
            radar_reader_task.cancel()
        if radar_logic_task and not radar_logic_task.done():
            radar_logic_task.cancel()
        if display_task and not display_task.done():
            display_task.cancel()
        
        # Warte, bis alle Tasks tatsächlich abgeschlossen sind (mit Timeout, falls sie hängen bleiben)
        try:
            tasks_to_wait_for = [t for t in [radar_reader_task, radar_logic_task, display_task] if t is not None and not t.done()]
            if tasks_to_wait_for:
                # Warten auf die verbleibenden Tasks mit einem Timeout
                await asyncio.wait_for(asyncio.gather(*tasks_to_wait_for, return_exceptions=True), timeout=5.0)
            log.info("Alle Asyncio-Tasks beendet.")
        except asyncio.TimeoutError:
            log.error("Timeout beim Warten auf Beendigung der Tasks. Einige Tasks hängen möglicherweise.")
        except asyncio.CancelledError:
            log.info("Asyncio-Tasks erfolgreich abgebrochen.")
        except Exception as e:
            log.error(f"Fehler beim Beenden der Asyncio-Tasks: {e}")

        # Final cleanup actions (Radar-Verbindung wird im finally-Block von radar_reader_task geschlossen)
        log.info("System-Haupt-Loop beendet.")

# --- Hauptausführung ---
if __name__ == "__main__":
    clear_pycache()
    multiprocessing.set_start_method('spawn', True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Programm beendet durch Benutzer (Strg+C).")
    except Exception as e:
        log.critical(f"Ein kritischer Fehler ist aufgetreten: {e}", exc_info=True)
    finally:
        # cleanup_gpio() ist mit atexit registriert und wird automatisch aufgerufen.
        log.info("Programm beendet.")