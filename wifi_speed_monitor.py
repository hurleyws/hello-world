#!/usr/bin/env python3
"""
Wi-Fi Speed & Health Monitor (Vaporwave, borderless, resizable)

- Lightweight check every 10 seconds:
  - Ping a host (latency)
  - Small ~200 KB HTTP download to estimate Mbps
- Full Speedtest (download-only) every 30 minutes:
  - Uses speedtest-cli to get more accurate speed
- Two control charts:
  - Top: light-check ping (ms)
  - Bottom: full-test download (Mbps)
- After 10 valid points per chart:
  - Mean center line + UCL/LCL via I-chart (moving range method)
- Frameless, translucent window:
  - Color-coded points (green/yellow/red) for performance
  - Draggable
  - Resizable from the bottom-right corner
  - Right-click context menu: Toggle Fullscreen / Close
  - Opens in fullscreen by emulating it (no -fullscreen attribute)
"""

import threading
import time
from datetime import datetime
from collections import deque
import subprocess
import urllib.request
import json
import shutil
import ctypes
from ctypes import wintypes


import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg



# ===== CONFIGURATION =====
TEST_INTERVAL_SECONDS = 10               # Time between checks
FULL_TEST_INTERVAL_SECONDS = 1800        # 30 minutes
MAX_POINTS = 300                         # Max observations to keep
MIN_POINTS_FOR_LIMITS = 10               # Min points for SPC lines

PING_HOST = "1.1.1.1"                    # For light checks
TEST_URL = "https://www.google.com/"     # Lightweight download target
TARGET_BYTES = 200_000                   # ~200 KB per light check
PING_TIMEOUT_SECONDS = 3
DOWNLOAD_TIMEOUT_SECONDS = 5

# "Good" performance thresholds (tune to taste)
GOOD_PING_MS = 40        # <= good, <= WARN is yellow, > WARN is red
WARN_PING_MS = 80

GOOD_DOWNLOAD_MBPS = 200  # >= good, >= WARN is yellow, < WARN is red
WARN_DOWNLOAD_MBPS = 100

# Vaporwave colors
BG = "#1b1035"           # main background
PLOT_BG = "#241445"
FG = "#f8f0ff"           # text
ACCENT_PING_LINE = "#7ee7ff"  # soft cyan line
ACCENT_FULL_LINE = "#ff9ad6"  # soft pink line
ACCENT_TITLE = "#b967ff"      # purple
ACCENT_MEAN = "#fffb96"       # soft yellow
ACCENT_UCL = "#ff71ce"
ACCENT_LCL = "#ff71ce"
GRID_COLOR = "#3a2b5b"

# Resizing behavior
RESIZE_MARGIN = 24       # px from bottom-right corner for resize grab
MIN_WIDTH = 500
MIN_HEIGHT = 400
# ==========================
# Try to find the speedtest-cli command
SPEEDTEST_CLI = shutil.which("speedtest-cli") or shutil.which("speedtest")


def measure_ping_ms(host: str, timeout: int = PING_TIMEOUT_SECONDS) -> float | None:
    """Measure ping in ms to a host using Windows 'ping'. Returns None on failure."""
    try:
        # Common kwargs for subprocess.run
        kwargs = dict(
            args=["ping", "-n", "1", host],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # On Windows, prevent a console window from appearing
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(**kwargs)

        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if "time=" in line.lower():
                parts = line.split("time=")[-1]
                num = ""
                for ch in parts:
                    if ch.isdigit() or ch == ".":
                        num += ch
                    else:
                        break
                if num:
                    return float(num)
        return None
    except Exception:
        return None



def measure_download_mbps(
    url: str,
    target_bytes: int = TARGET_BYTES,
    timeout: int = DOWNLOAD_TIMEOUT_SECONDS,
) -> float | None:
    """
    Lightweight download: grab up to `target_bytes` from `url` and estimate Mbps.
    Uses a small amount of data (~200 KB). Returns None on failure.
    """
    try:
        start = time.perf_counter()
        total = 0

        with urllib.request.urlopen(url, timeout=timeout) as resp:
            while total < target_bytes:
                chunk_size = min(16384, target_bytes - total)
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)

        elapsed = time.perf_counter() - start
        if elapsed <= 0 or total == 0:
            return None

        mbps = (total * 8 / elapsed) / 1_000_000  # bits/s → Mbps
        return mbps
    except Exception:
        return None


