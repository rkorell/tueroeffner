# Program: test_display.py
# Purpose: Stellt Test-Visualisierung auf dem Display bereit (Progressbar für Radar-Tracking).
#          Wird nur verwendet, wenn globals_state.TEST_DISPLAY_MODE = True.
# Author: Dr. Ralf Korell / CircuIT
# Creation Date: October 26, 2025

import config

def draw_test_progressbar(draw, y_distance, x_sign_changed):
    """
    Zeichnet eine Progressbar für Test-Zwecke:
    - Phase 1 (vor X-Vorzeichenwechsel): Horizontaler Balken, wird von links nach rechts weiß
    - Phase 2 (nach X-Vorzeichenwechsel): Vertikaler Balken, wächst von unten nach oben
    
    Args:
        draw: ImageDraw-Objekt
        y_distance: Aktuelle Y-Distanz in mm (None = kein Target)
        x_sign_changed: Boolean, ob X-Vorzeichenwechsel stattgefunden hat
    """
    BLACK = 0
    WHITE = 255
    
    # Gesamten Bildschirm weiß machen (Reset)
    draw.rectangle((0, 0, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT), outline=WHITE, fill=WHITE)
    
    if y_distance is None:
        # Kein Target → Display bleibt weiß (leer)
        return
    
    # Y-Bereich für Progressbar: 2500mm (voll) → 0mm (leer)
    MAX_Y = 2500.0
    
    # Begrenze Y auf sinnvollen Bereich
    y_clamped = max(0, min(y_distance, MAX_Y))
    
    if not x_sign_changed:
        # === Phase 1: Horizontal (Annäherung) ===
        # Balken ist am Anfang voll schwarz (Y=2500mm)
        # Wird von LINKS nach RECHTS weiß (Y nimmt ab)
        # Bei Y=0mm ist alles weiß
        
        schwarzer_anteil = y_clamped / MAX_Y  # 0.0 (nah) bis 1.0 (weit)
        breite_schwarz = int(config.DISPLAY_WIDTH * schwarzer_anteil)
        
        # Schwarzer Balken RECHTS (wird von links "aufgefressen")
        if breite_schwarz > 0:
            draw.rectangle(
                (config.DISPLAY_WIDTH - breite_schwarz, 0, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT),
                outline=BLACK,
                fill=BLACK
            )
    
    else:
        # === Phase 2: Vertikal (Entfernung nach Vorzeichenwechsel) ===
        # Schwarzer Balken wächst von UNTEN nach OBEN
        # Je größer Y (Entfernung), desto höher der schwarze Balken
        
        hoehe_anteil = y_clamped / MAX_Y  # 0.0 (nah) bis 1.0 (weit)
        hoehe_schwarz = int(config.DISPLAY_HEIGHT * hoehe_anteil)
        
        # Schwarzer Balken UNTEN (wächst nach oben)
        if hoehe_schwarz > 0:
            draw.rectangle(
                (0, config.DISPLAY_HEIGHT - hoehe_schwarz, config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT),
                outline=BLACK,
                fill=BLACK
            )