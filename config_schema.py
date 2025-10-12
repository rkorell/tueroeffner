# Program: config_schema.py
# Purpose: Definiert das Schema und die Metadaten für die system_config.json.
#          Jedes Feld enthält Label, Beschreibung, Typ und ggf. weitere Optionen für die UI-Darstellung und Validierung.
# Author: CircuIT
# Creation Date: August 18, 2025
# Modified: October 10, 2025, 13:45 UTC - Added 'initial_scan_duration_sec' parameter to system_globals.

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
            "ble_scan_interval_sec": {
                "label": "BLE Scan Intervall (Sekunden)",
                "description": "Definiert, wie oft der BLE-Scanner nach Beacons sucht. Ein kleinerer Wert erhöht die Reaktionszeit, kann aber die CPU-Auslastung erhöhen.",
                "type": "number",
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "unit": "Sekunden"
            },
            "identification_timeout_sec": {
                "label": "Identifikations-Timeout (Sekunden)",
                "description": "Zeitspanne, nach der ein Beacon als nicht mehr identifiziert gilt, wenn keine weiteren Pakete empfangen werden.",
                "type": "number",
                "min": 1.0,
                "max": 30.0,
                "step": 0.5,
                "unit": "Sekunden"
            },
            "proximity_distance_threshold": {
                "label": "Nähesschwelle (Meter)",
                "description": "Geschätzte Distanz in Metern, innerhalb derer ein Beacon als 'nah genug' für die Anwesenheitserkennung gilt. Dies ist eine Schätzung und hängt stark von der Umgebung ab.",
                "type": "number",
                "min": 0.5,
                "max": 10.0,
                "step": 0.1,
                "unit": "Meter"
            },
            "presence_detection_time": {
                "label": "Anwesenheits-Erkennungszeit (Sekunden)",
                "description": "Wie lange ein Beacon kontinuierlich erkannt werden muss, bevor er als 'anwesend' gilt (Debouncing).",
                "type": "number",
                "min": 1,
                "max": 30,
                "step": 1,
                "unit": "Sekunden"
            },
            "absence_detection_time": {
                "label": "Abwesenheits-Erkennungszeit (Sekunden)",
                "description": "Wie lange kein Beacon erkannt werden darf, bevor er als 'abwesend' gilt (Debouncing).",
                "type": "number",
                "min": 5,
                "max": 60,
                "step": 1,
                "unit": "Sekunden"
            },
            "calibrated_measured_power_global_default": {
                "label": "Kalibrierte Sendeleistung (dBm)",
                "description": "Standardwert für die kalibrierte Sendeleistung (Tx Power) eines Beacons in 1 Meter Entfernung. Wird zur Distanzschätzung verwendet. Ein höherer Wert bedeutet stärkere Sendeleistung.",
                "type": "number",
                "min": -100,
                "max": -30,
                "step": 1,
                "unit": "dBm"
            },
            "path_loss_exponent_global_default": {
                "label": "Pfadverlust-Exponent",
                "description": "Standardwert für den Pfadverlust-Exponenten. Beschreibt, wie schnell das Signal mit der Entfernung abnimmt. Typische Werte: 2.0 (freier Raum), 2.5-3.5 (Innenräume).",
                "type": "number",
                "min": 1.5,
                "max": 4.0,
                "step": 0.1
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
            "force_beacon_absence_duration_sec": {
                "label": "Erzwungene Beacon-Abwesenheit (Sekunden)",
                "description": "Dauer, für die nach einer erfolgreichen Türöffnung eine Beacon-Abwesenheit erzwungen wird, um sofortige Mehrfachauslösungen zu verhindern. Während dieser Zeit wird die Tür nicht erneut geöffnet.",
                "type": "number",
                "min": 5,
                "max": 60,
                "step": 1,
                "unit": "Sekunden"
            },
            "initial_scan_duration_sec": {
                "label": "Initialer Scan Dauer (Sekunden)",
                "description": "Dauer des dedizierten Scans beim Systemstart, um initial festzustellen, welche Beacons im Haus sind. Während dieser Zeit werden Beacons, die nicht erkannt werden, als 'nicht zu Hause' markiert.",
                "type": "number",
                "min": 5,
                "max": 60,
                "step": 1,
                "unit": "Sekunden"
            },
            "beacon_absence_timeout_for_home_status_sec": {
                "label": "Beacon-Abwesenheits-Timeout für 'Zu Hause'-Status (Sekunden)",
                "description": "Zeit in Sekunden, die ein Beacon nicht vom System gesehen werden darf, bevor es als 'nicht mehr zu Hause' gilt. Dies dient dazu, den 'is_currently_inside_house'-Status zurückzusetzen, wenn das System läuft.",
                "type": "number",
                "min": 300,
                "max": 14400,
                "step": 60,
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