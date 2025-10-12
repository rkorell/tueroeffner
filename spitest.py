# spi_test.py
import spidev
import time
import logging

logging.basicConfig(level=logging.INFO)

try:
    spi = spidev.SpiDev()
    spi.open(0, 0) # Open SPI bus 0, device 0 (CE0)
    spi.max_speed_hz = 1000000 # 1 MHz

    logging.info("SPI-Bus geöffnet. Sende Testdaten...")

    # Sende 3 Bytes (z.B. 0x01, 0x02, 0x03)
    resp = spi.xfer2([0x01, 0x02, 0x03])
    logging.info(f"Gesendet: [0x01, 0x02, 0x03], Empfangen: {resp}")

    time.sleep(1)

    # Sende 3 Bytes (z.B. 0xFF, 0x00, 0xFF)
    resp = spi.xfer2([0xFF, 0x00, 0xFF])
    logging.info(f"Gesendet: [0xFF, 0x00, 0xFF], Empfangen: {resp}")

except FileNotFoundError:
    logging.error("SPI-Gerät nicht gefunden. Stellen Sie sicher, dass SPI aktiviert ist.")
except Exception as e:
    logging.error(f"Fehler bei SPI-Kommunikation: {e}")
finally:
    if 'spi' in locals() and spi.fd: # Check if spi object and file descriptor exist
        spi.close()
        logging.info("SPI-Bus geschlossen.")