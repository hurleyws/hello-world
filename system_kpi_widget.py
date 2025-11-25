#!/usr/bin/env python3
"""
Synthwave System Dashboard Widget

- Top row: 4 donut-style gauges
    * CPU usage (%)
    * Memory usage (%)
    * Disk usage (%)
    * Battery level (% or N/A)
- Bottom: CPU per-core heatmap over time

Features:
- Frameless, translucent window
- Draggable
- Resizable from bottom-right
- Right-click context menu: Toggle Fullscreen / Close
"""

import threading
import time
from datetime import datetime
from collections import deque
import ctypes
from ctypes import wintypes

import psutil
import numpy as np
import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.patches as patches

# ===== CONFIGURATION =====

SAMPLE_INTERVAL_SECONDS = 2      # Time between samples
MAX_POINTS = 300                 # Max samples to keep for history

# Vaporwave colors (aligned with your other widgets)
BG = "#1b1035"           # main background
PLOT_BG = "#241445"
FG = "#f8f0ff"           # text
ACCENT_TITLE = "#b967ff"      # purple
GRID_COLOR = "#3a2b5b"

GAUGE_GOOD_COLOR = "#05ffa1"   # neon green
GAUGE_WARN_COLOR = "#fffb96"   # soft yellow
GAUGE_BAD_COLOR = "#ff71ce"    # neon pink
GAUGE_BG_COLOR = "#3a2b5b"

HEATMAP_CMAP = "magma"

ALPHA = 0.9

# Thresholds for gauge color-coding
GOOD_CPU = 50.0
WARN_CPU = 80.0

GOOD_MEM = 60.0
WARN_MEM = 80.0

GOOD_DISK = 70.0
WARN_DISK = 90.0

GOOD_BATT = 40.0     # low-ish is fine if plugged in; we just color it
WARN_BATT = 20.0

# Resizing behavior
RESIZE_MARGIN = 24
MIN_WIDTH = 700
MIN_HEIGHT = 450


# ===== HELPERS =====

def gauge_color(value, good, warn):
    """Pick gauge color given value and thresholds."""
    if value is None:
        return "#777777"  # neutral grey for N/A
    if value <= good:
        return GAUGE_GOOD_COLOR
    elif value <= warn:
        return GAUGE_WARN_COLOR
    else:
        return GAUGE_BAD_COLOR


def draw_donut_gauge(ax, value, label, good_thr, warn_thr,
                     vmin=0.0, vmax=100.0):
    """
    Draw a donut-style gauge on the given axis.
    value: 0-100 (or None)
    """
    ax.clear()
    ax.set_facecolor(PLOT_BG)
    ax.set_aspect("equal")
    ax.axis("off")

    # Clamp and handle None
    if value is None:
        display_val = "N/A"
        frac = 0.0
        color = gauge_color(None, good_thr, warn_thr)
    else:
        v = max(vmin, min(vmax, float(value)))
        frac = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.0
        display_val = f"{v:.0f}%"
        color = gauge_color(v, good_thr, warn_thr)

    # Background ring
    bg_wedge = patches.Wedge(
        center=(0, 0),
        r=1.0,
        theta1=0,
        theta2=360,
        width=0.3,
        facecolor="none",
        edgecolor=GAUGE_BG_COLOR,
        linewidth=4,
        alpha=0.7,
    )
    ax.add_patch(bg_wedge)

    # Value arc – from 90° (top) clockwise frac*360
    theta1 = 90
    theta2 = 90 - 360 * frac
    val_wedge = patches.Wedge(
        center=(0, 0),
        r=1.0,
        theta1=theta1,
        theta2=theta2,
        width=0.3,
        facecolor=color,
        edgecolor=color,
        linewidth=4,
        alpha=0.9,
    )
    ax.add_patch(val_wedge)

    # Value text
    ax.text(
        0,
        0.1,
        display_val,
        ha="center",
        va="center",
        color=FG,
        fontsize=13,
        fontweight="bold",
    )

    # Label text
    ax.text(
        0,
        -0.75,
        label,
        ha="center",
        va="center",
        color=ACCENT_TITLE,
        fontsize=9,
        fontweight="bold",
    )

    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)


