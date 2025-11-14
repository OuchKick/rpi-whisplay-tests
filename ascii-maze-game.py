#!/usr/bin/env python3
"""
ASCII Dungeon Maze Game for Whisplay (single-button control)

Controls (single physical button):
- Short press (quick release): Select / Confirm (or open menu if at a fork)
- Long press (>= 0.5s): While held, cycles the menu cursor every 0.33s through available options.
- No double-tap behavior.
"""
from time import time, sleep
import random
import sys
import os
from threading import Thread, Event

# paths so we can import your driver + utils
sys.path.append(os.path.abspath("../extra"))  # where utils.py typically lives
sys.path.append(os.path.abspath("../Driver"))  # where WhisPlay.py typically lives

try:
    from WhisPlay import WhisPlayBoard
except Exception as e:
    raise RuntimeError("Couldn't import WhisPlayBoard. Ensure WhisPlay.py is in ../Driver or project root.") from e

from utils import ImageUtils
from PIL import Image, ImageDraw, ImageFont
from collections import deque

# -------------------------
# Config (user chose 12px)
# -------------------------
CELL_W = 8    # pixel width per char cell (approx)
CELL_H = 12   # pixel height per char cell
DOUBLE_PRESS_WINDOW = 0.45  # unused but keep if needed later
LONG_PRESS_FOR_CYCLE = 0.5  # seconds to hold before cycling starts
CYCLE_INTERVAL = 0.33       # seconds between cursor moves while holding
FPS_SLEEP = 0.12

# ASCII glyphs for Style C (rounded block look)
GL_WALL = "▓"
GL_FLOOR = "."
GL_PLAYER = "¡"
GL_TREASURE = "☼"

