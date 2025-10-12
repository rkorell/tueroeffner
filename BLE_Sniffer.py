# Program: BLE_Sniffer.py
# Purpose: Standalone tool to sniff and display raw BLE advertising data from iBeacons.
#          Helps in identifying additional data fields for enhanced security.
# Author: Your Name / CircuIT
# Creation Date: August 16, 2025
# Modified: August 16, 2025 - Initial implementation as a dedicated BLE sniffer.

import asyncio
import time
import os
import tkinter as tk
from tkinter import ttk, scrolledtext
import logging
import struct

# BLE Imports
from bleak import BleakScanner

# --- Logging Konfiguration für den Sniffer ---
# basicConfig wird einmal aufgerufen, um den Root-Logger für die Konsole zu konfigurieren.
# Der GuiLogHandler wird separat hinzugefügt, um in das Textfeld zu schreiben.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - BLE - %(levelname)s - %(message)s')

class GuiLogHandler(logging.Handler):
    def __init__(self, text_widget, root_widget):
        super().__init__()
        self.text_widget = text_widget
        self.root_widget = root_widget

    def emit(self, record):
        msg = self.format(record)
        if self.text_widget.winfo_exists():
            self.root_widget.after(0, self._update_text_widget, msg)

    def _update_text_widget(self, msg):
        if self.text_widget.winfo_exists():
            self.text_widget.config(state='normal')
            self.text_widget.insert(tk.END, msg + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.config(state='disabled')

# --- Globale Variablen für den BLE Scan ---
beacon_last_seen_data = {} # Stores for each Beacon: {'timestamp': time.time(), 'mac': mac_addr, 'major': major_val, 'minor': minor_val, 'rssi': rssi_val, 'distance': distance}
# ble_scan_active will be an instance attribute of BLESnifferGUI
# calibration_running is removed

# --- KONFIGURATION (kopiert und angepasst aus tueroeffner.py) ---
# Diese Werte dienen der Filterung und grundlegenden Distanzschätzung.

# BLE iBeacon Konfiguration
TARGET_IBEACON_UUID = "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0" # UUID ist für alle Minew Beacons identisch
CALIBRATED_MEASURED_POWER_DEFAULT = -77 # Kalibrierter Measured Power (Tx Power @ 1m vom Beacon)
PATH_LOSS_EXPONENT_DEFAULT = 2.5 # Pfadverlust-Exponent (N): Typischerweise 2.0 für freie Sicht, 2.5-4.0 für Innenräume.

# Debouncing Konfiguration (für interne Bereinigung der Beacon-Liste)
ABSENCE_DETECTION_TIME = 10 # Sekunden: Zeit, die der Beacon nicht erkannt werden darf, um als "nicht anwesend" zu gelten

# Konfigurationsdatei für erlaubte Nutzer und deren Beacons (für allowed_majors)
ALLOWED_USERS_CONFIG = "Erlaubte_Nutzer.conf"
BLE_SCAN_INTERVAL_SEC = 1.0 # Sekunden Intervall für den BLE-Scan

# --- Hilfsfunktionen (kopiert aus tueroeffner.py) ---

def cleanup_gpio():
    """Räumt die GPIO-Einstellungen auf."""
    try:
        import RPi.GPIO as GPIO
        if GPIO.getmode() is not None:
            GPIO.cleanup()
            logging.info("GPIO aufgeräumt.")
    except ImportError:
        logging.warning("RPi.GPIO nicht importierbar, überspringe GPIO-Cleanup.")

def bytes_to_uuid(b):
    return f"{b[0:4].hex()}-{b[4:6].hex()}-{b[6:8].hex()}-{b[8:10].hex()}-{b[10:16].hex()}".upper()

def estimate_distance(rssi, measured_power, n):
    if rssi == 0:
        return -1.0
    return 10 ** ((measured_power - rssi) / (10 * n))

def read_allowed_users_config():
    """
    Liest die Konfigurationsdatei für erlaubte Nutzer und ihre Beacon-Majors ein.
    Format: Name;wahr/falsch;Major1;Major2;Major3
    """
    allowed_users = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, ALLOWED_USERS_CONFIG)

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'): # Kommentare und leere Zeilen ignorieren
                        continue
                    
                    parts = line.split(';')
                    if len(parts) < 2:
                        logging.warning(f"Ungültige Zeile in '{ALLOWED_USERS_CONFIG}': '{line}'. Erwarte mindestens Name;Status.")
                        continue
                    
                    name = parts[0].strip()
                    status_str = parts[1].strip().lower()
                    allowed = (status_str == 'wahr')
                    
                    beacon_majors = []
                    # Lese Major-Werte ab dem dritten Feld
                    for i in range(2, len(parts)):
                        major_str = parts[i].strip()
                        if major_str:
                            try:
                                beacon_majors.append(int(major_str))
                            except ValueError:
                                logging.warning(f"Ungültiger Major-Wert '{major_str}' für Nutzer '{name}' in '{ALLOWED_USERS_CONFIG}'. Ignoriere.")
                    
                    allowed_users[name] = {
                        'allowed': allowed,
                        'beacon_majors': beacon_majors
                    }
        except Exception as e:
            logging.error(f"Fehler beim Lesen von '{ALLOWED_USERS_CONFIG}': {e}")
    return allowed_users

