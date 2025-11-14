#!/usr/bin/env python3
"""
water_drop_simulator.py

Water drop simulator for PiSugar WhisPlay (uses WhisPlayBoard).
Features:
 - Raindrops fall with gravity and create ripples on impact
 - Ripple outlines expand and fade
 - Soft sine "plink" sounds on impact
 - Button controls:
     Short press: toggle start/stop
     Long press (~2s): add a few drops
     Extra long (~4s): spawn storm (many drops)
     Double press: reset/clear
"""

from time import sleep, time
import sys
import os
import random
import argparse
import math

# numpy and pygame for audio generation
import numpy as np
import pygame

# Allow importing WhisPlay from your Driver folder (matches your other scripts)
sys.path.append(os.path.abspath("../Driver"))
from WhisPlay import WhisPlayBoard

# ------------------------------
# Configuration
# ------------------------------
GRAVITY = 0.18             # pixels per frame^2 (tweak)
FRAMERATE = 30             # target FPS
FRAME_TIME = 1.0 / FRAMERATE
DROP_SPAWN_RATE_RUNNING = 0.12  # average drops per frame when running (probability)
STORM_SPAWN_MULTIPLIER = 6      # multiplier when in storm mode
LONG_PRESS_SECONDS = 2.0
EXTRA_LONG_PRESS_SECONDS = 4.0
DOUBLE_PRESS_WINDOW = 0.4

# Audio config
SAMPLE_RATE = 22050
SOUND_DURATION = 0.11  # seconds for plink
BASE_PLINK_FREQ = 700  # base frequency for impact sound

# ------------------------------
# Utility: volume set for wm8960 (optional)
# ------------------------------
import subprocess

pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)

def set_wm8960_volume_stable(volume_level: str):
    """
    Try to set wm8960 Speaker volume (best-effort; safe if amixer missing).
    volume_level: e.g. '121'
    """
    CARD_NAME = 'wm8960soundcard'
    CONTROL_NAME = 'Speaker'
    DEVICE_ARG = f'hw:{CARD_NAME}'
    command = ['amixer', '-D', DEVICE_ARG, 'sset', CONTROL_NAME, volume_level]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"INFO: Set '{CONTROL_NAME}' volume to {volume_level}.")
    except Exception:
        # silent fail: many dev setups won't have this card or amixer.
        pass

# ------------------------------
# Audio: generate a small plink sound
# ------------------------------
def generate_plink(freq=None, duration=SOUND_DURATION, sample_rate=SAMPLE_RATE):
    """
    Generate a short synthesized sine 'plink' as a pygame Sound.
    Returns a pygame.mixer.Sound object.
    """
    if freq is None:
        freq = BASE_PLINK_FREQ + random.uniform(-150, 150)
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # soft attack-decay envelope
    envelope = (1 - np.exp(-12 * t)) * np.exp(-8 * t)
    wave = 0.6 * envelope * np.sin(2 * np.pi * freq * t)
    # convert to 16-bit signed
    audio = np.int16(wave * 32767)
    try:
        snd = pygame.sndarray.make_sound(audio)
        return snd
    except Exception as e:
        # If conversion fails, return None
        print("Audio generation failed:", e)
        return None

# ------------------------------
# Drawing helpers for WhisPlay
# ------------------------------
def draw_pixel_safe(board, x, y, color):
    """Draw pixel if inside bounds (int coords)."""
    if 0 <= x < board.LCD_WIDTH and 0 <= y < board.LCD_HEIGHT:
        board.draw_pixel(int(x), int(y), color)

def draw_circle_outline(board, cx, cy, radius, color):
    """Bresenham circle outline algorithm - draws integer points on the perimeter."""
    # radius should be int >= 0
    r = int(radius)
    x = r
    y = 0
    err = 0
    while x >= y:
        draw_pixel_safe(board, cx + x, cy + y, color)
        draw_pixel_safe(board, cx + y, cy + x, color)
        draw_pixel_safe(board, cx - y, cy + x, color)
        draw_pixel_safe(board, cx - x, cy + y, color)
        draw_pixel_safe(board, cx - x, cy - y, color)
        draw_pixel_safe(board, cx - y, cy - x, color)
        draw_pixel_safe(board, cx + y, cy - x, color)
        draw_pixel_safe(board, cx + x, cy - y, color)

        y += 1
        err += 1 + 2*y
        if 2*(err - x) + 1 > 0:
            x -= 1
            err += 1 - 2*x

# ------------------------------
# Simulation objects
# ------------------------------
class Raindrop:
    def __init__(self, x, y, vy=0.0, color=0x07FF):
        self.x = float(x)
        self.y = float(y)
        self.vy = float(vy)
        self.radius = 1.0
        self.color = color
        self.alive = True

    def update(self):
        self.vy += GRAVITY
        self.y += self.vy

class Ripple:
    def __init__(self, x, y, max_radius=28, color=0x07FF, life=0.9):
        self.x = int(x)
        self.y = int(y)
        self.age = 0.0
        self.life = float(life)  # seconds
        self.max_radius = int(max_radius)
        self.color = color
        self.alive = True

    def update(self, dt):
        self.age += dt
        if self.age >= self.life:
            self.alive = False

    def current_radius(self):
        # progress from 0 to max_radius
        prog = min(1.0, self.age / self.life)
        return prog * self.max_radius

    def current_color(self):
        # fade color to darker as it ages (approx by reducing brightness)
        prog = min(1.0, self.age / self.life)
        fade = int((1 - prog) * 31)  # green/blue mixing later
        # produce cyan-like ripple by combining green+blue with fade
        r = 0
        g = min(255, int((1 - prog) * 200) + 30)
        b = min(255, int((1 - prog) * 255))
        # convert to rgb565
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return rgb565

