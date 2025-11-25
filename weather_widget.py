#!/usr/bin/env python3
"""
Synthwave Weather Widget (Open-Meteo version, no API key needed)

- Hourly temps in Fahrenheit for waking hours (7 AM – 10 PM)
- Line plot of temperature
- If any hour has precipitation probability > 0:
    - Show a bar chart of precip probability (%)
- Simple weather symbols (☀, ☁, 🌧, 🌫, ❄, etc.) on the temp plot
- Shows "current" hour's:
    - Temp, condition
    - Wind speed
    - Humidity
    - Allergens placeholder (N/A for now)
- Frameless, translucent, draggable, resizable
- Right-click menu: Refresh now / Toggle Fullscreen / Close
"""

import threading
import time
from datetime import datetime, timedelta
from collections import namedtuple

import requests
import tkinter as tk
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ========= CONFIG =========

# Location (Fort Worth by default)
LAT = 32.7555
LON = -97.3308

# Refresh interval (seconds)
REFRESH_INTERVAL_SEC = 15 * 60  # 15 minutes

# Waking hours (local time)
WAKE_START_HOUR = 7   # 7 AM
WAKE_END_HOUR = 22    # 10 PM

# Vaporwave aesthetic
BG = "#1b1035"
PLOT_BG = "#241445"
FG = "#f8f0ff"
ACCENT_TITLE = "#f8f0ff"
TEMP_LINE_COLOR = "#ff9ad6"      # soft pink
TEMP_POINT_COLOR = "#fffb96"     # soft yellow
PRECIP_BAR_COLOR = "#01cdfe"     # bright cyan
GRID_COLOR = "#3a2b5b"

ALPHA = 0.9

RESIZE_MARGIN = 18
MIN_WIDTH = 600
MIN_HEIGHT = 350

HourlyPoint = namedtuple(
    "HourlyPoint",
    ["local_dt", "hour_label", "temp_f", "pop", "wind_mph", "humidity", "weather_main", "weather_desc"]
)

# Map Open-Meteo WMO weather codes to simple categories and descriptions
WMO_CODE_MAP = {
    0: ("Clear", "Clear sky"),
    1: ("Clear", "Mainly clear"),
    2: ("Clouds", "Partly cloudy"),
    3: ("Clouds", "Overcast"),
    45: ("Fog", "Fog"),
    48: ("Fog", "Depositing rime fog"),
    51: ("Drizzle", "Light drizzle"),
    53: ("Drizzle", "Moderate drizzle"),
    55: ("Drizzle", "Dense drizzle"),
    56: ("Drizzle", "Freezing drizzle, light"),
    57: ("Drizzle", "Freezing drizzle, dense"),
    61: ("Rain", "Slight rain"),
    63: ("Rain", "Moderate rain"),
    65: ("Rain", "Heavy rain"),
    66: ("Rain", "Freezing rain, light"),
    67: ("Rain", "Freezing rain, heavy"),
    71: ("Snow", "Slight snow"),
    73: ("Snow", "Moderate snow"),
    75: ("Snow", "Heavy snow"),
    77: ("Snow", "Snow grains"),
    80: ("Rain", "Rain showers, slight"),
    81: ("Rain", "Rain showers, moderate"),
    82: ("Rain", "Rain showers, violent"),
    85: ("Snow", "Snow showers, slight"),
    86: ("Snow", "Snow showers, heavy"),
    95: ("Thunderstorm", "Thunderstorm"),
    96: ("Thunderstorm", "Thunderstorm with slight hail"),
    99: ("Thunderstorm", "Thunderstorm with heavy hail"),
}

WEATHER_SYMBOLS = {
    "Thunderstorm": "⛈",
    "Drizzle": "☂",   # changed from 🌦
    "Rain": "🌧",
    "Snow": "❄",
    "Clear": "☀",
    "Clouds": "☁",
    "Fog": "🌫",
}



# ========== DATA FETCHING ==========

def weather_from_code(code: int):
    """Translate WMO code into (main, desc)."""
    main, desc = WMO_CODE_MAP.get(code, ("Clouds", "Unknown"))
    return main, desc


