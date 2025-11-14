#!/usr/bin/env python3
"""
ASCII Dungeon Maze Game for Whisplay (single-button control)

Controls (single physical button):
- Short press (release quickly): Select / Confirm
- Double-tap (two short releases within window): Cycle menu selection
- Long press (>= 2.0s): Pause / resume (optional)
"""

from time import time, sleep
import random
import sys
import os
from threading import Thread, Event

# Use your project's WhisPlay and utils
sys.path.append(os.path.abspath("."))          # current folder
sys.path.append(os.path.abspath("../Driver"))  # where WhisPlay.py typically is

try:
    from WhisPlay import WhisPlayBoard
except Exception as e:
    raise RuntimeError("Couldn't import WhisPlayBoard. Ensure WhisPlay.py is in ../Driver or project root.") from e

from utils import ImageUtils

from PIL import Image, ImageDraw, ImageFont

# -------------------------
# Config
# -------------------------
CELL_W = 8    # pixel width per char cell (we compute based on screen later)
CELL_H = 12   # pixel height per char cell (we compute based on screen later)
DOUBLE_PRESS_WINDOW = 0.45
LONG_PRESS_SECONDS = 2.0

# ASCII glyphs for Style C (rounded block look)
GL_WALL = "▓"
GL_FLOOR = "."
GL_PLAYER = "¡"
GL_TREASURE = "☼"

