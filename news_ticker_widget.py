#!/usr/bin/env python3
"""
Synthwave / Brogrammer News Ticker Widget

- Frameless, translucent Tkinter window
- Pulls headlines from RSS feeds (configurable)
- Rotates through headlines every few seconds
- Multiple lines visible at once, each with a different neon color
- Draggable and resizable (from bottom-right corner)
- Right-click menu: Refresh Now / Close
"""

import threading
import time
from collections import deque
from xml.etree import ElementTree as ET
from urllib.request import urlopen

import tkinter as tk

# -------- CONFIG --------

# RSS feeds to pull headlines from
RSS_FEEDS = [
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "https://feeds.bbci.co.uk/news/rss.xml",
]

# How many headlines to show at once
VISIBLE_ROWS = 10

# How often to rotate displayed headlines (ms)
ROTATE_INTERVAL_MS = 6000  # 3 seconds

# How often to refresh feeds (seconds)
REFRESH_INTERVAL_SEC = 600  # 10 minutes

# Window visuals
BG = "#1b1035"        # same base background as Wi-Fi widget
FG = "#f8f0ff"        # default text color
ALPHA = 0.9           # translucency

# Brogrammer-style neon line colors
BROGRAMMER_COLORS = [
    "#ffffff",  # bright white (high contrast)
    "#01cdfe",  # bright cyan
    "#00ffcc",  # aqua / teal (pops hard on dark bg)
    "#05ffa1",  # neon green
    "#fffb96",  # soft neon yellow
    "#f05e48",  # orange-red
]


# Resizing behavior
RESIZE_MARGIN = 16   # px from bottom-right corner
MIN_WIDTH = 500
MIN_HEIGHT = 120

# ------------------------


def fetch_headlines_from_feed(url, timeout=10):
    """
    Fetch headlines (titles) from an RSS or Atom feed URL.
    Returns a list of strings.
    """
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = resp.read()
    except Exception:
        return []

    try:
        root = ET.fromstring(data)
    except Exception:
        return []

    titles = []

    # Try RSS: <rss><channel><item><title>...</title></item></channel></rss>
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())

    # Try Atom: <feed><entry><title>...</title></entry></feed>
    if not titles:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            if title_el is not None and title_el.text:
                titles.append(title_el.text.strip())

    return titles


def fetch_all_headlines():
    """
    Fetch and merge headlines from all configured feeds.
    Deduplicates by title, keeps order as they come.
    """
    seen = set()
    merged = []
    for url in RSS_FEEDS:
        titles = fetch_headlines_from_feed(url)
        for t in titles:
            if t not in seen:
                seen.add(t)
                merged.append(t)
    return merged