def fetch_hourly_weather():
    """
    Fetch hourly weather from Open-Meteo.

    Endpoint: https://api.open-meteo.com/v1/forecast
    Params: temperature_2m, precipitation_probability, relativehumidity_2m,
            windspeed_10m, weathercode, timezone=auto
    Returns: (None, list_of_HourlyPoint)  [timezone handled server-side]
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=temperature_2m,precipitation_probability,relativehumidity_2m,"
        "windspeed_10m,weathercode"
        "&timezone=auto"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps_c = hourly.get("temperature_2m", [])
    pops = hourly.get("precipitation_probability", [])
    hums = hourly.get("relativehumidity_2m", [])
    winds_kmh = hourly.get("windspeed_10m", [])
    codes = hourly.get("weathercode", [])

    now = datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)

    points = []
    for t, tc, pop, hum, wind_kmh, code in zip(
        times, temps_c, pops, hums, winds_kmh, codes
    ):
        # Parse local datetime from ISO string (e.g., "2025-11-23T15:00")
        local_dt = datetime.fromisoformat(t)
        hour = local_dt.hour
        local_date = local_dt.date()

        # Keep only:
        # - remaining hours today (>= now)
        # - any hour tomorrow
        if local_date == today:
            if local_dt < now:
                continue  # earlier today, already in the past
        elif local_date == tomorrow:
            pass  # keep
        else:
            continue  # drop anything beyond tomorrow

        # Still enforce waking hours
        if not (WAKE_START_HOUR <= hour <= WAKE_END_HOUR):
            continue


        # Convert °C → °F (Open-Meteo defaults to °C)
        temp_f = tc * 9 / 5 + 32

        # Some fields may be None; make them sensible defaults
        pop = pop if pop is not None else 0.0
        hum = hum if hum is not None else 0
        wind_kmh = wind_kmh if wind_kmh is not None else 0.0

        # km/h → mph
        wind_mph = wind_kmh * 0.621371

        main, desc = weather_from_code(code)

        # Hour label like "3 PM"
        hour_label = local_dt.strftime("%I %p").lstrip("0")


        points.append(
            HourlyPoint(
                local_dt=local_dt,
                hour_label=hour_label,
                temp_f=temp_f,
                pop=float(pop),
                wind_mph=float(wind_mph),
                humidity=int(hum),
                weather_main=main,
                weather_desc=desc,
            )
        )

    return None, points


def pick_current_point(points):
    """
    Choose the best "current" point:
    - First one whose local_dt >= now, or
    - If all in the past, the last one.
    """
    if not points:
        return None
    now = datetime.now()
    future_or_now = [p for p in points if p.local_dt >= now]
    if future_or_now:
        return future_or_now[0]
    return points[-1]


# ========== UI APP ==========

class WeatherWidgetApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.configure(bg=BG)

        self.stop_event = threading.Event()
        self.data_lock = threading.Lock()

        self.points = []
        self.current_point = None

        self.is_fullscreen = False
        self.saved_geometry = None
        self._drag_mode = None
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._orig_x = 0
        self._orig_y = 0
        self._orig_w = 0
        self._orig_h = 0

        self._build_ui()
        self._build_context_menu()

        self._make_drag_resize(self.root)
        self._make_drag_resize(self.canvas.get_tk_widget())

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda e: self.on_close())

        # Start data thread + periodic UI updates
        self._start_worker()
        self._schedule_plot_update()
        self._schedule_refresh()

        # Initial title
        self.root.title("Weather: loading...")

    # ----- UI BUILD -----

    def _build_ui(self):
        top_frame = tk.Frame(self.root, bg=BG)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))

        self.title_label = tk.Label(
            top_frame,
            text=" WEATHER ",
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

        # Matplotlib figure
        fig = Figure(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor(BG)
        fig.subplots_adjust(top=0.88, hspace=0.9)  # <-- more separation

        self.ax_temp = fig.add_subplot(211)
        self.ax_precip = fig.add_subplot(212)

        def style_ax(ax, title, ylabel):
            ax.set_title(title, color=ACCENT_TITLE, fontsize=10)
            ax.set_facecolor(PLOT_BG)
            ax.grid(True, linestyle="--", alpha=0.4, color=GRID_COLOR)
            ax.tick_params(colors=FG, labelcolor=FG)
            ax.yaxis.label.set_color(FG)
            for spine in ax.spines.values():
                spine.set_color(FG)
            ax.set_ylabel(ylabel, color=FG)

        style_ax(self.ax_temp, "Temperature (°F)", "Temp (°F)")
        style_ax(self.ax_precip, "Precipitation Chance (%)", "PoP (%)")

        self.temp_line, = self.ax_temp.plot([], [], "-", color=TEMP_LINE_COLOR, alpha=0.7)
        self.temp_scatter = self.ax_temp.scatter([], [], c=TEMP_POINT_COLOR, s=30)

        self.precip_bars = None

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
        self.context_menu.add_command(label="Refresh now", command=self.refresh_now)
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

    # ----- DATA THREAD -----

    def _start_worker(self):
        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
        )
        self.worker_thread.start()

    def _worker_loop(self):
        while not self.stop_event.is_set():
            try:
                _, points = fetch_hourly_weather()
                current = pick_current_point(points)

                with self.data_lock:
                    self.points = points
                    self.current_point = current

                if current:
                    summary = (
                        f"{current.local_dt.strftime('%a %I:%M %p')} | "
                        f"{current.temp_f:.0f}°F {current.weather_main or ''} | "
                        f"Wind {current.wind_mph:.0f} mph | "
                        f"Humidity {current.humidity}% | "
                        f"Allergens: N/A"
                    )
                else:
                    summary = "No data"

                self.root.after(0, self._update_summary_label, summary)
            except Exception as e:
                self.root.after(0, self._update_summary_label, f"Error: {e}")

            # Sleep until the next refresh
            for _ in range(REFRESH_INTERVAL_SEC * 10):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)

    def _update_summary_label(self, text: str):
        self.summary_label.config(text=text)

    # ----- PLOT UPDATES -----

    def _schedule_plot_update(self):
        self._update_plot()
        self.root.after(5000, self._schedule_plot_update)

    def _update_plot(self):
        with self.data_lock:
            points = list(self.points)

        if not points:
            self.temp_line.set_data([], [])
            self.temp_scatter.remove()
            self.temp_scatter = self.ax_temp.scatter([], [], c=TEMP_POINT_COLOR, s=30)
            if self.precip_bars is not None:
                for bar in self.precip_bars:
                    bar.remove()
                self.precip_bars = None
            self.canvas.draw_idle()
            return

        x = list(range(len(points)))
        temps = [p.temp_f for p in points]
        hour_labels = [p.hour_label for p in points]
        pops = [p.pop for p in points]  # already 0–100
        weather_main = [p.weather_main for p in points]

        # Temperature line + points
        self.temp_line.set_data(x, temps)

        self.temp_scatter.remove()
        self.temp_scatter = self.ax_temp.scatter(x, temps, c=TEMP_POINT_COLOR, s=30, zorder=3)

        # Clear any previous text annotations (older Matplotlib: remove each text artist)
        for txt in list(self.ax_temp.texts):
            txt.remove()

        # Add weather symbols near each point
        for xi, yi, wm in zip(x, temps, weather_main):
            symbol = WEATHER_SYMBOLS.get(wm, "")
            if symbol:
                self.ax_temp.text(
                    xi,
                    yi + 1.5,
                    symbol,
                    color=FG,
                    fontsize=10,
                    ha="center",
                    va="bottom",
                )

        # Axes formatting
        self.ax_temp.set_xlim(-0.5, len(x) - 0.5)
        if temps:
            ymin = min(temps)
            ymax = max(temps)
            padding = max(2, (ymax - ymin) * 0.2)
            self.ax_temp.set_ylim(ymin - padding, ymax + padding)

        self.ax_temp.set_xticks(x)
        self.ax_temp.set_xticklabels(hour_labels, rotation=0, fontsize=8, color=FG)
        for label in self.ax_temp.get_xticklabels():
            label.set_rotation(45)
            label.set_ha("right")

        # Precipitation bars (only if any > 0)
        if any(pop > 0 for pop in pops):
            if self.precip_bars is not None:
                for bar in self.precip_bars:
                    bar.remove()
            self.precip_bars = self.ax_precip.bar(
                x, pops, color=PRECIP_BAR_COLOR, alpha=0.8
            )
            self.ax_precip.set_xlim(-0.5, len(x) - 0.5)
            self.ax_precip.set_ylim(0, max(100, max(pops) * 1.1))
            self.ax_precip.set_xticks(x)
            self.ax_precip.set_xticklabels(hour_labels, rotation=0, fontsize=8, color=FG)
            for label in self.ax_precip.get_xticklabels():
                label.set_rotation(45)
                label.set_ha("right")
            self.ax_precip.yaxis.set_label_text("PoP (%)", color=FG)
            self.ax_precip.set_title("Precipitation Chance (%)", color=ACCENT_TITLE, fontsize=10)
        else:
            # No precip expected: clear bars and show a gentle message
            if self.precip_bars is not None:
                for bar in self.precip_bars:
                    bar.remove()
                self.precip_bars = None
            self.ax_precip.clear()
            self.ax_precip.set_facecolor(PLOT_BG)
            self.ax_precip.grid(True, linestyle="--", alpha=0.4, color=GRID_COLOR)
            self.ax_precip.tick_params(colors=FG, labelcolor=FG)
            for spine in self.ax_precip.spines.values():
                spine.set_color(FG)
            self.ax_precip.set_xticks([])
            self.ax_precip.set_yticks([])
            self.ax_precip.set_title("No precipitation expected", color=ACCENT_TITLE, fontsize=10)

        self.canvas.draw_idle()


    # ----- REFRESH CONTROL -----

    def _schedule_refresh(self):
        if not self.stop_event.is_set():
            self.refresh_now()
            self.root.after(REFRESH_INTERVAL_SEC * 1000, self._schedule_refresh)

    def refresh_now(self):
        threading.Thread(target=self._worker_once, daemon=True).start()

    def _worker_once(self):
        try:
            _, points = fetch_hourly_weather()
            current = pick_current_point(points)
            with self.data_lock:
                self.points = points
                self.current_point = current

            if current:
                summary = (
                    f"{current.local_dt.strftime('%a %I:%M %p')} | "
                    f"{current.temp_f:.0f}°F {current.weather_main or ''} | "
                    f"Wind {current.wind_mph:.0f} mph | "
                    f"Humidity {current.humidity}% | "
                    f"Allergens: N/A"
                )
            else:
                summary = "No data"

            self.root.after(0, self._update_summary_label, summary)
        except Exception as e:
            self.root.after(0, self._update_summary_label, f"Error: {e}")

    # ----- FULLSCREEN & SHUTDOWN -----

    def toggle_fullscreen(self):
        self.set_fullscreen(not self.is_fullscreen)

    def set_fullscreen(self, value: bool):
        if value and not self.is_fullscreen:
            self.is_fullscreen = True
            self.root.update_idletasks()
            self.saved_geometry = self.root.geometry()

            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{sw}x{sh}+0+0")

            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)
        elif not value and self.is_fullscreen:
            self.is_fullscreen = False
            self.root.update_idletasks()
            if self.saved_geometry:
                self.root.geometry(self.saved_geometry)
            else:
                w = 800
                h = 400
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                x = (sw - w) // 2
                y = (sh - h) // 2
                self.root.geometry(f"{w}x{h}+{x}+{y}")

            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-alpha", ALPHA)

    # Start centered near bottom
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w = 800
    h = 400
    x = (sw - w) // 2
    y = sh - h - 80
    root.geometry(f"{w}x{h}+{x}+{y}")

    app = WeatherWidgetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