# -------------------------
# Maze generator: recursive backtracker (grid with odd dims)
# -------------------------
class Maze:
    def __init__(self, width_cells, height_cells):
        # ensure odd dimensions for proper maze (walls between cells)
        self.w = width_cells if width_cells % 2 == 1 else width_cells - 1
        self.h = height_cells if height_cells % 2 == 1 else height_cells - 1
        self.grid = [[1 for _ in range(self.w)] for _ in range(self.h)]
        self._generate()

    def _neighbors(self, cx, cy):
        # 2-step neighbors (up/down/left/right)
        n = []
        deltas = [ (0, -2), (2, 0), (0, 2), (-2, 0) ]
        for dx, dy in deltas:
            nx, ny = cx + dx, cy + dy
            if 0 < nx < self.w-1 and 0 < ny < self.h-1:
                n.append((nx, ny))
        return n

    def _generate(self):
        # start at (1,1)
        stack = [(1,1)]
        self.grid[1][1] = 0
        while stack:
            cx, cy = stack[-1]
            neigh = [n for n in self._neighbors(cx, cy) if self.grid[n[1]][n[0]] == 1]
            if not neigh:
                stack.pop()
                continue
            nx, ny = random.choice(neigh)
            # knock down wall between
            wall_x = (cx + nx) // 2
            wall_y = (cy + ny) // 2
            self.grid[wall_y][wall_x] = 0
            self.grid[ny][nx] = 0
            stack.append((nx, ny))

    def place_treasure_farthest_from(self, sx, sy):
        # simple BFS to find farthest cell
        from collections import deque
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
        tx, ty, _ = far
        return (tx, ty)

    def is_floor(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.grid[y][x] == 0
        return False

# -------------------------
# Renderer: uses PIL to draw ASCII glyphs into an image then convert to RGB565
# -------------------------
class Renderer:
    def __init__(self, whisplay):
        self.wh = whisplay
        # compute grid size (characters) based on available resolution and chosen cell size
        # but we pick font size to match the cell sizes to maximize fit
        self.screen_w = self.wh.LCD_WIDTH
        self.screen_h = self.wh.LCD_HEIGHT
        # target char counts approximated from desired cell size:
        self.cols = self.screen_w // CELL_W
        self.rows = self.screen_h // CELL_H
        # choose font size to fit CELL_W x CELL_H
        # use default PIL font to ensure it exists; try to pick approx the cell height
        try:
            self.font = ImageFont.truetype("DejaVuSansMono.ttf", CELL_H - 1)
        except Exception:
            self.font = ImageFont.load_default()
        # small padding to center text in cell
        self.cell_w = self.screen_w / self.cols
        self.cell_h = self.screen_h / self.rows

    def render_viewport(self, maze, player_x, player_y, treasure_pos, elapsed_s, menu_lines=None, menu_selected=0):
        """
        Render a viewport centered on player to the device.
        - maze: Maze object
        - player_x, player_y: coordinates in maze grid
        - treasure_pos: (x,y)
        - elapsed_s: float seconds for timer
        - menu_lines: list of str for menu (if None, no menu)
        """
        # compute viewport in maze-coordinates centered on player
        half_cols = self.cols // 2
        half_rows = self.rows // 2

        left = player_x - half_cols
        top = player_y - half_rows

        # create image
        img = Image.new("RGB", (self.screen_w, self.screen_h), (0,0,0))
        draw = ImageDraw.Draw(img)

        # draw time header across top - single line
        time_text = f"Time: {elapsed_s:.1f}s"
        draw.text((4,2), time_text, font=self.font, fill=(255,255,255))

        # draw maze area
        # compute starting pixel for grid area slightly below header
        header_h = int(self.cell_h)  # ~one row used for header
        grid_y_offset = header_h

        for r in range(self.rows - 1):  # -1 leaving header row
            for c in range(self.cols):
                maze_x = left + c
                maze_y = top + r
                px = int(c * self.cell_w)
                py = int(grid_y_offset + r * self.cell_h)
                char = " "
                if 0 <= maze_x < maze.w and 0 <= maze_y < maze.h:
                    if (maze_x, maze_y) == treasure_pos:
                        char = GL_TREASURE
                    elif (maze_x, maze_y) == (player_x, player_y):
                        char = GL_PLAYER
                    else:
                        char = GL_FLOOR if maze.grid[maze_y][maze_x] == 0 else GL_WALL
                else:
                    char = GL_WALL
                # draw character centered in cell
                # small padding
                draw.text((px+1, py+1), char, font=self.font, fill=(255,255,255))

        # if menu_lines present, draw a simple translucent box and menu text centered
        if menu_lines:
            # compute box area
            box_w = int(self.screen_w * 0.7)
            box_h = int(self.screen_h * 0.35)
            box_x = (self.screen_w - box_w)//2
            box_y = (self.screen_h - box_h)//2
            # draw dark rectangle
            draw.rectangle([box_x, box_y, box_x+box_w, box_y+box_h], fill=(20,20,20))
            # border
            draw.rectangle([box_x, box_y, box_x+box_w, box_y+box_h], outline=(180,180,180), width=2)
            # draw menu lines; highlight selected
            line_h = int(box_h / max(1, len(menu_lines)+1))
            for idx, line in enumerate(menu_lines):
                tx = box_x + 12
                ty = box_y + 12 + idx*line_h
                prefix = ">" if idx == menu_selected else " "
                draw.text((tx, ty), prefix + " " + line, font=self.font, fill=(255,255,255))

        # convert to rgb565 buffer using your project's ImageUtils
        rgb565 = ImageUtils.image_to_rgb565(img, self.wh.LCD_WIDTH, self.wh.LCD_HEIGHT)
        self.wh.draw_image(0, 0, self.wh.LCD_WIDTH, self.wh.LCD_HEIGHT, rgb565)

# -------------------------
# Game engine
# -------------------------
class Game:
    def __init__(self, whisplay):
        self.wh = whisplay
        # compute maze size in cells (a little larger than viewport)
        self.renderer = Renderer(self.wh)
        # Make maze larger than viewport to allow exploration
        maze_cols = max(21, self.renderer.cols * 3 // 2 | 1)   # odd
        maze_rows = max(21, self.renderer.rows * 3 // 2 | 1)   # odd
        # ensure odd numbers
        maze_cols = maze_cols if maze_cols % 2 == 1 else maze_cols+1
        maze_rows = maze_rows if maze_rows % 2 == 1 else maze_rows+1

        self.maze = Maze(maze_cols, maze_rows)
        # start at first floor cell near (1,1)
        self.player_x, self.player_y = 1, 1
        self.treasure = self.maze.place_treasure_farthest_from(self.player_x, self.player_y)
        self.start_time = None
        self.running = False
        self.menu_active = False
        self.menu_options = []
        self.menu_selected = 0

        # input timing
        self.last_release_time = 0
        self.last_press_time = None
        self.double_window = DOUBLE_PRESS_WINDOW
        self.long_press_s = LONG_PRESS_SECONDS

        # stop event for background loop
        self._stop = Event()

        # attach button callbacks
        self.wh.on_button_press(self._on_button_press)
        self.wh.on_button_release(self._on_button_release)

    # button handling
    def _on_button_press(self):
        self.last_press_time = time()

    def _on_button_release(self):
        now = time()
        duration = now - (self.last_press_time or now)
        # detect long press
        if duration >= self.long_press_s:
            # toggle pause
            self.running = not self.running
            print("[GAME] Long press: toggled running ->", self.running)
            return

        # detect double-tap versus single
        if now - self.last_release_time <= self.double_window:
            # double tap: cycle menu selection if menu active; otherwise treat as "cycle" (noop)
            if self.menu_active:
                self.menu_selected = (self.menu_selected + 1) % max(1, len(self.menu_options))
                self._render()
            else:
                # no menu yet: trigger a cycle action by opening menu at forks if present
                # we'll reuse single-press behavior here: if menu appears, double-tap will change selection
                self._handle_short_press(double=True)
        else:
            # schedule single press handler
            self._handle_short_press(double=False)

        self.last_release_time = now

    def _handle_short_press(self, double=False):
        # if menu is active and it's a short press -> confirm selection
        if self.menu_active:
            # confirm selection
            choice = self.menu_options[self.menu_selected]
            self._apply_choice(choice)
            return

        # otherwise (no menu active) we want to:
        # - if at a fork, open menu
        # - else, toggle running (start/stop)
        neighbors = self._available_directions(self.player_x, self.player_y)
        if len(neighbors) > 1:
            # open menu with string names
            self.menu_options = [ self._dir_name(d) for d in neighbors ]
            self.menu_selected = 0
            self.menu_active = True
            self._render()
            return
        else:
            # toggle run / step
            self.running = not self.running
            if self.running and self.start_time is None:
                self.start_time = time()
            self._render()

    def _dir_name(self, d):
        dx,dy = d
        if dx == 1: return "Right"
        if dx == -1: return "Left"
        if dy == 1: return "Down"
        if dy == -1: return "Up"
        return "?"

    def _apply_choice(self, choice_name):
        # convert choice_name back to direction: find first neighbor matching the name
        neighbors = self._available_directions(self.player_x, self.player_y)
        for d in neighbors:
            if self._dir_name(d) == choice_name:
                # move one step into that direction
                self.player_x += d[0]
                self.player_y += d[1]
                break
        self.menu_active = False
        self.menu_options = []
        self.menu_selected = 0
        if self.start_time is None:
            self.start_time = time()
        self.running = True
        self._render()

    def _available_directions(self, x, y):
        dirs = []
        for dx,dy in [ (1,0),(-1,0),(0,1),(0,-1) ]:
            nx, ny = x+dx, y+dy
            if self.maze.is_floor(nx, ny):
                dirs.append((dx,dy))
        return dirs

    def _auto_step(self):
        # If only one forward path (or multiple but running), advance one cell toward an available neighbor.
        neighbors = self._available_directions(self.player_x, self.player_y)
        if not neighbors:
            # trapped
            self.running = False
            return
        if len(neighbors) == 1:
            d = neighbors[0]
            self.player_x += d[0]
            self.player_y += d[1]
            return
        # multiple neighbors: stop and open menu
        self.running = False
        self.menu_options = [self._dir_name(d) for d in neighbors]
        self.menu_selected = 0
        self.menu_active = True

    def _render(self):
        elapsed = 0.0
        if self.start_time:
            elapsed = time() - self.start_time
        self.renderer.render_viewport(self.maze, self.player_x, self.player_y, self.treasure, elapsed, menu_lines=self.menu_options if self.menu_active else None, menu_selected=self.menu_selected)

    def start(self):
        # start main game loop in a background thread
        self.loop_thread = Thread(target=self._loop, daemon=True)
        self.loop_thread.start()

    def _loop(self):
        # main loop handles auto movement and rendering
        fps_sleep = 0.12
        while not self._stop.is_set():
            if self.menu_active:
                # just render and wait for user selection
                self._render()
                sleep(0.15)
                continue

            if self.running:
                # auto step then re-render
                self._auto_step()
                self._render()
                # check for treasure
                if (self.player_x, self.player_y) == self.treasure:
                    # win
                    self.running = False
                    self.menu_active = True
                    self.menu_options = ["Replay", "Exit"]
                    self.menu_selected = 0
                    self._render()
                sleep(fps_sleep)
            else:
                # idle rendering occasionally in case timer updates or menu
                self._render()
                sleep(0.2)

    def stop(self):
        self._stop.set()

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
        # Keep main thread alive. Button callbacks drive game.
        while True:
            sleep(0.5)
    except KeyboardInterrupt:
        print("[GAME] Exiting...")
    finally:
        game.stop()
        wh.cleanup()

if __name__ == "__main__":
    main()
