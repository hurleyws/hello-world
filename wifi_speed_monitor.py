#!/usr/bin/env python3
"""
Compact Vaporwave Wi-Fi Ping Monitor
(Linux-optimized, lightweight, small-screen friendly)

Features:
- Ping every 10s (configurable)
- Lightweight ~200 KB HTTP download to estimate Mbps
- Ping control chart only
- Mbps displayed as text (no second graph)
- Color-coded ping dots (green/yellow/red)
- Red pings logged to: ~/wifi_ping_alerts.csv
- Frameless, translucent, draggable + bottom-right resizable
- Right-click menu: Quit / Toggle Fullscreen
- Stays behind real apps (desktop widget vibe)
"""

import os
import time
import threading
from datetime import datetime
import subprocess
import urllib.request
from collections import deque
import tkinter as tk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ---------------- CONFIG ----------------
PING_INTERVAL_SEC = 10
PING_HOST = "1.1.1.1"

TEST_URL = "https://www.google.com/"
TARGET_BYTES = 200_000
DOWNLOAD_TIMEOUT = 5

GOOD_PING = 40
WARN_PING = 80

MAX_POINTS = 200
MIN_POINTS_FOR_LIMITS = 10

CSV_PATH = os.path.expanduser("~/wifi_ping_alerts.csv")

# Vaporwave aesthetic
BG = "#1b1035"
FG = "#f8f0ff"
PLOT_BG = "#241445"
ACCENT_PING = "#7ee7ff"
ACCENT_MEAN = "#fffb96"
ACCENT_CL = "#ff71ce"
GRID_COLOR = "#3a2b5b"

# Resize margin
RESIZE_MARGIN = 18


# ------------- MEASUREMENTS -------------