# --- GUI-Klasse ---
class BLESnifferGUI:
    def __init__(self, root, loop):
        self.root = root
        self.loop = loop # The asyncio event loop
        self.root.title("BLE Sniffer")
        self.root.geometry("800x700")

        self.ble_scan_active = False # Flag to control the BLE scan asyncio task
        self.allowed_majors = self._get_allowed_majors()

        self._create_widgets()
        self._setup_logging_to_gui()

        # Bind the window close event to our cleanup function
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Start the periodic asyncio runner
        self._periodic_asyncio_run_id = self.root.after(10, self._periodic_asyncio_run)


    def _get_allowed_majors(self):
        allowed_users_data = read_allowed_users_config()
        majors = set()
        for user_data in allowed_users_data.values():
            if user_data['allowed']:
                majors.update(user_data['beacon_majors'])
        logging.info(f"Erlaubte Major-Werte für BLE-Filterung: {majors}")
        return majors

    def _create_widgets(self):
        # Frame for controls
        control_frame = ttk.LabelFrame(self.root, text="Steuerung")
        control_frame.pack(padx=10, pady=10, fill="x")

        self.start_button = ttk.Button(control_frame, text="Start BLE Scan", command=self.start_ble_scan)
        self.start_button.pack(side="left", padx=5, pady=5)

        self.stop_button = ttk.Button(control_frame, text="Stop BLE Scan", command=self.stop_ble_scan)
        self.stop_button.pack(side="left", padx=5, pady=5)
        self.stop_button.config(state="disabled") # Initially disabled

        # Frame for raw data display
        data_frame = ttk.LabelFrame(self.root, text="Erkannte Beacons (Live)")
        data_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self.data_listbox = scrolledtext.ScrolledText(data_frame, height=10, state='disabled')
        self.data_listbox.pack(padx=5, pady=5, fill="both", expand=True)

        # Frame for log output
        log_frame = ttk.LabelFrame(self.root, text="Log-Ausgabe (Raw Advertising Data)")
        log_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, state='disabled')
        self.log_text.pack(padx=5, pady=5, fill="both", expand=True)

    def _setup_logging_to_gui(self):
        gui_handler = GuiLogHandler(self.log_text, self.root)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - BLE - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(gui_handler)
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, "GUI-Logging gestartet.\n")
        self.log_text.config(state='disabled')

    async def _run_ble_scan_task(self):
        self.ble_scan_active = True 
        logging.info("BLE Scan Task gestartet.")

        def detection_callback(device, advertisement_data):
            rssi_val = advertisement_data.rssi
            
            # Filter for iBeacon format (0x0215) within manufacturer data (0x004C for Apple)
            if 0x004C in advertisement_data.manufacturer_data:
                mfg_data = advertisement_data.manufacturer_data[0x004C]
                
                if len(mfg_data) >= 23 and mfg_data[0] == 0x02 and mfg_data[1] == 0x15:
                    try:
                        uuid_bytes, major_val, minor_val, measured_power = struct.unpack_from(">16sHHb", mfg_data, 2)
                    except struct.error:
                        return

                    uuid_str = bytes_to_uuid(uuid_bytes)

                    # Only process beacons with allowed major values
                    if uuid_str == TARGET_IBEACON_UUID and major_val in self.allowed_majors:
                        distance = estimate_distance(rssi_val, CALIBRATED_MEASURED_POWER_DEFAULT, PATH_LOSS_EXPONENT_DEFAULT)
                        
                        beacon_info = {
                            'timestamp': time.time(),
                            'mac': device.address,
                            'major': major_val,
                            'minor': minor_val,
                            'rssi': rssi_val,
                            'distance': distance
                        }
                        beacon_last_seen_data[device.address] = beacon_info

                        # Update GUI data listbox
                        self.root.after(0, self._update_data_listbox, beacon_info)

                        # Log raw advertisement data for analysis
                        log_msg = (
                            f"--- Raw Data for {device.address} ---\n"
                            f"  Local Name: {advertisement_data.local_name}\n"
                            f"  Manufacturer Data ({hex(0x004C)}): {advertisement_data.manufacturer_data.get(0x004C, b'').hex()}\n"
                            f"  Service Data: { {k: v.hex() for k, v in advertisement_data.service_data.items()} }\n"
                            f"  Raw Advertisement: {advertisement_data.data.hex()}\n"
                            f"------------------------------------"
                        )
                        logging.info(log_msg)

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        
        while self.ble_scan_active: 
            current_time = time.time()
            addresses_to_remove = [
                addr for addr, data in beacon_last_seen_data.items()
                if current_time - data['timestamp'] > ABSENCE_DETECTION_TIME
            ]
            for addr in addresses_to_remove:
                del beacon_last_seen_data[addr]
                logging.info(f"Beacon {addr} aus Liste entfernt (zu alt oder zu weit weg).")

            await asyncio.sleep(BLE_SCAN_INTERVAL_SEC)
        
        await scanner.stop()
        logging.info("BLE Scan Task gestoppt.")

    def _update_data_listbox(self, beacon_info):
        self.data_listbox.config(state='normal')
        self.data_listbox.insert(tk.END, f"MAC: {beacon_info['mac']}, Major: {beacon_info['major']}, Minor: {beacon_info['minor']}, RSSI: {beacon_info['rssi']} dBm, Distanz: {beacon_info['distance']:.2f}m\n")
        self.data_listbox.see(tk.END)
        self.data_listbox.config(state='disabled')

    def start_ble_scan(self):
        if self.ble_scan_active:
            logging.warning("Scan läuft bereits.")
            return
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        # Restart the task if it was stopped
        if self.ble_scan_task.done():
            self.ble_scan_task = self.loop.create_task(self._run_ble_scan_task())
        self.ble_scan_active = True
        logging.info("BLE Scan manuell gestartet.")

    def stop_ble_scan(self):
        if not self.ble_scan_active:
            logging.warning("Kein Scan läuft.")
            return
        self.ble_scan_active = False
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        logging.info("BLE Scan manuell gestoppt.")

    def on_closing(self):
        logging.info("Tkinter Fenster geschlossen. Starte geordnetes Herunterfahren.")
        
        # Stop the periodic asyncio runner
        if self._periodic_asyncio_run_id:
            self.root.after_cancel(self._periodic_asyncio_run_id)
            self._periodic_asyncio_run_id = None # Clear the ID
            logging.info("Periodischer Asyncio Runner gestoppt.")

        # Set flag to stop BLE scan task
        self.ble_scan_active = False

        # Cancel all running asyncio tasks
        for task in asyncio.all_tasks(loop=self.loop):
            task.cancel()
        
        # Schedule the final cleanup in the asyncio loop
        self.loop.call_soon_threadsafe(self.loop.create_task, self._async_final_cleanup())
        
        # Finally, quit the Tkinter mainloop
        self.root.quit()

    async def _async_final_cleanup(self):
        logging.info("Starte asyncio Cleanup.")
        # Wait for all tasks to actually finish cancelling
        await asyncio.gather(*asyncio.all_tasks(loop=self.loop), return_exceptions=True)
        
        if not self.loop.is_closed():
            self.loop.close()
        logging.info("Asyncio Loop beendet.")
        cleanup_gpio()
        # The root.destroy() is implicitly handled by root.quit() and mainloop exit.

    def _periodic_asyncio_run(self):
        # Check if the loop is still running before trying to run it
        if not self.loop.is_running():
            try:
                # Run the loop for a very short period to process pending tasks
                self.loop.run_until_complete(asyncio.sleep(0))
            except RuntimeError: # Catch "Event loop is closed" or similar if cleanup already started
                return # Stop scheduling if loop is dead
        
        # Process any pending tasks in the asyncio loop
        self.loop._run_once() # Process one iteration of the event loop

        # Reschedule only if the root window still exists
        if self.root.winfo_exists():
            self._periodic_asyncio_run_id = self.root.after(10, self._periodic_asyncio_run) # Schedule the next update after 10ms (faster updates)


# --- Hauptprogramm ---
def main():
    # Ensure multiprocessing is set to spawn for compatibility
    # This must be done at the very beginning of the main process
    import multiprocessing
    multiprocessing.set_start_method('spawn', force=True)

    root = tk.Tk()
    
    # Create the asyncio event loop and set it as the default for this thread
    # This is crucial for integrating with Tkinter's mainloop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = BLESnifferGUI(root, loop)

    # Start the Tkinter mainloop (this call is blocking)
    root.mainloop()

    logging.info("Programmende (nach Tkinter mainloop).") 


if __name__ == "__main__":
    main()