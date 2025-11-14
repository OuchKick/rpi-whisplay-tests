# sound-pixel.py
from time import sleep, time
import sys, os, random
import pygame
import numpy as np

# Import WhisPlay driver
sys.path.append(os.path.abspath("../Driver"))
from WhisPlay import WhisPlayBoard

# --- Setup ---
board = WhisPlayBoard()
board.set_backlight(70)
board.set_rgb(0, 0, 0)

WIDTH, HEIGHT = 240, 240
print("WhisPlay initialized. Button controls the animation.")

# --- Initialize sound ---
pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)

def generate_blip_sound(freq=None, duration=0.08, waveform="sine", echo=True):
    """Generate a short synth blip with optional delay/echo."""
    sample_rate = 44100
    t = np.linspace(0, duration, int(sample_rate * duration), False)

    if freq is None:
        freq = random.randint(200, 1200)

    # Mostly sine waves
    if waveform == "random":
        waveform = random.choices(["sine", "square", "saw"], weights=[0.7, 0.15, 0.15])[0]

    if waveform == "sine":
        wave = np.sin(2 * np.pi * freq * t)
    elif waveform == "square":
        wave = np.sign(np.sin(2 * np.pi * freq * t))
    elif waveform == "saw":
        wave = 2*(t*freq - np.floor(0.5 + t*freq))

    # Slight random amplitude modulation
    wave *= np.exp(-5*t) * random.uniform(0.3, 0.7)

    # Convert to 16-bit
    audio = np.int16(wave * 32767)
    sound = pygame.sndarray.make_sound(audio)

    # Optional echo/delay
    if echo:
        def play_with_echo():
            sound.play()
            pygame.time.set_timer(pygame.USEREVENT, int(duration*400), True)
            pygame.mixer.Sound.play(sound)
        return sound
    else:
        return sound

# --- Pixel object ---
class Pixel:
    def __init__(self, x, y, dx, dy, color):
        self.x = x
        self.y = y
        self.dx = dx
        self.dy = dy
        self.color = color

    def move(self):
        bounced = False
        self.x += self.dx
        self.y += self.dy

        # Bounce on edges
        if self.x <= 0 or self.x >= WIDTH - 1:
            self.dx *= -1
            bounced = True
        if self.y <= 0 or self.y >= HEIGHT - 1:
            self.dy *= -1
            bounced = True

        # Play sound on bounce
        if bounced:
            freq = 200 + int(self.color % 0xFFFF) % 1000  # map color to freq
            blip = generate_blip_sound(freq=freq)
            blip.play()

    def draw(self):
        board.draw_pixel(int(self.x), int(self.y), self.color)

# --- State ---
pixels = []
running = False
last_press_time = 0
press_start_time = None
long_press_duration = 2.0
extra_long_press_duration = 4.0
double_press_window = 0.4

# --- Utilities ---
def random_color():
    return random.choice([0xF800, 0x07E0, 0x001F, 0xFFFF, 0xFFE0, 0x07FF])

def check_collision(p1, p2):
    return int(p1.x) == int(p2.x) and int(p1.y) == int(p2.y)

# --- Animation loop ---
def animation_loop():
    while running:
        board.fill_screen(0x0000)  # clear screen

        # Move pixels
        for p in pixels:
            p.move()

        # Detect collisions between pixels
        for i in range(len(pixels)):
            for j in range(i + 1, len(pixels)):
                if check_collision(pixels[i], pixels[j]):
                    pixels[i].color = random_color()
                    pixels[j].color = random_color()
                    # Sound pitch based on color
                    freq1 = 200 + int(pixels[i].color % 0xFFFF) % 1000
                    freq2 = 200 + int(pixels[j].color % 0xFFFF) % 1000
                    generate_blip_sound(freq=freq1).play()
                    generate_blip_sound(freq=freq2).play()

        # Draw pixels
        for p in pixels:
            p.draw()

        sleep(0.02)

# --- Button events ---
def on_button_pressed():
    global press_start_time
    press_start_time = time()

def on_button_released():
    global running, last_press_time, press_start_time, pixels

    press_duration = time() - press_start_time if press_start_time else 0
    now = time()

    # Double press → reset
    if now - last_press_time < double_press_window:
        print("Double press detected → Resetting!")
        pixels.clear()
        running = False
        board.fill_screen(0x0000)
        board.set_rgb(0, 0, 0)
        last_press_time = now
        return

    # Extra-long press → spawn 10 pixels
    if press_duration >= extra_long_press_duration:
        print("Extra-long press detected → Adding 10 new pixels.")
        for _ in range(10):
            new_pixel = Pixel(
                random.randint(0, WIDTH - 1),
                random.randint(0, HEIGHT - 1),
                random.choice([-1, 1]),
                random.choice([-1, 1]),
                random_color()
            )
            pixels.append(new_pixel)
        if not running:
            running = True
    # Long press → add 1 pixel
    elif press_duration >= long_press_duration:
        print("Long press detected → Adding 1 new pixel.")
        new_pixel = Pixel(
            random.randint(0, WIDTH - 1),
            random.randint(0, HEIGHT - 1),
            random.choice([-1, 1]),
            random.choice([-1, 1]),
            random_color()
        )
        pixels.append(new_pixel)
        if not running:
            running = True
    else:
        # Short press → toggle start/stop
        running = not running
        print("Toggled running:", running)
        if running and not pixels:
            pixels.append(Pixel(WIDTH // 2, HEIGHT // 2, 1, 1, random_color()))

    last_press_time = now

# --- Attach callbacks ---
board.on_button_press(on_button_pressed)
board.on_button_release(on_button_released)

# --- Main loop ---
try:
    while True:
        if running:
            animation_loop()
        else:
            sleep(0.05)
except KeyboardInterrupt:
    print("Exiting...")
finally:
    board.cleanup()
    pygame.mixer.quit()