def get_current_monitor_geometry(root):
    """
    Return (width, height, left, top) for the monitor that currently
    contains the center of the Tk window.
    Windows-only; safe fallback if something goes wrong.
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

        root.update_idletasks()
        win_x = root.winfo_x()
        win_y = root.winfo_y()
        win_w = root.winfo_width()
        win_h = root.winfo_height()

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
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        return sw, sh, 0, 0


# ===== MAIN APP =====

class SystemDashboardWidget:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg=BG)

        # Data
        self.data_lock = threading.Lock()
        self.timestamps = deque(maxlen=MAX_POINTS)
        self.cpu_vals = deque(maxlen=MAX_POINTS)
        self.mem_vals = deque(maxlen=MAX_POINTS)
        self.disk_vals = deque(maxlen=MAX_POINTS)
        self.batt_vals = deque(maxlen=MAX_POINTS)   # may be None
        self.per_core_history = deque(maxlen=MAX_POINTS)  # list of [per-core]

        # Determine number of cores for heatmap layout
        self.num_cores = psutil.cpu_count(logical=True) or 4

        # Thread control
        self.stop_event = threading.Event()
        self.worker_thread = None

        # Drag/resize state
        self.is_fullscreen = False
        self.saved_geometry = None
        self._drag_mode = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._orig_x = 0
        self._orig_y = 0
        self._orig_w = 0
        self._orig_h = 0

        # Build UI
        self._build_ui()
        self._build_context_menu()

        # Drag/resize behavior
        self._make_drag_resize(self.root)
        self._make_drag_resize(self.canvas.get_tk_widget())

        # Events
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda e: self.on_close())

        # Start worker + plotting
        self._start_worker()
        self._schedule_plot_update()

    # ----- UI -----

    def _build_ui(self):
        # Top bar: title + summary
        top_frame = tk.Frame(self.root, bg=BG)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))

        self.title_label = tk.Label(
            top_frame,
            text=" SYSTEM DASHBOARD ",
            bg=BG,
            fg=ACCENT_TITLE,
            font=("Consolas", 12, "bold"),
        )
        self.title_label.pack(side=tk.LEFT, anchor="w")

        self.summary_label = tk.Label(
            top_frame,
            text="",
            bg=BG,
            fg=FG,
            font=("Consolas", 10),
            anchor="e",
            justify="right",
        )
        self.summary_label.pack(side=tk.RIGHT, anchor="e")

        # Figure layout: 4 gauges on top row, heatmap spanning bottom row
        fig = Figure(figsize=(8, 5), dpi=100)
        fig.patch.set_facecolor(BG)
        gs = fig.add_gridspec(2, 4, height_ratios=[1, 2])

        # Gauges
        self.ax_cpu = fig.add_subplot(gs[0, 0])
        self.ax_mem = fig.add_subplot(gs[0, 1])
        self.ax_disk = fig.add_subplot(gs[0, 2])
        self.ax_batt = fig.add_subplot(gs[0, 3])

        for ax in [self.ax_cpu, self.ax_mem, self.ax_disk, self.ax_batt]:
            ax.set_facecolor(PLOT_BG)
            ax.axis("off")

        # Heatmap
        self.ax_heatmap = fig.add_subplot(gs[1, :])
        self.ax_heatmap.set_facecolor(PLOT_BG)
        self.ax_heatmap.set_title("CPU Usage per Core (Recent History)", color=ACCENT_TITLE, fontsize=10)
        self.ax_heatmap.tick_params(colors=FG, labelcolor=FG)
        for spine in self.ax_heatmap.spines.values():
            spine.set_color(FG)

        # Initialize heatmap with dummy data
        initial_data = np.zeros((self.num_cores, 1))
        self.heatmap_im = self.ax_heatmap.imshow(
            initial_data,
            aspect="auto",
            vmin=0,
            vmax=100,
            cmap=HEATMAP_CMAP,
            origin="lower",
        )
        self.ax_heatmap.set_yticks(range(self.num_cores))
        self.ax_heatmap.set_yticklabels([f"C{i}" for i in range(self.num_cores)], fontsize=8, color=FG)
        self.ax_heatmap.set_xticks([])
        self.ax_heatmap.set_xlabel("Time →", color=FG, fontsize=9)

        self.canvas = FigureCanvasTkAgg(fig, master=self.root)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 6))

    def _build_context_menu(self):
        self.context_menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=BG,
            fg=FG,
            activebackground=PLOT_BG,
            activeforeground=FG,
        )
        self.context_menu.add_command(label="Toggle Fullscreen", command=self.toggle_fullscreen)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Close", command=self.on_close)

        def show_menu(event):
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

        self.root.bind("<Button-3>", show_menu)
        self.canvas.get_tk_widget().bind("<Button-3>", show_menu)

    # ----- DRAG / RESIZE -----

    def _make_drag_resize(self, widget):
        widget.bind("<ButtonPress-1>", self._on_mouse_down)
        widget.bind("<B1-Motion>", self._on_mouse_drag)

    def _on_mouse_down(self, event):
        if self.is_fullscreen:
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

    # ----- WORKER / METRICS -----

    def _start_worker(self):
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            args=(self.stop_event,),
            daemon=True,
        )
        self.worker_thread.start()

    def _worker_loop(self, stop_event: threading.Event):
        # Warm-up call so psutil has a baseline
        psutil.cpu_percent(interval=None, percpu=True)

        while not stop_event.is_set():
            ts = datetime.now()

            # CPU per core & overall
            per_core = psutil.cpu_percent(interval=None, percpu=True)
            cpu_total = float(sum(per_core) / len(per_core)) if per_core else 0.0

            mem = psutil.virtual_memory().percent
            try:
                disk = psutil.disk_usage("/").percent
            except Exception:
                disk = 0.0

            batt_pct = None
            batt_status = "N/A"
            try:
                batt = psutil.sensors_battery()
                if batt is not None:
                    batt_pct = float(batt.percent)
                    batt_status = "AC" if batt.power_plugged else "BAT"
            except Exception:
                batt = None

            with self.data_lock:
                self.timestamps.append(ts)
                self.cpu_vals.append(cpu_total)
                self.mem_vals.append(mem)
                self.disk_vals.append(disk)
                self.batt_vals.append(batt_pct)
                # Per-core history
                # Ensure list length matches num_cores
                if per_core and len(per_core) == self.num_cores:
                    self.per_core_history.append(list(per_core))
                elif per_core:
                    # Adjust if core count changed (rare)
                    per_core = per_core[: self.num_cores]
                    self.per_core_history.append(list(per_core))

            # Update summary text
            summary = (
                f"{ts.strftime('%H:%M:%S')} | "
                f"CPU {cpu_total:.1f}% | Mem {mem:.1f}% | Disk {disk:.1f}% | "
                f"Batt {batt_pct:.0f}% ({batt_status})" if batt_pct is not None else
                f"{ts.strftime('%H:%M:%S')} | "
                f"CPU {cpu_total:.1f}% | Mem {mem:.1f}% | Disk {disk:.1f}% | Batt N/A"
            )
            self.root.after(0, self._update_summary, summary)

            # Sleep in small chunks to respond quickly to close
            for _ in range(int(SAMPLE_INTERVAL_SECONDS * 10)):
                if stop_event.is_set():
                    break
                time.sleep(0.1)

    def _update_summary(self, text: str):
        self.summary_label.config(text=text)
        self.root.title(text)

    # ----- PLOTTING -----

    def _schedule_plot_update(self):
        self._update_plot()
        self.root.after(2000, self._schedule_plot_update)

    def _update_plot(self):
        with self.data_lock:
            cpu_vals = list(self.cpu_vals)
            mem_vals = list(self.mem_vals)
            disk_vals = list(self.disk_vals)
            batt_vals = list(self.batt_vals)
            per_core_history = list(self.per_core_history)

        # Current values for gauges
        cpu_current = cpu_vals[-1] if cpu_vals else 0.0
        mem_current = mem_vals[-1] if mem_vals else 0.0
        disk_current = disk_vals[-1] if disk_vals else 0.0
        batt_current = batt_vals[-1] if batt_vals else None

        # Draw gauges
        draw_donut_gauge(self.ax_cpu, cpu_current, "CPU", GOOD_CPU, WARN_CPU)
        draw_donut_gauge(self.ax_mem, mem_current, "MEM", GOOD_MEM, WARN_MEM)
        draw_donut_gauge(self.ax_disk, disk_current, "DISK", GOOD_DISK, WARN_DISK)
        draw_donut_gauge(self.ax_batt, batt_current, "BATT", GOOD_BATT, WARN_BATT)

        # Heatmap
        if per_core_history:
            arr = np.array(per_core_history).T  # shape: (num_cores, time)
            self.heatmap_im.set_data(arr)
            # X-axis: show only "Start" and "Now" to avoid clutter
            t_len = arr.shape[1]
            self.ax_heatmap.set_xlim(-0.5, t_len - 0.5)
            self.ax_heatmap.set_xticks([0, max(0, t_len - 1)])
            self.ax_heatmap.set_xticklabels(["Start", "Now"], fontsize=8, color=FG)
        else:
            # No data yet
            self.heatmap_im.set_data(np.zeros((self.num_cores, 1)))
            self.ax_heatmap.set_xticks([])
            self.ax_heatmap.set_xticklabels([])

        self.canvas.draw_idle()

    # ----- FULLSCREEN & SHUTDOWN -----

    def set_fullscreen(self, value: bool):
        if value and not self.is_fullscreen:
            self.is_fullscreen = True
            self.root.update_idletasks()
            self.saved_geometry = self.root.geometry()

            mw, mh, mx, my = get_current_monitor_geometry(self.root)
            self.root.geometry(f"{mw}x{mh}+{mx}+{my}")

            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)

        elif not value and self.is_fullscreen:
            self.is_fullscreen = False
            self.root.update_idletasks()

            if self.saved_geometry:
                self.root.geometry(self.saved_geometry)
            else:
                mw, mh, mx, my = get_current_monitor_geometry(self.root)
                w = min(1200, mw - 100)
                h = min(800, mh - 100)
                x = mx + (mw - w) // 2
                y = my + (mh - h) // 2
                self.root.geometry(f"{w}x{h}+{x}+{y}")

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
    root.overrideredirect(True)
    root.attributes("-alpha", ALPHA)

    # Start in a nice centered window instead of fullscreen
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = 950
    h = 550
    x = (sw - w) // 2
    y = 80
    root.geometry(f"{w}x{h}+{x}+{y}")

    app = SystemDashboardWidget(root)
    root.mainloop()


if __name__ == "__main__":
    main()
