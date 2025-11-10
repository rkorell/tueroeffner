# Program: config_schema.py
# Purpose: Definiert das Schema und die Metadaten für die system_config.json.
#          Jedes Feld enthält Label, Beschreibung, Typ und ggf. weitere Optionen für die UI-Darstellung und Validierung.
# Author: CircuIT
# Creation Date: August 18, 2025
# Modified: October 10, 2025, 13:45 UTC - Added 'initial_scan_duration_sec' parameter to system_globals.
# Modified: October 16, 2025, 13:00 UTC - Added 'radar_config' parameters.
# Modified: November 10, 2025, 17:00 UTC - Config-Leichen entfernt: 10 ungenutzte BLE-Scanner-Variablen aus system_globals gelöscht.
# Modified: November 10, 2025, 17:30 UTC - Magic Numbers ausgelagert: 4 neue Felder in radar_config (history_size, sign_change_y_max, sign_change_x_max, radar_loop_delay).
# Modified: November 10, 2025, 18:00 UTC - Config-Leiche entfernt: min_distance_to_sensor aus radar_config gelöscht (ungenutzt).

CONFIG_SCHEMA = {
    "system_globals": {
        "label": "System Globale Einstellungen",
        "description": "Allgemeine Einstellungen für den Betrieb des Türöffnungssystems.",
        "type": "group",
        "fields": {
            "ibeacon_uuid": {
                "label": "iBeacon UUID",
                "description": "Die universell eindeutige Kennung (UUID) für iBeacons, die vom System erkannt werden sollen. Alle Ihre iBeacons sollten diese UUID verwenden.",
                "type": "string",
                "placeholder": "E2C56DB5-DFFB-48D2-B060-D0F5A71096E0",
                "pattern": "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$",
                "pattern_description": "Muss im Format XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX sein."
            },
            "eddystone_namespace_id": {
                "label": "Eddystone Namespace ID",
                "description": "Die Namespace ID für Eddystone UID Beacons, die vom System erkannt werden sollen.",
                "type": "string",
                "placeholder": "1A2B3C4D5E6F708090A0",
                "pattern": "^[0-9A-Fa-f]{20}$",
                "pattern_description": "Muss eine 20-stellige Hexadezimalzahl sein."
            },
            "relay_activation_duration_sec": {
                "label": "Relais-Aktivierungsdauer (Sekunden)",
                "description": "Wie lange das Relais aktiviert wird, um die Tür zu öffnen. Dieser Wert wird an 'codesend' übergeben. Muss zwischen 3 und 10 Sekunden liegen.",
                "type": "number",
                "min": 3,
                "max": 10,
                "step": 1,
                "unit": "Sekunden"
            },
            "min_detection_interval": {
                "label": "Mindest-Erkennungsintervall (Sekunden)",
                "description": "Mindestzeit, die zwischen zwei 'codesend'-Befehlen vergehen muss. Dies ist ein Cooldown, um das Relais zu schützen und unerwünschte Mehrfachauslösungen zu vermeiden.",
                "type": "number",
                "min": 1,
                "max": 30,
                "step": 1,
                "unit": "Sekunden"
            },
            "weather_config": {
                "label": "Wetterkonfiguration",
                "description": "Einstellungen für die Abfrage von Wetterdaten über Weather Underground (PWS).",
                "type": "group",
                "fields": {
                    "station_id": {
                        "label": "Wetterstations-ID (PWS)",
                        "description": "Ihre persönliche Wetterstations-ID von Weather Underground (PWS), z.B. 'IGEROL23'.",
                        "type": "string",
                        "placeholder": "IGEROL23"
                    },
                    "api_key": {
                        "label": "Weather Underground API Key",
                        "description": "Ihr API-Schlüssel für den Zugriff auf Weather Underground Daten. Diesen Schlüssel sollten Sie vertraulich behandeln.",
                        "type": "string",
                        "placeholder": "d1a8702761c9427fa8702761c9f27fc1",
                        "secret": True
                    },
                    "query_interval_sec": {
                        "label": "Wetter-Abfrageintervall (Sekunden)",
                        "description": "Wie oft Wetterdaten von Weather Underground abgerufen werden sollen. Ein Wert von 300 Sekunden entspricht 5 Minuten.",
                        "type": "number",
                        "min": 60,
                        "max": 3600,
                        "step": 60,
                        "unit": "Sekunden"
                    }
                }
            },
            "logging_config": {
                "label": "Logging Konfiguration",
                "description": "Einstellungen für die Protokollierung (Logging) des Systems.",
                "type": "group",
                "fields": {
                    "level": {
                        "label": "Logging Level",
                        "description": "Der Detailgrad der Protokollmeldungen, die in der Konsole und/oder Datei angezeigt werden. DEBUG ist am ausführlichsten, CRITICAL nur bei schwerwiegenden Fehlern.",
                        "type": "select",
                        "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
                    },
                    "file_enabled": {
                        "label": "Logging in Datei aktivieren",
                        "description": "Sollen Protokollmeldungen auch in eine separate Logdatei geschrieben werden?",
                        "type": "boolean"
                    },
                    "file_path": {
                        "label": "Logdateipfad",
                        "description": "Der vollständige Pfad zur Logdatei, falls Datei-Logging aktiviert ist.",
                        "type": "string",
                        "placeholder": "tuer_oeffner.log"
                    }
                }
            }
        }
    },
    "radar_config": {
        "label": "Radar Konfiguration",
        "description": "Einstellungen für den mmWave Radar Sensor und die Türöffnungslogik.",
        "type": "group",
        "fields": {
            "uart_port": {
                "label": "UART Port",
                "description": "Der UART-Port, an den der Radarsensor angeschlossen ist (z.B. /dev/ttyAMA2).",
                "type": "string",
                "placeholder": "/dev/ttyAMA2"
            },
            "ble_scan_max_duration": {
                "label": "Max. BLE Scan Dauer",
                "description": "Maximale Dauer in Sekunden, für die der BLE-Scan läuft, wenn er vom Radar ausgelöst wird. Der Scan endet früher, wenn ein berechtigter Beacon gefunden wird.",
                "type": "number",
                "min": 0.1,
                "max": 2.0,
                "step": 0.1,
                "unit": "Sekunden"
            },
            "speed_noise_threshold": {
                "label": "Geschwindigkeits-Rauschschwelle",
                "description": "Mindestgeschwindigkeit in cm/s, die ein Objekt haben muss, um als 'bewegt' zu gelten. Kleinere Werte werden als Rauschen oder statisch ignoriert.",
                "type": "number",
                "min": 0,
                "max": 20,
                "step": 1,
                "unit": "cm/s"
            },
            "expected_x_sign": {
                "label": "Erwartetes X-Vorzeichen für Annäherung",
                "description": "Das erwartete Vorzeichen der X-Koordinate, wenn eine Person aus der 'Kommen'-Richtung kommt. Empirisch zu bestimmen, je nach Sensor-Ausrichtung ('positive' oder 'negative').",
                "type": "select",
                "options": ["positive", "negative"]
            },
            "door_open_comfort_delay": {
                "label": "Türöffnungs-Komfortverzögerung",
                "description": "Optionaler Wartezeitraum in Sekunden nach Erkennung des Türöffnungszeitpunkts, um die Benutzererfahrung zu verbessern (z.B. Tür summer, wenn Hand den Knauf erreicht).",
                "type": "number",
                "min": 0.0,
                "max": 2.0,
                "step": 0.1,
                "unit": "Sekunden"
            },
            "cooldown_duration": {
                "label": "Cooldown Dauer",
                "description": "Dauer in Sekunden des Cooldowns nach jedem abgeschlossenen Ereigniszyklus (mit oder ohne Türöffnung).",
                "type": "number",
                "min": 1,
                "max": 30,
                "step": 1,
                "unit": "Sekunden"
            },
            "history_size": {
                "label": "Historie-Größe (Frames)",
                "description": "Anzahl der Radar-Frames für die Trendanalyse. Kleinere Werte = schnellere Reaktion, größere Werte = stabilere Erkennung. Empfohlen: 5-10.",
                "type": "number",
                "min": 3,
                "max": 15,
                "step": 1,
                "unit": "Frames"
            },
            "sign_change_y_max": {
                "label": "Max. Y-Distanz für Vorzeichenwechsel (mm)",
                "description": "Maximale Y-Distanz (Abstand zum Sensor), bis zu der ein X-Vorzeichenwechsel als gültig akzeptiert wird. Filtert Radar-Rauschen bei großen Entfernungen.",
                "type": "number",
                "min": 200,
                "max": 1000,
                "step": 50,
                "unit": "mm"
            },
            "sign_change_x_max": {
                "label": "Max. X-Wert für Vorzeichenwechsel (mm)",
                "description": "Maximaler absoluter X-Wert, bis zu dem ein Vorzeichenwechsel bei X=0 als gültig akzeptiert wird. Filtert seitliche Radar-Messfehler.",
                "type": "number",
                "min": 300,
                "max": 1500,
                "step": 50,
                "unit": "mm"
            },
            "radar_loop_delay": {
                "label": "Radar Loop Verzögerung (Sekunden)",
                "description": "Pause zwischen Radar-Auslesungen im I/O-Task. Kleinere Werte = höhere Polling-Rate, aber mehr CPU-Last. Empfohlen: 0.05 (50ms).",
                "type": "number",
                "min": 0.01,
                "max": 0.2,
                "step": 0.01,
                "unit": "Sekunden"
            }
        }
    },
    "known_beacons": {
        "label": "Bekannte Beacons (JSON)",
        "description": "Liste der autorisierten und bekannten BLE Beacons. Diese Liste ist komplex und wird als rohes JSON bearbeitet, um die volle Flexibilität zu gewährleisten. Achten Sie auf korrekte Syntax! Nutzen Sie den Button 'Leeren Beacon hinzufügen', um ein Template einzufügen.",
        "type": "json_array"
    },
    "auth_criteria": {
        "label": "Authentifizierungskriterien",
        "description": "Definiert, welche BLE-Datenfelder für die vollständige Beacon-Identifikation erforderlich sind. 'REQUIRED' bedeutet, das Feld muss übereinstimmen; 'OPTIONAL' bedeutet, es kann zur Identifikation beitragen, ist aber nicht zwingend; 'DISABLED' bedeutet, es wird ignoriert.",
        "type": "group",
        "fields": {
            "ibeacon": {
                "label": "iBeacon Daten",
                "description": "Erforderlichkeit der iBeacon-Daten (Major, Minor) für die Authentifizierung.",
                "type": "select",
                "options": ["REQUIRED", "OPTIONAL", "DISABLED"]
            },
            "eddystone_uid": {
                "label": "Eddystone UID Daten",
                "description": "Erforderlichkeit der Eddystone UID-Daten (Instance ID) für die Authentifizierung.",
                "type": "select",
                "options": ["REQUIRED", "OPTIONAL", "DISABLED"]
            },
            "eddystone_url": {
                "label": "Eddystone URL Daten",
                "description": "Erforderlichkeit der Eddystone URL-Daten für die Authentifizierung.",
                "type": "select",
                "options": ["REQUIRED", "OPTIONAL", "DISABLED"]
            },
            "mac_address": {
                "label": "MAC Adresse",
                "description": "Erforderlichkeit der MAC-Adresse für die Authentifizierung. Die MAC-Adresse ist immer ein starkes Identifikationsmerkmal.",
                "type": "select",
                "options": ["REQUIRED", "OPTIONAL", "DISABLED"]
            }
        }
    }
}