def compute_ichart_limits(values, min_points: int = MIN_POINTS_FOR_LIMITS):
    """
    Compute I-chart mean, UCL, LCL using moving range.
    values: list of floats
    Returns (mean, UCL, LCL) or (None, None, None) if not enough data.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < min_points:
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

    mr_bar = sum(mrs) / len(mrs)
    # I-chart constants: sigma ≈ MRbar / 1.128; 3σ ≈ 2.66 * MRbar
    ucl = mean + 2.66 * mr_bar
    lcl = max(0.0, mean - 2.66 * mr_bar)

    return mean, ucl, lcl


def color_for_ping(p: float) -> str:
    if p <= GOOD_PING_MS:
        return "lime"
    elif p <= WARN_PING_MS:
        return "gold"
    else:
        return "red"


def color_for_download(d: float) -> str:
    if d >= GOOD_DOWNLOAD_MBPS:
        return "lime"
    elif d >= WARN_DOWNLOAD_MBPS:
        return "gold"
    else:
        return "red"

# ----- Windows multi-monitor helper -----

def get_current_monitor_geometry(root):
    """
    Return (width, height, left, top) for the monitor that currently
    contains the center of the Tk window.
    Windows-only; safe no-op fallback if something goes wrong.
    """
    try:
        user32 = ctypes.windll.user32

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        # Make sure geometry is up to date
        root.update_idletasks()
        win_x = root.winfo_x()
        win_y = root.winfo_y()
        win_w = root.winfo_width()
        win_h = root.winfo_height()

        # Use window center to pick monitor
        cx = win_x + win_w // 2
        cy = win_y + win_h // 2

        MONITOR_DEFAULTTONEAREST = 2
        monitor = user32.MonitorFromPoint(
            wintypes.POINT(cx, cy),
            MONITOR_DEFAULTTONEAREST
        )

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(monitor, ctypes.byref(info))

        left = info.rcMonitor.left
        top = info.rcMonitor.top
        right = info.rcMonitor.right
        bottom = info.rcMonitor.bottom

        width = right - left
        height = bottom - top
        return width, height, left, top

    except Exception:
        # Fallback: just use Tk's single-screen idea
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        return sw, sh, 0, 0


class SpeedMonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg=BG)

        # Data: deque of (timestamp, ping_ms, down_mbps, method)
        self.data = deque(maxlen=MAX_POINTS)

        # Thread control
        self.stop_event = threading.Event()
        self.worker_thread = None

        # Full-test tracking
        self.last_full_test_ts: float | None = None
        self.speedtest_client: speedtest.Speedtest | None = None

        # Drag/resize state
        self.is_fullscreen = False
        self.saved_geometry: str | None = None
        self._drag_mode = None      # "move" or "resize"
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._orig_x = 0
        self._orig_y = 0
        self._orig_w = 0
        self._orig_h = 0

        # Build UI
        self._build_ui()

        # Start worker thread
        self._start_worker()

        # Start periodic plot updates
        self._schedule_plot_update()

        # Shutdown behavior
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda e: self.on_close())

        # Make window draggable/resizable (when not fullscreen)
        self._make_drag_resize(self.root)
        self._make_drag_resize(self.canvas.get_tk_widget())

        # Right-click context menu
        self._build_context_menu()

    # ---------- UI building ----------

    def _build_ui(self):
        # Top spacer
        spacer = tk.Frame(self.root, bg=BG, height=6)
        spacer.pack(side=tk.TOP, fill=tk.X)

        # Figure with 2 subplots
        fig = Figure(figsize=(6, 5), dpi=100)
        fig.patch.set_facecolor(BG)
        fig.subplots_adjust(hspace=0.6)

        self.ax_ping = fig.add_subplot(211)
        self.ax_full = fig.add_subplot(212)

        def style_ax(ax, title, ylabel):
            ax.set_title(title, color=ACCENT_TITLE, fontsize=11)
            ax.set_xlabel("", color=FG)
            ax.set_ylabel(ylabel, color=FG)
            ax.set_facecolor(PLOT_BG)
            ax.grid(True, linestyle="--", alpha=0.4, color=GRID_COLOR)
            ax.tick_params(colors=FG, labelcolor=FG)
            for spine in ax.spines.values():
                spine.set_color(FG)

        style_ax(self.ax_ping, "Light Check: Ping (ms)", "Ping (ms)")
        style_ax(self.ax_full, "Full Test: Download Speed (Mbps)", "Download (Mbps)")

        # Ping plot
        self.ping_line, = self.ax_ping.plot(
            [], [], linestyle="-", color=ACCENT_PING_LINE, alpha=0.6
        )
        self.ping_scatter = self.ax_ping.scatter([], [])

        self.ping_mean_line = self.ax_ping.axhline(
            0, linestyle="-", linewidth=1, color=ACCENT_MEAN
        )
        self.ping_ucl_line = self.ax_ping.axhline(
            0, linestyle="--", linewidth=1, color=ACCENT_UCL
        )
        self.ping_lcl_line = self.ax_ping.axhline(
            0, linestyle="--", linewidth=1, color=ACCENT_LCL
        )
        self.ping_mean_line.set_visible(False)
        self.ping_ucl_line.set_visible(False)
        self.ping_lcl_line.set_visible(False)

        # Full-test plot
        self.full_line, = self.ax_full.plot(
            [], [], linestyle="-", color=ACCENT_FULL_LINE, alpha=0.6
        )
        self.full_scatter = self.ax_full.scatter([], [])

        self.full_mean_line = self.ax_full.axhline(
            0, linestyle="-", linewidth=1, color=ACCENT_MEAN
        )
        self.full_ucl_line = self.ax_full.axhline(
            0, linestyle="--", linewidth=1, color=ACCENT_UCL
        )
        self.full_lcl_line = self.ax_full.axhline(
            0, linestyle="--", linewidth=1, color=ACCENT_LCL
        )
        self.full_mean_line.set_visible(False)
        self.full_ucl_line.set_visible(False)
        self.full_lcl_line.set_visible(False)

        # Embed the figure into Tkinter
        self.canvas = FigureCanvasTkAgg(fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_context_menu(self):
        self.context_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=BG,
            fg=FG,
            activebackground=PLOT_BG,
            activeforeground=FG,
        )
        self.context_menu.add_command(
            label="Toggle Fullscreen", command=self.toggle_fullscreen
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Close", command=self.on_close)

        def show_menu(event):
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

        self.root.bind("<Button-3>", show_menu)
        self.canvas.get_tk_widget().bind("<Button-3>", show_menu)

    # ---------- Dragging / resizing ----------

    def _make_drag_resize(self, widget):
        widget.bind("<ButtonPress-1>", self._on_mouse_down)
        widget.bind("<B1-Motion>", self._on_mouse_drag)

    def _on_mouse_down(self, event):
        if self.is_fullscreen:
            # No drag/resize in fullscreen
            return

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
        if self.is_fullscreen or self._drag_mode is None:
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

    # ---------- Worker / measurements ----------

    def _start_worker(self):
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(self.stop_event,),
            daemon=True,
        )
        self.worker_thread.start()

    def _init_speedtest_client(self):
        """
        Kept for compatibility, but we no longer use the Python speedtest module.
        Full tests use the external `speedtest-cli` command instead.
        """
        return

    def _run_full_test(self):
        """
        Run a full speed test (download-only) using the external speedtest-cli tool.
        Expects speedtest-cli to be installed and in PATH.
        """
        if SPEEDTEST_CLI is None:
            raise RuntimeError("speedtest-cli not found in PATH. Install with: pip install speedtest-cli")

        # Call speedtest-cli with JSON output
        cmd = [SPEEDTEST_CLI, "--json"]
        kwargs = dict(
            args=cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Prevent console window from appearing in the no-console .exe
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run(**kwargs)

        if result.returncode != 0:
            raise RuntimeError(f"speedtest-cli failed: {result.stderr.strip()}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse speedtest-cli JSON: {e}")

        # speedtest-cli JSON fields: 'download' in bits/s, 'ping' in ms
        down_bps = data.get("download")
        ping_ms = data.get("ping")

        if down_bps is None or ping_ms is None:
            raise RuntimeError("speedtest-cli JSON missing 'download' or 'ping'")

        down_mbps = down_bps / 1_000_000.0
        return float(ping_ms), float(down_mbps)



    def _worker_loop(self, stop_event: threading.Event):
        self.last_full_test_ts = None


        while not stop_event.is_set():
            ts = datetime.now()
            now = time.time()

            do_full_test = (
                self.last_full_test_ts is None
                or (now - self.last_full_test_ts) >= FULL_TEST_INTERVAL_SECONDS
            )

            try:
                if do_full_test:
                    ping_ms, down_mbps = self._run_full_test()
                    method = "full"
                    self.last_full_test_ts = time.time()
                else:
                    ping_ms = measure_ping_ms(PING_HOST)
                    down_mbps = measure_download_mbps(TEST_URL)
                    method = "light"

                self.data.append((ts, ping_ms, down_mbps, method))

                self._set_last_result_title(ts, ping_ms, down_mbps, method)

            except Exception:
                if do_full_test:
                    self.speedtest_client = None

            for _ in range(int(TEST_INTERVAL_SECONDS * 10)):
                if stop_event.is_set():
                    break
                time.sleep(0.1)

    def _set_last_result_title(self, ts, ping_ms, down_mbps, method: str):
        method_label = "FULL" if method == "full" else "light"
        ping_txt = "n/a" if ping_ms is None else f"{ping_ms:.1f} ms"
        down_txt = "n/a" if down_mbps is None else f"{down_mbps:.2f} Mbps"
        txt = f"{method_label} @ {ts.strftime('%H:%M:%S')} | Ping: {ping_txt} | Down: {down_txt}"
        self.root.title(txt)

    # ---------- Plot & SPC ----------

    def _schedule_plot_update(self):
        self._update_plot()
        self.root.after(2000, self._schedule_plot_update)

    def _update_plot(self):
        if not self.data:
            self.canvas.draw_idle()
            return

        ping_light = [p for (_, p, _, m) in self.data if m == "light" and p is not None]
        full_down = [d for (_, _, d, m) in self.data if m == "full" and d is not None]

        # Ping chart
        if ping_light:
            x_ping = list(range(1, len(ping_light) + 1))
            self.ping_line.set_data(x_ping, ping_light)

            colors = [color_for_ping(p) for p in ping_light]
            self.ping_scatter.remove()
            self.ping_scatter = self.ax_ping.scatter(
                x_ping, ping_light, c=colors, s=30, zorder=3
            )

            self.ax_ping.set_xlim(0.5, len(x_ping) + 0.5)

            mean, ucl, lcl = compute_ichart_limits(ping_light)
            if mean is not None:
                self.ping_mean_line.set_visible(True)
                self.ping_ucl_line.set_visible(True)
                self.ping_lcl_line.set_visible(True)

                self.ping_mean_line.set_ydata([mean, mean])
                self.ping_ucl_line.set_ydata([ucl, ucl])
                self.ping_lcl_line.set_ydata([lcl, lcl])

                ymax = max(max(ping_light), ucl)
                ymin = min(min(ping_light), lcl)
            else:
                self.ping_mean_line.set_visible(False)
                self.ping_ucl_line.set_visible(False)
                self.ping_lcl_line.set_visible(False)
                ymax = max(ping_light)
                ymin = min(ping_light)

            if ymax <= 0:
                ymax = 1
            self.ax_ping.set_ylim(max(0, ymin * 0.8), ymax * 1.2)
        else:
            self.ping_line.set_data([], [])
            self.ping_scatter.remove()
            self.ping_scatter = self.ax_ping.scatter([], [])

        # Full-test chart
        if full_down:
            x_full = list(range(1, len(full_down) + 1))
            self.full_line.set_data(x_full, full_down)

            colors = [color_for_download(d) for d in full_down]
            self.full_scatter.remove()
            self.full_scatter = self.ax_full.scatter(
                x_full, full_down, c=colors, s=30, zorder=3
            )

            self.ax_full.set_xlim(0.5, len(x_full) + 0.5)

            mean, ucl, lcl = compute_ichart_limits(full_down)
            if mean is not None:
                self.full_mean_line.set_visible(True)
                self.full_ucl_line.set_visible(True)
                self.full_lcl_line.set_visible(True)

                self.full_mean_line.set_ydata([mean, mean])
                self.full_ucl_line.set_ydata([ucl, ucl])
                self.full_lcl_line.set_ydata([lcl, lcl])

                ymax = max(max(full_down), ucl)
                ymin = min(min(full_down), lcl)
            else:
                self.full_mean_line.set_visible(False)
                self.full_ucl_line.set_visible(False)
                self.full_lcl_line.set_visible(False)
                ymax = max(full_down)
                ymin = min(full_down)

            if ymax <= 0:
                ymax = 1
            self.ax_full.set_ylim(max(0, ymin * 0.8), ymax * 1.2)
        else:
            self.full_line.set_data([], [])
            self.full_scatter.remove()
            self.full_scatter = self.ax_full.scatter([], [])
            self.full_mean_line.set_visible(False)
            self.full_ucl_line.set_visible(False)
            self.full_lcl_line.set_visible(False)

        self.canvas.draw_idle()

    # ---------- Fullscreen & shutdown ----------

    def set_fullscreen(self, value: bool):
        """
        Emulate fullscreen without using the -fullscreen attribute,
        and expand to the monitor the window is currently on.
        """
        if value and not self.is_fullscreen:
            self.is_fullscreen = True
            self.root.update_idletasks()

            # Save current geometry so we can restore
            self.saved_geometry = self.root.geometry()

            # Get bounds of the monitor this window is on
            mw, mh, mx, my = get_current_monitor_geometry(self.root)
            self.root.geometry(f"{mw}x{mh}+{mx}+{my}")

            # Bring to front
            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)

        elif not value and self.is_fullscreen:
            self.is_fullscreen = False
            self.root.update_idletasks()

            if self.saved_geometry:
                self.root.geometry(self.saved_geometry)
            else:
                # Sensible default windowed size in the center of that same monitor
                mw, mh, mx, my = get_current_monitor_geometry(self.root)
                w = min(1200, mw - 100)
                h = min(800, mh - 100)
                x = mx + (mw - w) // 2
                y = my + (mh - h) // 2
                self.root.geometry(f"{w}x{h}+{x}+{y}")

            # Bring back to front
            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)


    def toggle_fullscreen(self):
        self.set_fullscreen(not self.is_fullscreen)

    def on_close(self):
        self.stop_event.set()
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        self.root.destroy()


def main():
    root = tk.Tk()
    # Frameless & translucent
    root.overrideredirect(True)
    root.attributes("-alpha", 0.9)

    app = SpeedMonitorApp(root)
    # Start in "fullscreen" (emulated)
    app.set_fullscreen(True)

    root.mainloop()


if __name__ == "__main__":
    main()
