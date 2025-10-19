# test_radar_logic.py
import asyncio
import logging
import radar_logic
import config # radar_logic braucht config
import globals_state as gs # radar_logic braucht globals_state

# Konfiguriere minimales Logging, um Ausgaben zu sehen
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - TEST - %(levelname)s - %(message)s')

async def test_init():
    logging.info("TEST: Starte Test der radar_logic.init_radar_hardware()...")
    try:
        # Initialisiere config und globals_state, da radar_logic sie erwartet
        # config.py lädt sich selbst beim Import
        # globals_state.py initialisiert sich selbst beim Import
        
        # Fülle eine minimale config.SYSTEM_CONFIG für den Test, falls nicht schon geladen
        if config.SYSTEM_CONFIG is None:
            logging.info("TEST: config.SYSTEM_CONFIG ist None, lade Dummy-Konfiguration.")
            config.SYSTEM_CONFIG = {
                "radar_config": {
                    "uart_port": "/dev/ttyAMA2",
                    "ble_scan_max_duration": 0.5,
                    "speed_noise_threshold": 5,
                    "expected_x_sign": "negative",
                    "min_distance_to_sensor": 200,
                    "door_open_comfort_delay": 0.5,
                    "cooldown_duration": 3.0
                },
                "system_globals": {
                    "relay_activation_duration_sec": 4
                },
                "known_beacons": [],
                "auth_criteria": {}
            }

        # Rufe die Funktion auf
        await radar_logic.init_radar_hardware()
        logging.info("TEST: radar_logic.init_radar_hardware() erfolgreich.")
        
        # Optional: Teste eine Methode der RD03D_Async Instanz
        if radar_logic._radar_device:
            logging.info(f"TEST: Radar-Gerät verbunden: {radar_logic._radar_device.uart_port}")
            await radar_logic._radar_device.close() # Verbindung wieder schließen
            logging.info("TEST: Radar-Gerät geschlossen.")

    except AttributeError as e:
        logging.error(f"TEST: AttributeError beim Aufruf von radar_logic.init_radar_hardware(): {e}")
    except Exception as e:
        logging.error(f"TEST: Unerwarteter Fehler im Test: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_init())