# ------------------------------
# Main simulator class
# ------------------------------
class WaterDropSimulator:
    def __init__(self, board, args):
        self.board = board
        self.width = board.LCD_WIDTH
        self.height = board.LCD_HEIGHT
        self.running = False
        self.raindrops = []
        self.ripples = []
        self.last_spawn_acc = 0.0
        self.spawning_multiplier = 1.0
        self.last_press_time = 0.0
        self.press_start_time = None
        self.double_press_window = DOUBLE_PRESS_WINDOW
        self.long_press_seconds = LONG_PRESS_SECONDS
        self.extra_long_seconds = EXTRA_LONG_PRESS_SECONDS
        self.storm = False
        self.args = args

    def spawn_drop(self, x=None, y=0.0, vy=None):
        if x is None:
            x = random.uniform(4, self.width - 5)
        if vy is None:
            vy = random.uniform(0.6, 1.6)
        color = random.choice([0x07FF, 0x07E0, 0x001F, 0x07FF, 0xBDF7])  # watery colors
        d = Raindrop(x, y, vy, color=color)
        self.raindrops.append(d)

    def reset(self):
        self.raindrops.clear()
        self.ripples.clear()
        self.running = False
        self.storm = False
        self.board.fill_screen(0x0000)
        self.board.set_rgb(0, 0, 0)

    def step(self, dt):
        # possibly spawn new drops if running
        if self.running:
            # spawn by probability per frame
            spawn_prob = DROP_SPAWN_RATE_RUNNING * self.spawning_multiplier
            if self.storm:
                spawn_prob *= STORM_SPAWN_MULTIPLIER
            if random.random() < spawn_prob:
                self.spawn_drop()

        # update raindrops
        for drop in self.raindrops:
            if not drop.alive:
                continue
            drop.update()
            # Impact if reaches bottom of screen (y >= height - 2)
            if drop.y >= self.height - 2:
                drop.alive = False
                # create ripple
                r = Ripple(drop.x, self.height - 4, max_radius=random.randint(10, 34))
                self.ripples.append(r)
                # play sound
                freq = int(BASE_PLINK_FREQ + (1 - (random.random())) * 160 - (drop.vy * 15))
                snd = generate_plink(freq=freq)
                if snd:
                    snd.play()
            # optional impact on existing ripple? (not implemented to keep performance)
        # remove dead raindrops
        self.raindrops = [d for d in self.raindrops if d.alive]

        # update ripples
        for r in self.ripples:
            r.update(dt)
        self.ripples = [r for r in self.ripples if r.alive]

    def draw(self):
        # Clear screen quickly by filling black
        self.board.fill_screen(0x0000)

        # Draw ripples (outline)
        for r in self.ripples:
            radius = r.current_radius()
            if radius >= 1:
                color = r.current_color()
                # draw multiple thin concentric ring segments for nicer look
                draw_circle_outline(self.board, r.x, r.y, int(radius), color)
                # draw slight second outline for depth
                if radius > 3:
                    draw_circle_outline(self.board, r.x, r.y, int(radius * 0.85), color)

        # Draw raindrops as bright single pixels
        for d in self.raindrops:
            # color brightening based on vy
            draw_pixel_safe(self.board, int(d.x), int(d.y), d.color)

    # Button callbacks
    def on_button_press(self):
        self.press_start_time = time()

    def on_button_release(self):
        now = time()
        press_duration = 0.0
        if self.press_start_time:
            press_duration = now - self.press_start_time
        # detect double press
        if (now - self.last_press_time) < self.double_press_window:
            # double press - reset
            self.reset()
            self.last_press_time = now
            return

        # extra-long press: storm (toggle)
        if press_duration >= self.extra_long_seconds:
            self.storm = not self.storm
            self.running = True
            print("Storm toggled:", self.storm)
            # spawn an initial burst
            for _ in range(12):
                self.spawn_drop()
            self.last_press_time = now
            return

        # long press: add a few drops
        if press_duration >= self.long_press_seconds:
            for _ in range(6):
                self.spawn_drop()
            self.running = True
            self.last_press_time = now
            return

        # short press: toggle running
        self.running = not self.running
        # If starting with no drops, spawn a starter drop
        if self.running and not self.raindrops:
            for _ in range(2):
                self.spawn_drop()
        self.last_press_time = now

# ------------------------------
# Main routine
# ------------------------------
def main():
    parser = argparse.ArgumentParser(description="PiSugar WhisPlay Water Drop Simulator")
    parser.add_argument("--volume", default="121", help="Try to set wm8960 volume (best-effort).")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio generation.")
    args = parser.parse_args()

    # init board
    board = WhisPlayBoard()
    board.set_backlight(70)
    board.set_rgb(0, 0, 0)
    board.fill_screen(0x0000)

    # init pygame mixer
    if not args.no_audio:
        try:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=512)
            set_wm8960_volume_stable(args.volume)
        except Exception as e:
            print("Warning: pygame mixer init failed; continuing without audio. Error:", e)
            args.no_audio = True

    sim = WaterDropSimulator(board, args)

    # Attach button callbacks (match your driver)
    board.on_button_press(sim.on_button_press)
    board.on_button_release(sim.on_button_release)

    print("Water drop simulator ready. Short press to start/stop. Long press to add drops. Extra-long toggles storm. Double press resets.")

    last_time = time()
    try:
        while True:
            now = time()
            dt = now - last_time
            if dt <= 0:
                dt = FRAME_TIME
            # Step sim with dt
            sim.step(dt)
            sim.draw()

            last_time = now
            # maintain framerate
            sleep(max(0, FRAME_TIME - (time() - now)))

    except KeyboardInterrupt:
        print("Exiting...")

    finally:
        board.cleanup()
        try:
            pygame.mixer.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