def measure_ping_ms():
    """Linux ping: returns float ms or None."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", PING_HOST],
            capture_output=True,
            text=True,
            timeout=3
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if "time=" in line:
                value = line.split("time=")[1].split()[0]
                return float(value)
    except Exception:
        return None
    return None


def measure_download_mbps():
    """Lightweight ~200 KB HTTP download."""
    try:
        start = time.perf_counter()
        total = 0

        with urllib.request.urlopen(TEST_URL, timeout=DOWNLOAD_TIMEOUT) as resp:
            while total < TARGET_BYTES:
                chunk = resp.read(min(16384, TARGET_BYTES - total))
                if not chunk:
                    break
                total += len(chunk)

        elapsed = time.perf_counter() - start
        if elapsed <= 0:
            return None

        return (total * 8 / elapsed) / 1_000_000
    except Exception:
        return None


# ----------- SPC (I-chart) -------------

def compute_ichart_limits(values):
    vals = [v for v in values if v is not None]
    if len(vals) < MIN_POINTS_FOR_LIMITS:
        return None, None, None

    mean = sum(vals) / len(vals)

    mrs = []
    prev = None
    for v in vals:
        if prev is not None:
            mrs.append(abs(v - prev))
        prev = v

    if not mrs:
        return None, None, None

    mrbar = sum(mrs) / len(mrs)
    ucl = mean + 2.66 * mrbar
    lcl = max(0, mean - 2.66 * mrbar)

    return mean, ucl, lcl


def color_for_ping(ms):
    if ms is None:
        return "white"
    if ms <= GOOD_PING:
        return "lime"
    elif ms <= WARN_PING:
        return "gold"
    return "red"


# ----------- CSV Logging --------------

def log_red_ping(timestamp, ms, mbps):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)

    exists = os.path.isfile(CSV_PATH)

    with open(CSV_PATH, "a") as f:
        if not exists:
            f.write("timestamp,weekday,time,ping_ms,mbps\n")

        f.write(f"{timestamp},{timestamp.strftime('%a')},"
                f"{timestamp.strftime('%H:%M:%S')},{ms},{mbps}\n")


# -------------- THE APP ----------------

class PingMonitorApp:
    def __init__(self, root):
        self.root = root
        self.data = deque(maxlen=MAX_POINTS)
        self.mbps_value = None

        self.root.configure(bg=BG)
        self.root.overrideredirect(True)     # Frameless
        self.root.attributes("-alpha", 0.90) # Translucent

        self._drag_mode = None

        self._build_ui()
        self._build_menu()

        # Bind mouse events for drag & resize
        self._make_interaction_bindings(self.canvas.get_tk_widget())

        # Worker thread
        self.stop_event = threading.Event()
        threading.Thread(target=self.worker, daemon=True).start()

        # Redraw loop
        self.root.after(1500, self.update_plot)

    # --- UI ---
    def _build_ui(self):
        fig = Figure(figsize=(4, 3), dpi=90)
        fig.patch.set_facecolor(BG)
        fig.subplots_adjust(bottom=0.18, top=0.88)

        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor(PLOT_BG)
        self.ax.set_title("Ping (ms)", color=FG, fontsize=10)
        self.ax.grid(True, color=GRID_COLOR, linestyle="--", alpha=0.4)
        self.ax.tick_params(colors=FG)
        for s in self.ax.spines.values():
            s.set_color(FG)

        self.line, = self.ax.plot([], [], color=ACCENT_PING, alpha=0.6)
        self.scatter = self.ax.scatter([], [])

        # mean/UCL/LCL lines
        self.mean_line = self.ax.axhline(0, color=ACCENT_MEAN, lw=1)
        self.ucl_line = self.ax.axhline(0, color=ACCENT_CL, lw=1, ls="--")
        self.lcl_line = self.ax.axhline(0, color=ACCENT_CL, lw=1, ls="--")
        self.mean_line.set_visible(False)
        self.ucl_line.set_visible(False)
        self.lcl_line.set_visible(False)

        self.canvas = FigureCanvasTkAgg(fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)


    # --- Right-click menu ---
    def _build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0, bg=BG, fg=FG)
        self.menu.add_command(label="Toggle Fullscreen",
                              command=self.toggle_fullscreen)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

        def popup(event):
            self.menu.tk_popup(event.x_root, event.y_root)

        self.root.bind("<Button-3>", popup)
        self.canvas.get_tk_widget().bind("<Button-3>", popup)

    # --- Mouse Interaction (Drag + Resize) ---
    def _make_interaction_bindings(self, widget):
        # Bind to the whole window, not just the canvas
        self.root.bind("<Button-1>", self._on_mouse_down)
        self.root.bind("<B1-Motion>", self._on_mouse_drag)
        self.root.bind("<ButtonRelease-1>", self._on_mouse_up)

    def _on_mouse_down(self, event):
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()
    
        # Resize zone (bottom-right corner)
        if event.x >= win_w - RESIZE_MARGIN and event.y >= win_h - RESIZE_MARGIN:
            self._drag_mode = "resize"
            self.start_w = win_w
            self.start_h = win_h
        else:
            self._drag_mode = "move"
    
        self.start_x = event.x_root
        self.start_y = event.y_root
    
    def _on_mouse_drag(self, event):
        dx = event.x_root - self.start_x
        dy = event.y_root - self.start_y
    
        if self._drag_mode == "move":
            new_x = self.root.winfo_x() + dx
            new_y = self.root.winfo_y() + dy
            self.root.geometry(f"+{new_x}+{new_y}")
    
        elif self._drag_mode == "resize":
            new_w = max(300, self.start_w + dx)
            new_h = max(220, self.start_h + dy)
            self.root.geometry(f"{new_w}x{new_h}")
    
        self.start_x = event.x_root
        self.start_y = event.y_root
    
    def _on_mouse_up(self, event):
        self._drag_mode = None

    # --- Fullscreen ---
    def toggle_fullscreen(self):
        if self.root.attributes("-fullscreen"):
            self.root.attributes("-fullscreen", False)
        else:
            self.root.attributes("-fullscreen", True)

    # --- Quit ---
    def quit(self):
        self.stop_event.set()
        self.root.destroy()

    # --- Worker thread ---
    def worker(self):
        while not self.stop_event.is_set():
            ts = datetime.now()

            ping_ms = measure_ping_ms()
            mbps = measure_download_mbps()

            self.data.append((ts, ping_ms, mbps))

            if ping_ms is not None and ping_ms > WARN_PING:
                log_red_ping(ts, ping_ms, mbps)

            time.sleep(PING_INTERVAL_SEC)

    # --- Plot updates ---
    def update_plot(self):
        if self.data:
            ping_vals = [p for (_, p, _) in self.data if p is not None]
            x = list(range(len(ping_vals)))

            self.line.set_data(x, ping_vals)

            colors = [color_for_ping(v) for v in ping_vals]
            self.scatter.remove()
            self.scatter = self.ax.scatter(x, ping_vals, c=colors, s=28, zorder=3)

            self.ax.set_xlim(-1, len(x) + 1)

            # Control limits
            mean, ucl, lcl = compute_ichart_limits(ping_vals)
            if mean is not None:
                self.mean_line.set_ydata([mean, mean])
                self.ucl_line.set_ydata([ucl, ucl])
                self.lcl_line.set_ydata([lcl, lcl])
                self.mean_line.set_visible(True)
                self.ucl_line.set_visible(True)
                self.lcl_line.set_visible(True)

                ymin = min(min(ping_vals), lcl)
                ymax = max(max(ping_vals), ucl)
            else:
                self.mean_line.set_visible(False)
                self.ucl_line.set_visible(False)
                self.lcl_line.set_visible(False)
                ymin = min(ping_vals) if ping_vals else 0
                ymax = max(ping_vals) if ping_vals else 1

            self.ax.set_ylim(max(0, ymin * 0.8), ymax * 1.2)


        self.canvas.draw_idle()
        self.root.after(1500, self.update_plot)


def main():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-type", "dock")
    root.attributes("-alpha", 0.90)
    root.lower()
    root.attributes("-topmost", False)

    root.title("Ping Monitor")
    root.update_idletasks()

    # Apply EWMH hints using wmctrl
    os.system('wmctrl -r "Ping Monitor" -b add,below')
    os.system('wmctrl -r "Ping Monitor" -b add,sticky')
    os.system('wmctrl -r "Ping Monitor" -b add,skip_taskbar')
    os.system('wmctrl -r "Ping Monitor" -b add,skip_pager')

    # Keep behind if something tries to raise it
    def keep_back(event=None):
        root.lower()
        os.system('wmctrl -r "Ping Monitor" -b add,below')

    root.bind("<FocusIn>", keep_back)
    root.bind("<Map>", keep_back)

    app = PingMonitorApp(root)
    root.mainloop()


if __name__ == "__main__": 
    main()