# -------------------------
# Maze generator (recursive backtracker)
# -------------------------
class Maze:
    def __init__(self, width_cells, height_cells):
        self.w = width_cells if width_cells % 2 == 1 else width_cells - 1
        self.h = height_cells if height_cells % 2 == 1 else height_cells - 1
        self.grid = [[1 for _ in range(self.w)] for _ in range(self.h)]
        self._generate()

    def _neighbors(self, cx, cy):
        n = []
        deltas = [ (0, -2), (2, 0), (0, 2), (-2, 0) ]
        for dx, dy in deltas:
            nx, ny = cx + dx, cy + dy
            if 0 < nx < self.w-1 and 0 < ny < self.h-1:
                n.append((nx, ny))
        return n

    def _generate(self):
        stack = [(1,1)]
        self.grid[1][1] = 0
        while stack:
            cx, cy = stack[-1]
            neigh = [n for n in self._neighbors(cx, cy) if self.grid[n[1]][n[0]] == 1]
            if not neigh:
                stack.pop()
                continue
            nx, ny = random.choice(neigh)
            wall_x = (cx + nx) // 2
            wall_y = (cy + ny) // 2
            self.grid[wall_y][wall_x] = 0
            self.grid[ny][nx] = 0
            stack.append((nx, ny))

    def place_treasure_farthest_from(self, sx, sy):
        q = deque()
        q.append((sx, sy, 0))
        seen = set([(sx, sy)])
        far = (sx, sy, 0)
        while q:
            x,y,d = q.popleft()
            if d > far[2]:
                far = (x,y,d)
            for dx,dy in [ (1,0),(-1,0),(0,1),(0,-1) ]:
                nx, ny = x+dx, y+dy
                if 0 <= nx < self.w and 0 <= ny < self.h and (nx,ny) not in seen and self.grid[ny][nx] == 0:
                    seen.add((nx,ny))
                    q.append((nx,ny,d+1))
        return (far[0], far[1])

    def is_floor(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.grid[y][x] == 0
        return False

# -------------------------
# Renderer: draws ASCII glyphs into an image, convert to RGB565
# -------------------------
class Renderer:
    def __init__(self, whisplay):
        self.wh = whisplay
        self.screen_w = self.wh.LCD_WIDTH
        self.screen_h = self.wh.LCD_HEIGHT
        # approx columns/rows based on cell sizes
        self.cols = max(12, self.screen_w // CELL_W)
        self.rows = max(8, self.screen_h // CELL_H)
        # prefer monospace font sized to CELL_H
        try:
            self.font = ImageFont.truetype("DejaVuSansMono.ttf", CELL_H - 1)
        except Exception:
            self.font = ImageFont.load_default()
        self.cell_w = self.screen_w / self.cols
        self.cell_h = self.screen_h / self.rows

    def render_viewport(self, maze, player_x, player_y, treasure_pos, elapsed_s, menu_lines=None, menu_selected=0):
        half_cols = self.cols // 2
        half_rows = self.rows // 2
        left = player_x - half_cols
        top = player_y - half_rows

        img = Image.new("RGB", (self.screen_w, self.screen_h), (0,0,0))
        draw = ImageDraw.Draw(img)

        # header (time)
        time_text = f"Time: {elapsed_s:.1f}s" if elapsed_s is not None else "Time: 0.0s"
        draw.text((4,2), time_text, font=self.font, fill=(255,255,255))

        header_h = int(self.cell_h)
        grid_y_offset = header_h

        for r in range(self.rows - 1):
            for c in range(self.cols):
                maze_x = left + c
                maze_y = top + r
                px = int(c * self.cell_w)
                py = int(grid_y_offset + r * self.cell_h)
                if 0 <= maze_x < maze.w and 0 <= maze_y < maze.h:
                    if (maze_x, maze_y) == treasure_pos:
                        char = GL_TREASURE
                    elif (maze_x, maze_y) == (player_x, player_y):
                        char = GL_PLAYER
                    else:
                        char = GL_FLOOR if maze.grid[maze_y][maze_x] == 0 else GL_WALL
                else:
                    char = GL_WALL
                draw.text((px+1, py+1), char, font=self.font, fill=(255,255,255))

        if menu_lines:
            box_w = int(self.screen_w * 0.72)
            box_h = int(self.screen_h * 0.36)
            box_x = (self.screen_w - box_w)//2
            box_y = (self.screen_h - box_h)//2
            draw.rectangle([box_x, box_y, box_x+box_w, box_y+box_h], fill=(18,18,18))
            draw.rectangle([box_x, box_y, box_x+box_w, box_y+box_h], outline=(200,200,200), width=2)
            line_h = max(12, int(box_h / max(1, len(menu_lines)+1)))
            for idx, line in enumerate(menu_lines):
                tx = box_x + 12
                ty = box_y + 12 + idx*line_h
                prefix = ">" if idx == menu_selected else " "
                draw.text((tx, ty), prefix + " " + line, font=self.font, fill=(255,255,255))

        rgb565 = ImageUtils.image_to_rgb565(img, self.wh.LCD_WIDTH, self.wh.LCD_HEIGHT)
        self.wh.draw_image(0, 0, self.wh.LCD_WIDTH, self.wh.LCD_HEIGHT, rgb565)

# -------------------------
# Game engine
# -------------------------
class Game:
    def __init__(self, whisplay):
        self.wh = whisplay
        self.renderer = Renderer(self.wh)

        # maze larger than viewport
        maze_cols = max(21, (self.renderer.cols * 3) // 2 | 1)
        maze_rows = max(21, (self.renderer.rows * 3) // 2 | 1)
        maze_cols = maze_cols if maze_cols % 2 == 1 else maze_cols+1
        maze_rows = maze_rows if maze_rows % 2 == 1 else maze_rows+1

        self.maze = Maze(maze_cols, maze_rows)
        self.player_x, self.player_y = 1, 1
        self.treasure = self.maze.place_treasure_farthest_from(self.player_x, self.player_y)
        self.start_time = None

        # movement state
        self.current_dir = None   # (dx,dy) or None
        self.running = False

        # menu state
        self.menu_active = False
        self.menu_options = []
        self.menu_selected = 0

        # long-press cycling
        self._cycle_thread = None
        self._cycle_stop = Event()
        self._holding = False
        self._press_time = None

        # attach button callbacks
        self.wh.on_button_press(self._on_button_press)
        self.wh.on_button_release(self._on_button_release)

        # loop stop
        self._stop = Event()

    # ---------------------
    # Input callbacks
    # ---------------------
    def _on_button_press(self):
        self._press_time = time()
        self._holding = True
        # start a thread to watch for starting cycling after LONG_PRESS_FOR_CYCLE
        Thread(target=self._hold_watcher, daemon=True).start()

    def _on_button_release(self):
        press_duration = time() - (self._press_time or time())
        self._holding = False

        # if cycling thread active, stop it (it will have updated menu_selected)
        if self._cycle_thread and self._cycle_thread.is_alive():
            self._cycle_stop.set()
            self._cycle_thread.join(timeout=0.2)
            self._cycle_stop.clear()
            # releasing after cycling does not auto-confirm; user must short-tap to select

        # If it was a short press (less than LONG_PRESS_FOR_CYCLE)
        if press_duration < LONG_PRESS_FOR_CYCLE:
            # Short press behavior:
            # - If menu active -> confirm selected option
            # - If no menu active:
            #    - If currently at a fork or direction blocked -> open menu (if multiple options)
            #    - Else do nothing (player keeps moving)
            if self.menu_active:
                self._confirm_menu_selection()
            else:
                # check available dirs
                neighbors = self._available_directions(self.player_x, self.player_y)
                # If we're currently moving in a direction and that direction is still valid, do nothing.
                if self.current_dir and self.current_dir in neighbors and len(neighbors) == 1:
                    # single continuing corridor — nothing to do on short press
                    return
                # if multiple options or current_dir blocked -> open menu
                if len(neighbors) > 1 or (self.current_dir and self.current_dir not in neighbors):
                    self._open_menu(neighbors)
                else:
                    # no options to open, no-op
                    pass

    def _hold_watcher(self):
        # Wait until LONG_PRESS_FOR_CYCLE; if still holding, start cycling
        start = self._press_time
        while self._holding and time() - start < LONG_PRESS_FOR_CYCLE:
            sleep(0.02)
        if self._holding:
            # only start cycling if menu is active and there are >1 options
            if self.menu_active and len(self.menu_options) > 1:
                self._start_cycling()

    def _start_cycling(self):
        # spawn a thread that cycles menu_selected every CYCLE_INTERVAL until stopped
        if self._cycle_thread and self._cycle_thread.is_alive():
            return
        self._cycle_stop.clear()
        def cycler():
            while not self._cycle_stop.is_set():
                self.menu_selected = (self.menu_selected + 1) % len(self.menu_options)
                self._render()
                # wait but break early if stop requested
                if self._cycle_stop.wait(CYCLE_INTERVAL):
                    break
        self._cycle_thread = Thread(target=cycler, daemon=True)
        self._cycle_thread.start()

    # ---------------------
    # Menu handling
    # ---------------------
    def _available_directions(self, x, y):
        # returns list of (dx,dy) in fixed absolute order but filtered (Option B)
        order = [ (0,-1), (1,0), (0,1), (-1,0) ]  # Up, Right, Down, Left
        return [d for d in order if self.maze.is_floor(x + d[0], y + d[1])]

    def _dir_name(self, d):
        dx,dy = d
        if dx == 1: return "Right"
        if dx == -1: return "Left"
        if dy == 1: return "Down"
        if dy == -1: return "Up"
        return "?"

    def _open_menu(self, neighbors):
        # neighbors is a list of (dx,dy) already filtered (Option B)
        self.menu_active = True
        self.menu_options = [ self._dir_name(d) for d in neighbors ]
        self.menu_selected = 0
        self._render()

    def _confirm_menu_selection(self):
        if not self.menu_active or not self.menu_options:
            return
        choice_name = self.menu_options[self.menu_selected]
        # find corresponding direction from available dirs
        for d in self._available_directions(self.player_x, self.player_y):
            if self._dir_name(d) == choice_name:
                self.current_dir = d
                self.running = True
                if self.start_time is None:
                    self.start_time = time()
                break
        # close menu
        self.menu_active = False
        self.menu_options = []
        self.menu_selected = 0
        self._render()

    # ---------------------
    # Movement & loop
    # ---------------------
    def _auto_step(self):
        if not self.current_dir:
            return
        nx = self.player_x + self.current_dir[0]
        ny = self.player_y + self.current_dir[1]
        if self.maze.is_floor(nx, ny):
            self.player_x = nx
            self.player_y = ny
            # If after stepping we are at a fork (>1 available) OR the current_dir is now blocked next step, stop and show menu
            neighbors = self._available_directions(self.player_x, self.player_y)
            if len(neighbors) > 1:
                self.running = False
                self._open_menu(neighbors)
            elif self.current_dir not in neighbors:
                # blocked after this step — show menu for available options
                self.running = False
                if neighbors:
                    self._open_menu(neighbors)
                else:
                    # fully trapped
                    self.current_dir = None
            # else continue moving next tick
        else:
            # blocked immediately — open menu for available directions
            neighbors = self._available_directions(self.player_x, self.player_y)
            self.running = False
            if neighbors:
                self._open_menu(neighbors)
            else:
                self.current_dir = None

    def _render(self):
        elapsed = (time() - self.start_time) if self.start_time else 0.0
        self.renderer.render_viewport(self.maze, self.player_x, self.player_y, self.treasure, elapsed, menu_lines=self.menu_options if self.menu_active else None, menu_selected=self.menu_selected)

    def start(self):
        self.loop_thread = Thread(target=self._loop, daemon=True)
        self.loop_thread.start()

    def _loop(self):
        while not self._stop.is_set():
            if self.menu_active:
                # render occasionally so cursor movement is visible
                self._render()
                sleep(0.12)
                continue
            if self.running and self.current_dir:
                self._auto_step()
                self._render()
                # check for treasure
                if (self.player_x, self.player_y) == self.treasure:
                    self.running = False
                    self.menu_active = True
                    self.menu_options = ["Replay", "Exit"]
                    self.menu_selected = 0
                    self._render()
                sleep(FPS_SLEEP)
            else:
                # idle render to update timer or show static
                self._render()
                sleep(0.2)

    def stop(self):
        self._stop.set()
        # stop cycling if active
        if self._cycle_thread and self._cycle_thread.is_alive():
            self._cycle_stop.set()
            self._cycle_thread.join(timeout=0.2)

# -------------------------
# Main
# -------------------------
def main():
    wh = WhisPlayBoard()
    wh.set_backlight(80)
    game = Game(wh)
    print("[GAME] Starting...")
    game.start()
    try:
        while True:
            sleep(0.5)
    except KeyboardInterrupt:
        print("[GAME] Exiting...")
    finally:
        game.stop()
        wh.cleanup()

if __name__ == "__main__":
    main()