class NewsTickerApp:
    def _on_root_resize(self, event):
        # Update wraplength so text wraps nicely inside current width
        wrap = max(200, event.width - 40)  # little padding
        for lbl in self.line_labels:
            lbl.config(wraplength=wrap)

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg=BG)

        # Data
        self.headlines = deque()
        self.current_index = 0

        # Thread control
        self.stop_event = threading.Event()
        self.fetch_thread = None

        # Drag/resize state
        self._drag_mode = None  # "move" or "resize"
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._orig_x = 0
        self._orig_y = 0
        self._orig_w = 0
        self._orig_h = 0

        # Build UI
        self._build_ui()

        # Adjust text wrapping when window is resized
        self.root.bind("<Configure>", self._on_root_resize)


        # Make window draggable/resizable
        self._make_drag_resize(self.root)
        self._make_drag_resize(self.main_frame)

        # Right-click menu
        self._build_context_menu()

        # Close on Esc
        self.root.bind("<Escape>", lambda e: self.on_close())

        # Start fetching headlines
        self._start_fetch_thread()

        # Start rotation timer
        self._schedule_rotate()

        # Periodic background refresh
        self._schedule_refresh()

        # On close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        # Outer padding/frame
        self.main_frame = tk.Frame(self.root, bg=BG, bd=8)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Title / header
        self.header = tk.Label(
            self.main_frame,
            text=" NEWS TICKER ",
            bg=BG,
            fg="#ffffff",
            font=("Consolas", 12, "bold"),
        )
        self.header.pack(anchor="w")

        # Container for lines
        self.lines_frame = tk.Frame(self.main_frame, bg=BG)
        self.lines_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self.line_labels = []
        for i in range(VISIBLE_ROWS):
            color = BROGRAMMER_COLORS[i % len(BROGRAMMER_COLORS)]
            lbl = tk.Label(
                self.lines_frame,
                text="",
                bg=BG,
                fg=color,
                anchor="w",
                justify="left",
                font=("Consolas", 11,"bold"),
                wraplength=800,
            )
            lbl.pack(fill=tk.X, anchor="w")
            self.line_labels.append(lbl)

        # Initial message
        self._set_status_message("Fetching latest headlines...")

    def _build_context_menu(self):
        self.context_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=BG,
            fg=FG,
            activebackground="#241445",
            activeforeground=FG,
        )
        self.context_menu.add_command(label="Refresh now", command=self.refresh_now)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Close", command=self.on_close)

        def show_menu(event):
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

        self.root.bind("<Button-3>", show_menu)
        self.main_frame.bind("<Button-3>", show_menu)
        self.lines_frame.bind("<Button-3>", show_menu)
        for lbl in self.line_labels:
            lbl.bind("<Button-3>", show_menu)

    # ---------- Dragging / resizing ----------

    def _make_drag_resize(self, widget):
        widget.bind("<ButtonPress-1>", self._on_mouse_down)
        widget.bind("<B1-Motion>", self._on_mouse_drag)

    def _on_mouse_down(self, event):
        self.root.update_idletasks()
        win_x = self.root.winfo_x()
        win_y = self.root.winfo_y()
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()

        click_x = event.x_root - win_x
        click_y = event.y_root - win_y

        if click_x >= win_w - RESIZE_MARGIN and click_y >= win_h - RESIZE_MARGIN:
            self._drag_mode = "resize"
        else:
            self._drag_mode = "move"

        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._orig_x = win_x
        self._orig_y = win_y
        self._orig_w = win_w
        self._orig_h = win_h

    def _on_mouse_drag(self, event):
        if self._drag_mode is None:
            return

        dx = event.x_root - self._drag_start_x
        dy = event.y_root - self._drag_start_y

        if self._drag_mode == "move":
            new_x = self._orig_x + dx
            new_y = self._orig_y + dy
            self.root.geometry(f"+{new_x}+{new_y}")
        elif self._drag_mode == "resize":
            new_w = max(MIN_WIDTH, self._orig_w + dx)
            new_h = max(MIN_HEIGHT, self._orig_h + dy)
            self.root.geometry(f"{int(new_w)}x{int(new_h)}+{self._orig_x}+{self._orig_y}")

    # ---------- Fetching headlines ----------

    def _start_fetch_thread(self):
        if self.fetch_thread and self.fetch_thread.is_alive():
            return
        self.fetch_thread = threading.Thread(
            target=self._fetch_loop,
            daemon=True,
        )
        self.fetch_thread.start()

    def _fetch_loop(self):
        while not self.stop_event.is_set():
            try:
                headlines = fetch_all_headlines()
                if headlines:
                    self.headlines = deque(headlines)
                    self.current_index = 0
                    self._set_status_message(f"{len(headlines)} headlines loaded.")
                else:
                    if not self.headlines:
                        self._set_status_message("No headlines found.")
            except Exception:
                if not self.headlines:
                    self._set_status_message("Error fetching headlines.")
            # One fetch per REFRESH_INTERVAL_SEC; timer also triggers
            break

    def _set_status_message(self, msg: str):
        def apply():
            if self.line_labels:
                self.line_labels[0].config(text=f"[{msg}]")
                for lbl in self.line_labels[1:]:
                    lbl.config(text="")
        self.root.after(0, apply)

    def refresh_now(self):
        # Trigger immediate refresh in a new thread
        threading.Thread(target=self._fetch_loop, daemon=True).start()

    # ---------- Rotating display ----------

    def _schedule_rotate(self):
        self._rotate_headlines()
        self.root.after(ROTATE_INTERVAL_MS, self._schedule_rotate)

    def _rotate_headlines(self):
        """
        Log-style behavior:
        - Each tick, insert ONE new headline at the top
        - Push existing lines down
        - Oldest line falls off the bottom
        """
        if not self.headlines:
            return

        n = len(self.headlines)
        if n == 0:
            return

        # Shift existing lines down (bottom to top)
        for i in range(len(self.line_labels) - 1, 0, -1):
            above_text = self.line_labels[i - 1].cget("text")
            self.line_labels[i].config(text=above_text)

        # Insert next headline at the top
        text = self.headlines[self.current_index]
        self.line_labels[0].config(text=f"• {text}")

        # Advance pointer for next time
        self.current_index = (self.current_index + 1) % n


    def _schedule_refresh(self):
        # Periodic background refresh of feeds
        if not self.stop_event.is_set():
            self.refresh_now()
            self.root.after(REFRESH_INTERVAL_SEC * 1000, self._schedule_refresh)

    # ---------- Shutdown ----------

    def on_close(self):
        self.stop_event.set()
        if self.fetch_thread and self.fetch_thread.is_alive():
            self.fetch_thread.join(timeout=1.0)
        self.root.destroy()


def main():
    root = tk.Tk()
    # Frameless & translucent
    root.overrideredirect(True)
    root.attributes("-alpha", ALPHA)

    # Reasonable starting size, bottom of primary screen
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = 900
    h = 260
    x = (sw - w) // 2
    y = sh - h - 80
    root.geometry(f"{w}x{h}+{x}+{y}")

    app = NewsTickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
