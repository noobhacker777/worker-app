import tkinter as tk
import ctypes
import subprocess
from tkinter import messagebox, ttk
import requests
import hashlib
import tempfile
import time
from io import BytesIO
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageTk

try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

SCREENSHOT_AVAILABLE = True
try:
    import mss
    import mss.tools
except ImportError:
    mss = None
import threading
import os
import json
import re
import sys
import traceback
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from dotenv import load_dotenv


def local_now():
    """Return current local datetime"""
    return datetime.now()


def _capture_screenshot():
    """Capture screenshot cross-platform (Windows/macOS/Linux)."""
    if ImageGrab is not None and sys.platform.startswith("win"):
        try:
            return ImageGrab.grab()
        except Exception:
            pass

    if mss is not None:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                sct_img = sct.grab(monitor)
                return Image.frombytes("RGBA", sct_img.size, sct_img.rgba)
        except Exception:
            pass

    print("[Screenshot] Capture not available on this platform")
    return None


try:
    from ctypes import wintypes
except ImportError:  # pragma: no cover - non-Windows fallback
    from types import SimpleNamespace

    wintypes = SimpleNamespace(DWORD=int)

try:
    import pystray
    from PIL import Image as PILImage

    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

load_dotenv()

DEFAULT_ADMIN_API_URL = "https://tracker.hkbarughrpgahrg.dpdns.org"


def _get_cross_platform_app_data_dir():
    """Return a per-user application data directory on Windows, macOS, or Linux."""
    if sys.platform.startswith("win"):
        base_dir = Path(
            os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
    else:
        base_dir = Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config")))

    return base_dir / "workerapp"


def _show_fatal_error(exc_type, exc_value, exc_tb):
    """Persist startup/runtime crashes so packaged builds surface the real error."""
    try:
        crash_dir = _get_cross_platform_app_data_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_log = crash_dir / "crash.log"
        crash_log.write_text(
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            encoding="utf-8",
        )
    except Exception:
        pass

    try:
        messagebox.showerror(
            "Worker Activity Tracker crashed",
            f"{exc_type.__name__}: {exc_value}\n\nA crash log was written to AppData.",
        )
    except Exception:
        pass


sys.excepthook = _show_fatal_error


class WorkerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Worker Activity Tracker")
        self.root.geometry("900x680")
        self.root.resizable(True, True)
        self.is_windows = sys.platform.startswith("win")
        self.is_macos = sys.platform == "darwin"

        self.app_data_dir = _get_cross_platform_app_data_dir()
        self.credentials_path = self.app_data_dir / "credentials.json"
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.saved_credentials = self.load_saved_credentials()

        # Configuration
        self.API_URL = (os.getenv("ADMIN_API_URL") or DEFAULT_ADMIN_API_URL).rstrip("/")
        self.screenshot_interval = int(os.getenv("SCREENSHOT_INTERVAL", "300"))
        self.profile_refresh_interval = int(
            os.getenv("WORKER_PROFILE_REFRESH_INTERVAL", str(15 * 60))
        )

        # State
        self.worker_id = None
        self.token = None
        self.session_id = None
        self.work_session_id = None
        self.on_break = False
        self.break_id = None
        self.is_logged_in = False
        self.session_start_time = None
        self.worker_data = {}
        self.monitor_thread = None
        self.monitor_active = False
        self.activity_thread = None
        self.activity_active = False
        self.current_activity_start_time = None
        self.current_activity_signature = None
        self.current_activity_context = {}
        self.login_in_progress = False
        self.profile_refresh_job = None
        self.pending_clock_out_path = self.app_data_dir / "pending_clock_out.json"
        self.pending_clock_out = self._load_pending_clock_out()
        self.pending_clock_out_lock = threading.Lock()
        self.pending_clock_out_retry_thread = None
        self.pending_clock_out_retry_active = False
        self.browser_bridge_port = int(os.getenv("BROWSER_BRIDGE_PORT", "8765"))
        self.browser_context_cache = {}
        self.browser_context_lock = threading.Lock()
        self.browser_bridge_server = None
        self.browser_bridge_thread = None
        self._start_browser_bridge_server()
        self._start_pending_clock_out_retry_loop()

        # System tray
        self.tray_icon = None
        self.tray_thread = None
        self.window_visible = True
        self.tray_image = None
        self.minimize_after_login = False

        # Screenshot tracking for auto checkout
        self.last_screenshot_timestamp = None
        self.last_screenshot_lock = threading.Lock()

        # Screenshot compression (200KB max)
        self.max_screenshot_size_kb = int(os.getenv("MAX_SCREENSHOT_SIZE_KB", "200"))

        # Activity log queue for batch flush
        self.pending_activity_logs = []
        self.pending_activity_lock = threading.Lock()

        # Auto check-in on startup
        self.auto_checkin_done = False

        # Auto run on startup (Windows registry)
        self.run_on_startup = False
        self.startup_key = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
        self.app_name = "WorkerActivityTracker"

        # Screenshot delay tracking
        self.screenshot_count = 0
        self.expected_screenshot_count = 0
        self.screenshot_delay_seconds = 0
        self.session_start_for_delay = None
        self.delay_tracking_lock = threading.Lock()

        # Colors
        self.bg_color = "#f0f0f0"
        self.primary_color = "#667eea"
        self.success_color = "#4CAF50"
        self.danger_color = "#f44336"
        self.warning_color = "#ff9800"

        self.progress_style = ttk.Style(self.root)
        try:
            self.progress_style.theme_use("clam")
        except Exception:
            pass
        self.progress_style.configure(
            "Tracker.Horizontal.TProgressbar",
            troughcolor="#d9d9d9",
            background=self.primary_color,
            bordercolor="#d9d9d9",
            lightcolor=self.primary_color,
            darkcolor=self.primary_color,
        )

        self.root.configure(bg=self.bg_color)
        self._window_icon_image = None
        self._configure_platform_identity()
        self._configure_window_icon()

        # Initialize UI
        self.show_login_screen()

        # Update timer
        self.update_session_time()

        # Hide to tray on window close so the worker keeps running in the background.
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close_request)

        # Handle Windows shutdown event for auto checkout
        if self.is_windows:
            self._setup_shutdown_handler()

        # Initialize system tray
        if TRAY_AVAILABLE:
            self.root.after(500, self._create_system_tray)

        if self.saved_credentials.get("email") and self.saved_credentials.get(
            "password"
        ):
            self.root.after(300, self.auto_login_from_saved_credentials)

    def _asset_roots(self):
        """Return folders that may contain bundled or source-tree assets."""
        roots = []

        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            roots.append(Path(frozen_root))

        module_root = Path(__file__).resolve().parent
        roots.extend([module_root, module_root.parent])

        unique_roots = []
        seen = set()
        for root in roots:
            resolved = root.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_roots.append(resolved)
        return unique_roots

    def _find_asset(self, pattern):
        """Find the first matching asset in the bundle or repository tree."""
        for root in self._asset_roots():
            if not root.exists():
                continue
            matches = sorted(root.rglob(pattern))
            for match in matches:
                if match.is_file():
                    return match
        return None

    def _configure_window_icon(self):
        """Set the application window icon from bundled branding assets."""
        icon_path = self._find_asset("F_icon.png") or self._find_asset("F_icon.ico")
        if not icon_path:
            return

        try:
            if icon_path.suffix.lower() == ".png":
                self._window_icon_image = ImageTk.PhotoImage(Image.open(icon_path))
                self.root.iconphoto(True, self._window_icon_image)
            else:
                try:
                    icon_image = Image.open(icon_path)
                    self._window_icon_image = ImageTk.PhotoImage(icon_image)
                    self.root.iconphoto(True, self._window_icon_image)
                except Exception:
                    self.root.iconbitmap(default=str(icon_path))
        except Exception:
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _configure_platform_identity(self):
        """Apply platform-specific app identity tweaks where supported."""
        if not self.is_windows:
            return

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Tracker.WorkerApp"
            )
        except Exception:
            pass

        try:
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd = self.root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW
            )
        except Exception:
            pass

    def _apply_watermark(self, screenshot):
        """Overlay the configured Web_*_*.png branding on top of a screenshot."""
        watermark_path = self._find_asset("Web_*_*.png")
        if not watermark_path:
            return screenshot

        try:
            base = screenshot.convert("RGBA")
            with Image.open(watermark_path) as source:
                watermark = source.convert("RGBA")
                max_width = max(160, base.width // 5)
                max_height = max(90, base.height // 7)
                scale = min(
                    max_width / watermark.width, max_height / watermark.height, 1.0
                )

                if scale < 1.0:
                    new_size = (
                        max(1, int(watermark.width * scale)),
                        max(1, int(watermark.height * scale)),
                    )
                    watermark = watermark.resize(new_size, Image.LANCZOS)

                layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
                margin = max(12, min(base.width, base.height) // 40)
                x = max(margin, base.width - watermark.width - margin)
                y = max(margin, base.height - watermark.height - margin)

                layer.alpha_composite(watermark, (x, y))
                return Image.alpha_composite(base, layer)
        except Exception as exc:
            print(f"Watermark overlay skipped: {exc}")
            return screenshot

    def _compress_screenshot_to_max_size(self, screenshot, max_size_kb=None):
        """Compress screenshot to fit within max_size_kb (default 200KB).
        Returns BytesIO object with compressed JPEG data."""
        if max_size_kb is None:
            max_size_kb = self.max_screenshot_size_kb

        max_size_bytes = max_size_kb * 1024
        target_h = 720  # Limit height for reasonable file sizes

        # Convert to RGB for JPEG
        img = screenshot.convert("RGB")

        # Scale down if needed
        if img.height > target_h:
            ratio = target_h / img.height
            new_size = (int(img.width * ratio), target_h)
            img = img.resize(new_size, Image.LANCZOS)

        # Start with moderate quality and reduce until under limit
        quality = 85
        min_quality = 40

        while quality >= min_quality:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            size = buf.tell()
            buf.seek(0)

            if size <= max_size_bytes:
                return buf

            quality -= 5
            buf.close()

        # If still too large, reduce dimensions further
        if img.width > 1280:
            ratio = 1280 / img.width
            new_size = (1280, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            quality = 60

            buf = BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            buf.seek(0)
            return buf

        return buf

    def _create_system_tray(self):
        """Create system tray icon with show/hide functionality."""
        if not TRAY_AVAILABLE:
            return

        try:
            # Find icon for tray
            icon_path = self._find_asset("F_icon.png") or self._find_asset("F_icon.ico")
            if icon_path:
                self.tray_image = PILImage.open(str(icon_path))
                # Resize to standard tray icon size
                self.tray_image = self.tray_image.resize((64, 64), PILImage.LANCZOS)
            else:
                # Create a simple default icon
                self.tray_image = PILImage.new("RGB", (64, 64), color=(102, 126, 234))

            menu = (
                pystray.MenuItem(
                    "Show/Hide Window", self._toggle_window_visibility, default=True
                ),
                pystray.MenuItem(
                    "Clock In",
                    self._tray_clock_in,
                    enabled=lambda: self._can_clock_in(),
                ),
                pystray.MenuItem(
                    "Clock Out",
                    self._tray_clock_out,
                    enabled=lambda: self._can_clock_out(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit_application),
            )

            self.tray_icon = pystray.Icon(
                "Worker Activity Tracker", self.tray_image, menu=menu
            )

            # Run tray in daemon thread
            self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
            self.tray_thread.start()
            print("[System Tray] Initialized successfully")
        except Exception as e:
            print(f"[System Tray] Failed to initialize: {e}")

    def _toggle_window_visibility(self):
        """Toggle main window visibility."""
        if self.window_visible:
            self._hide_window_to_tray()
        else:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.window_visible = True
            print("[System Tray] Window shown")

    def _hide_window_to_tray(self):
        """Hide the main window while keeping the process alive."""
        self.root.withdraw()
        self.window_visible = False
        print("[System Tray] Window hidden")

        if self.is_logged_in and (self.session_id or self.work_session_id):
            if not self.monitor_active:
                self._start_monitoring()

    def _minimize_after_login(self):
        """Hide the window shortly after a successful login."""
        if not self.is_logged_in or not self.minimize_after_login:
            return

        self.minimize_after_login = False
        if TRAY_AVAILABLE and self.tray_icon:
            self._hide_window_to_tray()
        else:
            self.root.iconify()
            self.window_visible = False
            print("[System Tray] Window minimized")

    def _can_clock_in(self):
        """Check if clock-in is available."""
        return self.is_logged_in and not self.session_id and not self.work_session_id

    def _can_clock_out(self):
        """Check if clock-out is available."""
        return self.is_logged_in and (self.session_id or self.work_session_id)

    def _tray_clock_in(self):
        """Clock in from system tray."""
        if self._can_clock_in():
            self.root.after(0, self.clock_in)
            # Show window briefly to display success message
            if not self.window_visible:
                self.root.deiconify()
                self.window_visible = True
                self.root.after(3000, self._toggle_window_visibility)

    def _tray_clock_out(self):
        """Clock out from system tray."""
        if self._can_clock_out():
            # Use last screenshot timestamp as checkout time
            with self.last_screenshot_lock:
                checkout_time = self.last_screenshot_timestamp or local_now()

            self.root.after(0, lambda: self._clock_out_with_timestamp(checkout_time))
            # Show window briefly to display confirmation
            if not self.window_visible:
                self.root.deiconify()
                self.window_visible = True
                self.root.after(5000, self._toggle_window_visibility)

    def _clock_out_with_timestamp(self, timestamp):
        """Clock out with a specific timestamp (from last screenshot)."""
        self.status_label.config(text="Clocking out...")
        self._set_loading_indicator(True)
        self.root.update()

        threading.Thread(
            target=self._clock_out_with_timestamp_thread, args=(timestamp,), daemon=True
        ).start()

    def _clock_out_with_timestamp_thread(self, timestamp):
        """Thread function to clock out with specific timestamp."""
        payload = {
            "worker_id": self.worker_id,
            "email": self.worker_data.get("email"),
            "timestamp": timestamp.isoformat(),
            "session_id": self.session_id,
        }

        try:
            response = self._send_clock_out_request(payload)

            if response.status_code == 200:
                self._clear_pending_clock_out()
                self._stop_monitoring()
                self.session_id = None
                self.work_session_id = None
                self.session_start_time = None
                self.on_break = False

                self.root.after(0, self._update_dashboard_after_clock_out)
            else:
                error_msg = response.json().get("message", "Clock out failed")
                self._queue_pending_clock_out(payload)
                self.root.after(
                    0, lambda: self.status_label.config(text="Clock out queued")
                )

        except Exception as e:
            self._queue_pending_clock_out(payload)
            self.root.after(
                0, lambda: self.status_label.config(text="Clock out queued")
            )

        self.root.after(0, lambda: self.status_label.config(text="Ready"))
        self.root.after(0, lambda: self._set_loading_indicator(False))

    def _quit_application(self):
        """Quit the application gracefully."""
        self._shutdown_application()
        self.root.quit()

    def _handle_window_close_request(self):
        """Close button behavior: hide to tray when available, otherwise exit."""
        if TRAY_AVAILABLE:
            self._hide_window_to_tray()
            return

        self._shutdown_application()

    def _on_window_close(self):
        """Handle window close event - auto checkout if clocked in."""
        self._shutdown_application()

    def _shutdown_application(self):
        """Stop background work and destroy the Tk window."""
        if self.session_id or self.work_session_id:
            print(
                "[Auto Checkout] Window closed while clocked in. Performing auto checkout..."
            )

            # Use last screenshot timestamp as checkout time
            with self.last_screenshot_lock:
                checkout_time = self.last_screenshot_timestamp or local_now()

            # Flush all pending activity logs
            self._flush_all_pending_activity()

            # Perform checkout with last screenshot timestamp
            self._clock_out_with_timestamp_thread(checkout_time)

            # Give API call time to complete
            time.sleep(2)

        # Stop monitoring
        self._stop_monitoring()

        # Stop system tray
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        # Destroy window
        try:
            self.root.destroy()
        except Exception:
            pass

    def _setup_shutdown_handler(self):
        """Setup Windows shutdown event handler for auto checkout."""
        try:
            import ctypes.wintypes

            # Windows messages for shutdown
            WM_QUERYENDSESSION = 0x0011
            WM_ENDSESSION = 0x0016

            # Get the Tkinter window handle
            hwnd = self.root.winfo_id()

            # Store original window procedure
            self.original_wnd_proc = ctypes.windll.user32.GetWindowLongW(
                hwnd, -4
            )  # GWL_WNDPROC = -4

            # Define new window procedure
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
            )

            def new_wnd_proc(hwnd, msg, wParam, lParam):
                if msg in (WM_QUERYENDSESSION, WM_ENDSESSION):
                    print(f"[Shutdown] Windows shutdown detected (msg={msg:#x})")
                    # Perform auto checkout immediately
                    self._perform_shutdown_checkout()
                    # Return TRUE to allow shutdown to proceed
                    return 1
                # Call original window procedure
                return ctypes.windll.user32.CallWindowProcW(
                    self.original_wnd_proc, hwnd, msg, wParam, lParam
                )

            # Set new window procedure
            self.new_wnd_proc = WNDPROC(new_wnd_proc)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, -4, ctypes.cast(self.new_wnd_proc, ctypes.c_void_p)
            )

            print("[Shutdown] Windows shutdown handler installed")
        except Exception as e:
            print(f"[Shutdown] Failed to setup shutdown handler: {e}")

    def _perform_shutdown_checkout(self):
        """Perform checkout when PC is shutting down."""
        if not (self.session_id or self.work_session_id):
            print("[Shutdown] Not clocked in, skipping checkout")
            return

        print("[Shutdown] PC shutting down - performing auto checkout...")

        # Use last screenshot timestamp as checkout time
        with self.last_screenshot_lock:
            checkout_time = self.last_screenshot_timestamp or local_now()

        print(f"[Shutdown] Checkout time: {checkout_time.isoformat()}")

        # Flush all pending activity logs
        self._flush_all_pending_activity()

        # Perform checkout with last screenshot timestamp
        payload = {
            "worker_id": self.worker_id,
            "email": self.worker_data.get("email"),
            "timestamp": checkout_time.isoformat(),
            "session_id": self.session_id,
        }

        try:
            # Use a short timeout since system is shutting down
            response = self._send_clock_out_request(payload)

            if response.status_code == 200:
                print("[Shutdown] Checkout successful")
                self._clear_pending_clock_out()
            else:
                print(f"[Shutdown] Checkout failed: {response.status_code}")
                # Queue for retry when system starts again
                self._queue_pending_clock_out(payload)
        except Exception as e:
            print(f"[Shutdown] Checkout error: {e}")
            # Queue for retry
            payload = {
                "worker_id": self.worker_id,
                "email": self.worker_data.get("email"),
                "timestamp": checkout_time.isoformat(),
                "session_id": self.session_id,
            }
            self._queue_pending_clock_out(payload)

        # Stop monitoring immediately
        self._stop_monitoring()

        # Stop system tray
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        print("[Shutdown] Auto checkout complete")

    def show_login_screen(self):
        """Display login screen"""
        self.login_in_progress = False
        self.clear_window()

        # Header
        header = tk.Frame(self.root, bg=self.primary_color, height=80)
        header.pack(fill=tk.X, pady=0)
        header.pack_propagate(False)

        title = tk.Label(
            header,
            text="Worker Login",
            font=("Arial", 24, "bold"),
            fg="white",
            bg=self.primary_color,
        )
        title.pack(pady=15)

        # Login form
        form_frame = tk.Frame(self.root, bg=self.bg_color)
        form_frame.pack(pady=40, padx=40, fill=tk.BOTH, expand=True)

        # Worker email
        tk.Label(
            form_frame, text="Email:", font=("Arial", 12), fg="#333", bg=self.bg_color
        ).pack(anchor="w", pady=(0, 5))
        self.email_entry = tk.Entry(form_frame, font=("Arial", 12), width=40)
        self.email_entry.pack(pady=(0, 20), fill=tk.X)

        # Password
        tk.Label(
            form_frame,
            text="Password:",
            font=("Arial", 12),
            fg="#333",
            bg=self.bg_color,
        ).pack(anchor="w", pady=(0, 5))
        self.password_entry = tk.Entry(
            form_frame, font=("Arial", 12), width=40, show="*"
        )
        self.password_entry.pack(pady=(0, 30), fill=tk.X)

        # Remember me
        self.remember_var = tk.BooleanVar()
        tk.Checkbutton(
            form_frame,
            text="Remember credentials",
            font=("Arial", 10),
            variable=self.remember_var,
            bg=self.bg_color,
        ).pack(anchor="w")

        # Login button
        self.login_btn = tk.Button(
            form_frame,
            text="Login",
            font=("Arial", 13, "bold"),
            bg=self.primary_color,
            fg="white",
            cursor="hand2",
            command=self.login,
            height=2,
        )
        self.login_btn.pack(pady=30, fill=tk.X)

        self._build_status_footer("Ready to login")

        # Bind Enter key
        self.password_entry.bind("<Return>", lambda e: self.login())

        self._populate_saved_login_fields()
        self.email_entry.focus()

    def login(self):
        """Handle worker login"""
        if self.login_in_progress:
            return

        email = self.email_entry.get().strip()
        password = self.password_entry.get().strip()
        api_url = self.API_URL

        if not email or not password:
            messagebox.showerror("Error", "Please enter Email and Password")
            return

        self.login_in_progress = True
        self.login_btn.config(state=tk.DISABLED)
        self.status_label.config(text="Logging in...")
        self._set_loading_indicator(True)
        self.root.update_idletasks()

        # Run login in background thread
        threading.Thread(
            target=self._login_worker, args=(email, password, api_url), daemon=True
        ).start()

    def _set_login_idle(self):
        """Reset login button and state after a failed attempt."""
        self.login_in_progress = False
        if hasattr(self, "login_btn"):
            self.login_btn.config(state=tk.NORMAL)

    def show_toast(self, message, kind="info", duration=2500):
        """Show a temporary in-app notification."""
        colors = {
            "info": "#2f80ed",
            "success": "#4CAF50",
            "warning": "#ff9800",
            "error": "#f44336",
        }

        try:
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.configure(bg=colors.get(kind, "#2f80ed"))

            width = 320
            height = 60
            x = self.root.winfo_x() + self.root.winfo_width() - width - 24
            y = self.root.winfo_y() + self.root.winfo_height() - height - 60
            toast.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

            frame = tk.Frame(toast, bg=colors.get(kind, "#2f80ed"), padx=14, pady=12)
            frame.pack(fill=tk.BOTH, expand=True)

            label = tk.Label(
                frame,
                text=message,
                fg="white",
                bg=colors.get(kind, "#2f80ed"),
                font=("Arial", 10, "bold"),
                wraplength=290,
                justify="left",
            )
            label.pack(anchor="w", fill=tk.BOTH, expand=True)

            toast.after(duration, toast.destroy)
        except Exception:
            pass

    def load_saved_credentials(self):
        """Load saved login data from AppData Local."""
        try:
            if self.credentials_path.exists():
                with open(self.credentials_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def save_credentials(self, api_url, email, password):
        """Persist the local login configuration for auto-login."""
        payload = {
            "api_url": api_url.rstrip("/"),
            "email": email,
            "password": password,
            "saved_at": local_now().isoformat(),
        }
        try:
            self.app_data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.credentials_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.saved_credentials = payload
        except Exception as exc:
            print(f"Failed to save credentials: {exc}")

    def _populate_saved_login_fields(self):
        """Prefill login fields from saved data if present."""
        if not self.saved_credentials:
            return

        if hasattr(self, "email_entry"):
            self.email_entry.delete(0, tk.END)
            self.email_entry.insert(0, self.saved_credentials.get("email", ""))

        if hasattr(self, "password_entry"):
            self.password_entry.delete(0, tk.END)
            self.password_entry.insert(0, self.saved_credentials.get("password", ""))

        if hasattr(self, "remember_var"):
            self.remember_var.set(True)

    def auto_login_from_saved_credentials(self):
        """Automatically sign in if saved credentials exist."""
        email = self.saved_credentials.get("email")
        password = self.saved_credentials.get("password")
        api_url = self.API_URL

        if not email or not password or not api_url or self.login_in_progress:
            return

        self.API_URL = api_url.rstrip("/")
        if hasattr(self, "status_label"):
            self.status_label.config(text="Auto-login in progress...")
        if hasattr(self, "login_btn"):
            self.login_btn.config(state=tk.DISABLED)
        self.login_in_progress = True
        self._set_loading_indicator(True)
        threading.Thread(
            target=self._login_worker, args=(email, password, self.API_URL), daemon=True
        ).start()

    def _login_worker(self, email, password, api_url):
        """Worker login API call"""
        login_payload = {"email": email, "password": password}
        response = None
        try:
            response = requests.post(
                f"{api_url}/api/worker/login", json=login_payload, timeout=5
            )
        except requests.exceptions.RequestException as e:
            self.root.after(
                0, lambda: messagebox.showerror("Error", f"Connection error: {str(e)}")
            )
            self.root.after(
                0, lambda: self.status_label.config(text="Connection error")
            )
            self.root.after(0, lambda: self._set_loading_indicator(False))
            self.root.after(0, self._set_login_idle)
            return
        if response is None:
            self.root.after(
                0, lambda: messagebox.showerror("Login Failed", "Login failed")
            )
            self.root.after(0, lambda: self.status_label.config(text="Login failed"))
            self.root.after(0, lambda: self._set_loading_indicator(False))
            self.root.after(0, self._set_login_idle)
            return

        if response.status_code == 200:
            data = response.json()
            self.token = data.get("token")
            self.worker_data = {
                "id": data.get("worker_id"),
                "worker_id": data.get("worker_id_code") or data.get("worker_id"),
                "worker_id_code": data.get("worker_id_code") or data.get("worker_id"),
                "email": data.get("email", email),
                "name": data.get("name", ""),
            }
            # Use the business worker code (for example WRK001), not the numeric database id.
            self.worker_id = self.worker_data.get(
                "worker_id_code"
            ) or self.worker_data.get("worker_id")
            self.root.after(0, lambda: self.save_credentials(api_url, email, password))
            self._hydrate_worker_profile()
            self.is_logged_in = True
            self.login_in_progress = False
            self.minimize_after_login = True
            self.root.after(0, lambda: self._set_loading_indicator(False))
            self.root.after(0, self.show_dashboard)
            self.root.after(0, self._schedule_profile_refresh)

            # Auto check-in on startup if not already clocked in
            if (
                not self.auto_checkin_done
                and not self.session_id
                and not self.work_session_id
            ):
                self.root.after(2000, self._auto_check_in_on_startup)
                self.auto_checkin_done = True

            # Enable auto-run on startup after successful login
            if self.is_windows:
                self.root.after(1000, self._enable_run_on_startup)
        else:
            try:
                error_msg = response.json().get("message", "Login failed")
            except Exception:
                error_msg = "Login failed"
            self.root.after(0, lambda: messagebox.showerror("Login Failed", error_msg))
            self.root.after(0, lambda: self.status_label.config(text="Login failed"))
            self.root.after(0, lambda: self._set_loading_indicator(False))
            self.root.after(0, self._set_login_idle)

    def _auth_headers(self):
        """Return bearer auth headers for worker requests."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_foreground_window_info(self):
        """Return the active window title and process name on Windows."""
        if self.is_windows:
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    return {}

                length = user32.GetWindowTextLengthW(hwnd)
                title_buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buffer, length + 1)
                window_title = title_buffer.value.strip()

                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process_name = self._get_process_name(pid.value)

                return {
                    "window_title": window_title,
                    "process_name": process_name or "",
                }
            except Exception:
                return {}

        if self.is_macos:
            try:
                script = (
                    'tell application "System Events" to tell (first application process whose frontmost is true) '
                    "to return {name, name of front window}"
                )
                result = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=True,
                )
                output = result.stdout.strip()
                if not output:
                    return {}

                if ", " in output:
                    process_name, window_title = output.split(", ", 1)
                else:
                    process_name, window_title = output, ""

                return {
                    "window_title": window_title.strip(),
                    "process_name": process_name.strip(),
                }
            except Exception:
                return {}

        return {}

    def _get_process_name(self, pid):
        """Resolve a process name from its PID."""
        if not self.is_windows or not pid:
            return ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return ""

            try:
                buffer = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(len(buffer))
                if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)
                ):
                    return os.path.basename(buffer.value)
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return ""

        return ""

    def _normalize_browser_title(self, window_title):
        """Strip browser suffixes from the foreground window title."""
        if not window_title:
            return ""

        suffixes = (
            " - Google Chrome",
            " - Chromium",
            " - Microsoft Edge",
            " - Brave",
            " - Opera",
        )
        for suffix in suffixes:
            if window_title.endswith(suffix):
                return window_title[: -len(suffix)].strip()
        return window_title.strip()

    def _normalize_browser_tab_url(self, tab_url):
        """Preserve a usable browser tab URL for activity uploads."""
        if not tab_url:
            return ""

        cleaned_url = tab_url.strip()
        if not cleaned_url:
            return ""

        parsed = urlparse(cleaned_url)
        if parsed.scheme and parsed.netloc:
            return cleaned_url

        if parsed.netloc:
            return cleaned_url

        if cleaned_url.startswith(("http://", "https://")):
            return cleaned_url

        if parsed.path:
            return parsed.path.split("/")[0]

        return cleaned_url

    def _extract_domain_from_title(self, window_title):
        """Try to infer a host from a browser title when no URL is available."""
        if not window_title:
            return ""

        cleaned_title = window_title.strip().lower()
        if not cleaned_title:
            return ""

        match = re.search(
            r"(?:(?:localhost)|(?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z0-9-]+(?:\.[a-z0-9-]+)+))(?:\:\d{2,5})?",
            cleaned_title,
        )
        if match:
            return match.group(0)

        return ""

    def _normalize_browser_domain(self, value):
        """Normalize a browser identifier to a bare domain name."""
        if not value:
            return ""

        cleaned_value = str(value).strip().lower()
        if not cleaned_value:
            return ""

        parsed = urlparse(cleaned_value)
        if parsed.hostname:
            return parsed.hostname

        if parsed.scheme and parsed.path:
            return parsed.path.split("/")[0].split(":")[0]

        match = re.search(
            r"(?:(?:localhost)|(?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z0-9-]+(?:\.[a-z0-9-]+)+))(?:\:\d{2,5})?",
            cleaned_value,
        )
        if match:
            return match.group(0).split(":")[0]

        if "/" in cleaned_value:
            return cleaned_value.split("/")[0].split(":")[0]

        return cleaned_value.split(":")[0]

    def _is_noise_browser_title(self, title):
        """Return True for transient or dialog titles that should not become activity."""
        if not title:
            return False

        cleaned = str(title).strip().lower()
        if not cleaned:
            return False

        noise_terms = (
            "confirm",
            "task switching",
        )
        return any(term in cleaned for term in noise_terms)

    def _debug_browser_context(self, prefix, context):
        """Print a compact browser context trace for troubleshooting."""
        browser_name = (context.get("browser_name") or "").strip() or "Unknown"
        browser_domain = (context.get("browser_domain") or "").strip() or "N/A"
        browser_tab_url = (context.get("browser_tab_url") or "").strip() or "N/A"
        capture_method = (context.get("tab_capture_method") or "").strip() or "N/A"
        print(
            f"[Browser Debug] {prefix} | browser={browser_name} | domain={browser_domain} | "
            f"url={browser_tab_url} | source={capture_method}"
        )

    def _start_browser_bridge_server(self):
        """Start a tiny localhost server for the browser extension bridge."""
        if self.browser_bridge_server:
            return

        app = self

        class BrowserBridgeHandler(BaseHTTPRequestHandler):
            def _send_json(self, status_code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self._send_json(204, {"ok": True})

            def do_POST(self):
                parsed_path = urlparse(self.path).path.rstrip("/")

                if parsed_path == "/tab-context":
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        raw_body = self.rfile.read(length) if length > 0 else b"{}"
                        data = json.loads(raw_body.decode("utf-8") or "{}")
                        app._update_browser_context_cache(data)
                        self._send_json(200, {"ok": True})
                    except Exception as exc:
                        self._send_json(400, {"ok": False, "message": str(exc)})
                else:
                    self._send_json(404, {"ok": False, "message": "Not found"})

            def log_message(self, format, *args):  # noqa: A003
                return

        try:
            self.browser_bridge_server = ThreadingHTTPServer(
                ("127.0.0.1", self.browser_bridge_port), BrowserBridgeHandler
            )
            self.browser_bridge_server.daemon_threads = True
            self.browser_bridge_thread = threading.Thread(
                target=self.browser_bridge_server.serve_forever,
                daemon=True,
            )
            self.browser_bridge_thread.start()
            print(f"Browser bridge listening on 127.0.0.1:{self.browser_bridge_port}")
        except OSError as exc:
            print(f"Browser bridge unavailable: {exc}")

    def _update_browser_context_cache(self, data):
        """Store the latest browser context from the extension."""
        browser_name = (data.get("browser_name") or "").strip()
        if not browser_name:
            return

        url = (data.get("url") or data.get("browser_tab_url") or "").strip()
        domain = self._normalize_browser_domain(
            data.get("domain") or data.get("browser_domain") or url
        )
        timestamp = data.get("timestamp") or local_now().isoformat()

        with self.browser_context_lock:
            self.browser_context_cache[browser_name.lower()] = {
                "browser_name": browser_name,
                "browser_domain": domain or "",
                "browser_tab_url": url,
                "timestamp": timestamp,
                "updated_at": local_now().isoformat(),
            }

        self._debug_browser_context(
            "bridge",
            {
                "browser_name": browser_name,
                "browser_domain": domain or "",
                "browser_tab_url": url,
                "browser_tab_title": data.get("title")
                or data.get("browser_tab_title")
                or "",
                "browser_window_title": data.get("window_title") or "",
                "tab_capture_method": "browser_extension",
            },
        )
        print(f"[Bridge] {browser_name} | {domain or 'N/A'} | {url}")

    def _get_browser_extension_context(self, process_name):
        """Return the latest browser context from the extension cache if it is fresh."""
        browser_names = {
            "chrome.exe": "Chrome",
            "google chrome": "Chrome",
            "msedge.exe": "Edge",
            "microsoft edge": "Edge",
            "brave.exe": "Brave",
            "brave browser": "Brave",
            "opera.exe": "Opera",
            "opera": "Opera",
            "chromium.exe": "Chromium",
            "firefox.exe": "Firefox",
            "firefox": "Firefox",
            "librewolf.exe": "LibreWolf",
            "librewolf": "LibreWolf",
            "vivaldi.exe": "Vivaldi",
            "vivaldi": "Vivaldi",
            "chromium": "Chromium",
            "safari": "Safari",
        }

        browser_name = browser_names.get((process_name or "").lower(), "")
        if not browser_name:
            return None

        with self.browser_context_lock:
            cached = dict(self.browser_context_cache.get(browser_name.lower()) or {})

        if not cached:
            return None

        cached_at = cached.get("updated_at")
        try:
            age_seconds = (
                (local_now() - datetime.fromisoformat(cached_at)).total_seconds()
                if cached_at
                else None
            )
        except ValueError:
            age_seconds = None

        if age_seconds is not None and age_seconds > 30:
            return None

        return {
            "browser_name": browser_name,
            "browser_window_title": "",
            "browser_tab_title": "",
            "browser_tab_url": cached.get("browser_tab_url", ""),
            "browser_domain": cached.get("browser_domain", ""),
            "tab_capture_method": "browser_extension",
        }

    def _extract_domain_from_title(self, window_title):
        """Try to infer a domain or host from a browser window title."""
        if not window_title:
            return ""

        cleaned_title = window_title.strip().lower()
        if not cleaned_title:
            return ""

        host_match = re.search(
            r"(?:(?:localhost)|(?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z0-9-]+(?:\.[a-z0-9-]+)+))(?:\:\d{2,5})?",
            cleaned_title,
        )
        if host_match:
            return host_match.group(0)

        return ""

    def _fetch_remote_tabs(self):
        """Try Chrome/Edge remote debugging endpoints for richer tab metadata."""
        debug_ports = [9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229]
        extra_ports = os.getenv("BROWSER_REMOTE_DEBUG_PORTS", "").strip()
        if extra_ports:
            for part in extra_ports.split(","):
                try:
                    debug_ports.append(int(part.strip()))
                except ValueError:
                    continue

        seen_ports = set()
        for port in debug_ports:
            if port in seen_ports:
                continue
            seen_ports.add(port)
            try:
                response = requests.get(
                    f"http://127.0.0.1:{port}/json/list", timeout=0.5
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        return data
            except Exception:
                continue
        return []

    def _get_browser_tab_context(self):
        """Collect the current browser window/tab metadata if a browser is active."""
        window_info = self._get_foreground_window_info()
        window_title = window_info.get("window_title", "")
        process_name = (window_info.get("process_name") or "").lower()

        browser_names = {
            "chrome.exe": "Google Chrome",
            "google chrome": "Google Chrome",
            "msedge.exe": "Microsoft Edge",
            "microsoft edge": "Microsoft Edge",
            "brave.exe": "Brave",
            "brave browser": "Brave",
            "opera.exe": "Opera",
            "opera": "Opera",
            "firefox.exe": "Firefox",
            "firefox": "Firefox",
            "librewolf.exe": "LibreWolf",
            "librewolf": "LibreWolf",
            "vivaldi.exe": "Vivaldi",
            "vivaldi": "Vivaldi",
            "chromium.exe": "Chromium",
            "chromium": "Chromium",
            "safari": "Safari",
        }

        tab_context = {
            "browser_name": browser_names.get(process_name, ""),
            "browser_window_title": window_title,
            "browser_tab_title": "",
            "browser_tab_url": "",
            "browser_domain": "",
            "tab_capture_method": "",
        }

        if process_name not in browser_names:
            return tab_context

        extension_context = self._get_browser_extension_context(process_name)
        if extension_context and extension_context.get("browser_domain"):
            tab_context.update(extension_context)
            return tab_context

        remote_tabs = self._fetch_remote_tabs()
        normalized_title = self._normalize_browser_title(window_title)
        selected_tab = None

        for tab in remote_tabs:
            if tab.get("type") != "page":
                continue
            tab_title = (tab.get("title") or "").strip()
            if not tab_title:
                continue
            if tab_title == normalized_title or tab_title == window_title:
                selected_tab = tab
                break
            if normalized_title and (
                normalized_title.lower() in tab_title.lower()
                or tab_title.lower() in normalized_title.lower()
            ):
                selected_tab = tab
                break

        if not selected_tab:
            for tab in remote_tabs:
                if tab.get("type") == "page" and (tab.get("url") or "").startswith(
                    ("http://", "https://")
                ):
                    selected_tab = tab
                    break

        if selected_tab:
            selected_url = self._normalize_browser_tab_url(
                selected_tab.get("url") or ""
            )
            tab_context["browser_tab_url"] = selected_url
            tab_context["browser_tab_title"] = (
                selected_tab.get("title") or normalized_title or ""
            ).strip()
            tab_context["browser_domain"] = self._normalize_browser_domain(selected_url)
            tab_context["tab_capture_method"] = "remote_debugging"
        else:
            if self._is_noise_browser_title(
                window_title
            ) or self._is_noise_browser_title(normalized_title):
                tab_context["tab_capture_method"] = "ignored_noise"
                tab_context["ignore_activity"] = True
                self._debug_browser_context("capture", tab_context)
                return tab_context

            title_parts = [
                part.strip() for part in normalized_title.split(" - ") if part.strip()
            ]
            browser_domain = self._extract_domain_from_title(normalized_title)
            if not browser_domain and len(title_parts) >= 2:
                browser_domain = self._extract_domain_from_title(title_parts[-2])
            if not browser_domain and title_parts:
                browser_domain = self._extract_domain_from_title(title_parts[0])

            tab_context["browser_tab_title"] = ""
            tab_context["browser_domain"] = browser_domain
            tab_context["tab_capture_method"] = "foreground_window"

            if process_name == "brave.exe" and not browser_domain:
                print(
                    "[Browser Debug] Brave fallback has no tab URL. "
                    "Install the Tracker Browser Bridge extension in Brave or enable remote debugging."
                )

        self._debug_browser_context("capture", tab_context)
        return tab_context

    def _get_activity_context(self):
        """Collect the current foreground app/browser context."""
        window_info = self._get_foreground_window_info()
        window_title = (window_info.get("window_title") or "").strip()
        process_name = (window_info.get("process_name") or "").lower().strip()

        browser_context = self._get_browser_tab_context()
        browser_name = (browser_context.get("browser_name") or "").strip()
        browser_tab_title = (browser_context.get("browser_tab_title") or "").strip()
        browser_tab_url = (browser_context.get("browser_tab_url") or "").strip()
        ignore_activity = bool(browser_context.get("ignore_activity"))
        browser_domain = (
            browser_context.get("browser_domain")
            or self._normalize_browser_domain(browser_tab_url)
            or ""
        ).strip()
        tab_capture_method = (browser_context.get("tab_capture_method") or "").strip()

        if browser_name:
            app_name = browser_name
            signature = (
                "browser",
                browser_name,
                browser_domain or browser_name,
            )
        else:
            app_name = process_name or window_title or "Unknown app"
            signature = (
                "app",
                app_name,
                window_title,
            )

        return {
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "browser_name": browser_name,
            "browser_window_title": (
                browser_context.get("browser_window_title") or window_title
            ).strip(),
            "browser_tab_title": browser_tab_title,
            "browser_tab_url": browser_tab_url,
            "browser_domain": browser_domain,
            "tab_capture_method": tab_capture_method,
            "ignore_activity": ignore_activity,
            "signature": signature,
        }

    def _hydrate_worker_profile(self):
        """Load the latest worker profile from the API after login."""
        if not self.token:
            return

        try:
            response = requests.get(
                f"{self.API_URL}/api/worker/profile",
                headers=self._auth_headers(),
                timeout=5,
            )
            if response.status_code == 200:
                profile = response.json().get("worker", {})
                if profile:
                    self.worker_data = profile
                    self.worker_id = profile.get("worker_id") or self.worker_id
                    interval = profile.get("screenshot_interval_seconds")
                    try:
                        if interval is not None:
                            self.screenshot_interval = max(1, int(interval))
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass

    def _schedule_profile_refresh(self):
        """Refresh worker profile periodically to avoid frequent ad-hoc requests."""
        if self.profile_refresh_job is not None:
            try:
                self.root.after_cancel(self.profile_refresh_job)
            except Exception:
                pass
            self.profile_refresh_job = None

        if not self.is_logged_in or not self.token:
            return

        self.profile_refresh_job = self.root.after(
            self.profile_refresh_interval * 1000,
            self._refresh_worker_profile_periodically,
        )

    def _refresh_worker_profile_periodically(self):
        """Refresh the worker profile and reschedule the next refresh."""
        self.profile_refresh_job = None

        if not self.is_logged_in or not self.token:
            return

        self._hydrate_worker_profile()
        self._schedule_profile_refresh()

    def show_dashboard(self):
        """Display main dashboard"""
        self.clear_window()

        # Header
        header = tk.Frame(self.root, bg=self.primary_color, height=70)
        header.pack(fill=tk.X, pady=0)
        header.pack_propagate(False)

        worker_name = self.worker_data.get("name", "")
        title = tk.Label(
            header,
            text=f"Welcome, {worker_name}",
            font=("Arial", 18, "bold"),
            fg="white",
            bg=self.primary_color,
        )
        title.pack(side=tk.LEFT, padx=20, pady=10)

        logout_btn = tk.Button(
            header,
            text="Logout",
            font=("Arial", 10),
            bg="#e74c3c",
            fg="white",
            cursor="hand2",
            command=self.logout,
        )
        logout_btn.pack(side=tk.RIGHT, padx=20, pady=10)

        # Main content
        content = tk.Frame(self.root, bg=self.bg_color)
        content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Session info
        info_frame = tk.LabelFrame(
            content,
            text="Session Information",
            font=("Arial", 12, "bold"),
            padx=15,
            pady=15,
            bg=self.bg_color,
            fg="#333",
        )
        info_frame.pack(fill=tk.X, pady=(0, 20))
        self.populate_session_info(info_frame)
        tip = tk.Label(
            info_frame,
            text="Click Check In to start the timer and screenshot monitoring.",
            font=("Arial", 10),
            fg="#666",
            bg=self.bg_color,
        )
        tip.pack(anchor="w", pady=(0, 8))

        # Clock in/out section
        clock_frame = tk.LabelFrame(
            content,
            text="Clock Management",
            font=("Arial", 12, "bold"),
            padx=15,
            pady=15,
            bg=self.bg_color,
            fg="#333",
        )
        clock_frame.pack(fill=tk.X, pady=(0, 20))
        self.populate_clock_management(clock_frame)

        # Break section
        break_frame = tk.LabelFrame(
            content,
            text="Break Management",
            font=("Arial", 12, "bold"),
            padx=15,
            pady=15,
            bg=self.bg_color,
            fg="#333",
        )
        break_frame.pack(fill=tk.X, pady=(0, 20))
        self.populate_break_management(break_frame)

        self._build_status_footer("Ready")

        if self.minimize_after_login:
            self.root.after(250, self._minimize_after_login)

    def _build_status_footer(self, text):
        """Create the bottom-left status area with a small buffer-style bar."""
        footer = tk.Frame(self.root, bg=self.bg_color)
        footer.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 10))

        left = tk.Frame(footer, bg=self.bg_color)
        left.pack(side=tk.LEFT, anchor="w")

        self.footer_icon = tk.Label(
            left,
            text="✓",
            font=("Segoe UI Symbol", 11, "bold"),
            fg=self.success_color,
            bg=self.bg_color,
        )
        self.footer_icon.pack(side=tk.LEFT, padx=(0, 6))

        self.status_label = tk.Label(
            left,
            text=text,
            font=("Arial", 10),
            fg="#666",
            bg=self.bg_color,
        )
        self.status_label.pack(side=tk.LEFT)

        self.loading_bar = ttk.Progressbar(
            left,
            mode="indeterminate",
            length=120,
            style="Tracker.Horizontal.TProgressbar",
        )
        self.loading_bar.pack(side=tk.LEFT, padx=(10, 0))
        self.loading_bar.pack_forget()

    def _set_loading_indicator(self, active):
        """Toggle the buffer-style loading bar animation."""
        if not hasattr(self, "loading_bar"):
            return

        if active:
            if hasattr(self, "footer_icon"):
                self.footer_icon.config(text="⏳", fg=self.warning_color)
            self.loading_bar.pack(side=tk.LEFT, padx=(10, 0))
            self.loading_bar.start(12)
        else:
            self.loading_bar.stop()
            self.loading_bar.pack_forget()
            if hasattr(self, "footer_icon"):
                self.footer_icon.config(text="✓", fg=self.success_color)

    def populate_session_info(self, parent):
        """Populate session information frame"""
        # Session time
        self.session_time_label = tk.Label(
            parent,
            text="Session Time: --:--:--",
            font=("Arial", 14, "bold"),
            fg=self.primary_color,
            bg=self.bg_color,
        )
        self.session_time_label.pack(pady=10)

        # Status indicator
        self.status_frame = tk.Frame(parent, bg="white", height=30)
        self.status_frame.pack(fill=tk.X, pady=10)

        self.status_circle = tk.Label(
            self.status_frame,
            text="○",
            font=("Segoe UI Symbol", 20),
            fg="#999",
            bg="white",
        )
        self.status_circle.pack(side=tk.LEFT, padx=10)

        self.status_text = tk.Label(
            self.status_frame,
            text="Not Clocked In",
            font=("Arial", 12),
            fg="#666",
            bg="white",
        )
        self.status_text.pack(side=tk.LEFT, padx=5)

    def populate_clock_management(self, parent):
        """Populate clock management buttons"""
        btn_frame = tk.Frame(parent, bg=self.bg_color)
        btn_frame.pack(fill=tk.X)

        self.clock_in_btn = tk.Button(
            btn_frame,
            text="▶ Clock In",
            font=("Arial", 12, "bold"),
            cursor="hand2",
            bg=self.success_color,
            fg="white",
            command=self.clock_in,
            height=2,
        )
        self.clock_in_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.clock_out_btn = tk.Button(
            btn_frame,
            text="⏹ Clock Out",
            font=("Arial", 12, "bold"),
            cursor="hand2",
            bg=self.danger_color,
            fg="white",
            command=self.clock_out,
            height=2,
            state=tk.DISABLED,
        )
        self.clock_out_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def populate_break_management(self, parent):
        """Populate break management buttons"""
        break_btn_frame = tk.Frame(parent, bg=self.bg_color)
        break_btn_frame.pack(fill=tk.X)

        self.break_start_btn = tk.Button(
            break_btn_frame,
            text="☕ Start Break",
            font=("Arial", 11, "bold"),
            cursor="hand2",
            bg=self.warning_color,
            fg="white",
            command=self.start_break,
            state=tk.DISABLED,
        )
        self.break_start_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        self.break_end_btn = tk.Button(
            break_btn_frame,
            text="↩ End Break",
            font=("Arial", 11, "bold"),
            cursor="hand2",
            bg=self.success_color,
            fg="white",
            command=self.end_break,
            state=tk.DISABLED,
        )
        self.break_end_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def clock_in(self):
        """Handle clock in"""
        if self.session_id or self.work_session_id:
            print("[Clock In] Already clocked in.")
            return

        self.status_label.config(text="Clocking in...")
        self._set_loading_indicator(True)
        self.root.update()

        threading.Thread(target=self._clock_in, daemon=True).start()

    def _clock_in(self):
        """Clock in directly against the admin server."""
        try:
            response = requests.post(
                f"{self.API_URL}/api/worker-event/clock-in",
                json={
                    "worker_id": self.worker_id,
                    "email": self.worker_data.get("email"),
                    "timestamp": local_now().isoformat(),
                },
                headers=self._auth_headers(),
                timeout=5,
            )

            if response.status_code == 201:
                data = response.json()
                self.session_id = data.get("work_session_id")
                self.work_session_id = data.get("work_session_id")
                self.session_start_time = local_now()
                self.on_break = False

                # Start screenshot delay tracking
                self._update_delay_tracking_on_clock_in()

                self.root.after(0, self._update_dashboard_after_clock_in)
                self.root.after(0, self._start_monitoring)
            else:
                error_msg = response.json().get("message", "Clock in failed")
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))

        except Exception as e:
            self.root.after(
                0, lambda: messagebox.showerror("Error", f"Connection error: {str(e)}")
            )

        self.root.after(0, lambda: self.status_label.config(text="Ready"))
        self.root.after(0, lambda: self._set_loading_indicator(False))

    def _auto_check_in_on_startup(self):
        """Automatically clock in on app startup after login."""
        if self.session_id or self.work_session_id:
            print("[Auto Check-in] Already clocked in, skipping auto check-in")
            return

        if not self.is_logged_in or not self.worker_id:
            print("[Auto Check-in] Not logged in, skipping auto check-in")
            return

        print("[Auto Check-in] Performing automatic check-in...")
        threading.Thread(target=self._auto_check_in_thread, daemon=True).start()

    def _auto_check_in_thread(self):
        """Thread function for auto check-in."""
        try:
            response = requests.post(
                f"{self.API_URL}/api/worker-event/clock-in",
                json={
                    "worker_id": self.worker_id,
                    "email": self.worker_data.get("email"),
                    "timestamp": local_now().isoformat(),
                },
                headers=self._auth_headers(),
                timeout=5,
            )

            if response.status_code == 201:
                data = response.json()
                self.session_id = data.get("work_session_id")
                self.work_session_id = data.get("work_session_id")
                self.session_start_time = local_now()
                self.on_break = False

                print(
                    f"[Auto Check-in] Successfully clocked in worker {self.worker_id}"
                )
                self.root.after(0, self._update_dashboard_after_clock_in)
                self.root.after(0, self._start_monitoring)

                # Show notification
                self.root.after(
                    0,
                    lambda: self.show_toast(
                        "Auto clocked in on startup!", kind="success"
                    ),
                )
            else:
                print(f"[Auto Check-in] Failed: {response.status_code} {response.text}")
        except Exception as e:
            print(f"[Auto Check-in] Error: {str(e)}")

    def _flush_all_pending_activity(self):
        """Flush all pending activity logs in a single API call."""
        with self.pending_activity_lock:
            if not self.pending_activity_logs:
                return
            logs_to_flush = list(self.pending_activity_logs)
            self.pending_activity_logs.clear()

        if not logs_to_flush:
            return

        print(f"[Batch Flush] Flushing {len(logs_to_flush)} pending activity logs...")

        try:
            payload = {
                "worker_id": self.worker_id,
                "work_session_id": self.work_session_id,
                "activity_segments": logs_to_flush,
            }

            response = requests.post(
                f"{self.API_URL}/api/worker-event/activity-segment-batch",
                json=payload,
                headers=self._auth_headers(),
                timeout=10,
            )

            if response.status_code in (200, 201):
                print(
                    f"[Batch Flush] Successfully flushed {len(logs_to_flush)} activity logs"
                )
            else:
                print(f"[Batch Flush] Failed: {response.status_code} {response.text}")
        except Exception as e:
            print(f"[Batch Flush] Error: {str(e)}")

    def _queue_activity_log(self, activity_data):
        """Queue an activity log for batch flush."""
        with self.pending_activity_lock:
            self.pending_activity_logs.append(activity_data)

    def _enable_run_on_startup(self):
        """Add app to Windows startup registry (runs after successful login)."""
        if not self.is_windows:
            return

        try:
            import winreg

            app_path = os.path.abspath(sys.argv[0])

            # Try to open the key
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, self.startup_key, 0, winreg.KEY_ALL_ACCESS
                )
            except FileNotFoundError:
                # Key doesn't exist, create it
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.startup_key)

            # Set the value
            winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, f'"{app_path}"')
            winreg.CloseKey(key)

            self.run_on_startup = True
            print(f"[Startup] Added to Windows startup: {app_path}")
            self.show_toast("Will run on Windows startup", kind="info", duration=2)
        except Exception as e:
            print(f"[Startup] Failed to add to startup: {e}")

    def _disable_run_on_startup(self):
        """Remove app from Windows startup registry."""
        if not self.is_windows:
            return

        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.startup_key, 0, winreg.KEY_ALL_ACCESS
            )
            winreg.DeleteValue(key, self.app_name)
            winreg.CloseKey(key)

            self.run_on_startup = False
            print("[Startup] Removed from Windows startup")
        except FileNotFoundError:
            pass  # Already not in startup
        except Exception as e:
            print(f"[Startup] Failed to remove from startup: {e}")

    def _calculate_screenshot_delay(self):
        """Calculate how many screenshots are delayed behind schedule."""
        with self.delay_tracking_lock:
            if not self.session_start_for_delay:
                return 0, 0

            elapsed_seconds = (
                local_now() - self.session_start_for_delay
            ).total_seconds()
            expected_count = int(elapsed_seconds / self.screenshot_interval)
            actual_count = self.screenshot_count
            delay_count = max(0, expected_count - actual_count)

            # Calculate delay in seconds
            delay_seconds = delay_count * self.screenshot_interval

            return delay_count, delay_seconds

    def _update_delay_tracking_on_clock_in(self):
        """Reset delay tracking when clocking in."""
        with self.delay_tracking_lock:
            self.screenshot_count = 0
            self.expected_screenshot_count = 0
            self.screenshot_delay_seconds = 0
            self.session_start_for_delay = local_now()

    def _increment_screenshot_count(self):
        """Increment screenshot counter and check delay."""
        with self.delay_tracking_lock:
            self.screenshot_count += 1

            if self.session_start_for_delay:
                elapsed_seconds = (
                    local_now() - self.session_start_for_delay
                ).total_seconds()
                self.expected_screenshot_count = int(
                    elapsed_seconds / self.screenshot_interval
                )
                delay_count = max(
                    0, self.expected_screenshot_count - self.screenshot_count
                )
                self.screenshot_delay_seconds = delay_count * self.screenshot_interval

                if delay_count > 0:
                    print(
                        f"[Screenshot Delay] Behind by {delay_count} screenshots ({self.screenshot_delay_seconds}s delay)"
                    )
                elif self.screenshot_count % 10 == 0:
                    print(
                        f"[Screenshot Status] {self.screenshot_count} captured, on schedule"
                    )

    def _update_dashboard_after_clock_in(self):
        """Update UI after clock in"""
        self.clock_in_btn.config(state=tk.DISABLED)
        self.clock_out_btn.config(state=tk.NORMAL)
        self.break_start_btn.config(state=tk.NORMAL)

        self.status_circle.config(text="✓", fg=self.success_color)
        self.status_text.config(text="Clocked In", fg=self.success_color)

        self.show_toast("Clocked in successfully!", kind="success")

    def clock_out(self):
        """Handle clock out"""
        if messagebox.askyesno("Confirm", "Are you sure you want to clock out?"):
            self.status_label.config(text="Clocking out...")
            self._set_loading_indicator(True)
            self.root.update()

            threading.Thread(target=self._clock_out, daemon=True).start()

    def _clock_out(self):
        """Clock out directly against the admin server."""
        payload = {
            "worker_id": self.worker_id,
            "email": self.worker_data.get("email"),
            "timestamp": local_now().isoformat(),
            "session_id": self.session_id,
        }

        try:
            response = self._send_clock_out_request(payload)

            if response.status_code == 200:
                self._clear_pending_clock_out()
                self._stop_monitoring()
                self.session_id = None
                self.work_session_id = None
                self.session_start_time = None
                self.on_break = False

                self.root.after(0, self._update_dashboard_after_clock_out)
            else:
                error_msg = response.json().get("message", "Clock out failed")
                self._queue_pending_clock_out(payload)
                self.root.after(
                    0, lambda: self.status_label.config(text="Clock out queued")
                )
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Clock out queued",
                        f"{error_msg}\nThe app will retry when the connection returns.",
                    ),
                )

        except Exception as e:
            self._queue_pending_clock_out(payload)
            self.root.after(
                0, lambda: self.status_label.config(text="Clock out queued")
            )
            self.root.after(
                0,
                lambda: messagebox.showwarning(
                    "Clock out queued",
                    f"Connection error: {str(e)}\nThe app will retry when the connection returns.",
                ),
            )

        self.root.after(0, lambda: self.status_label.config(text="Ready"))
        self.root.after(0, lambda: self._set_loading_indicator(False))

    def _update_dashboard_after_clock_out(self):
        """Update UI after clock out"""
        self.clock_in_btn.config(state=tk.NORMAL)
        self.clock_out_btn.config(state=tk.DISABLED)
        self.break_start_btn.config(state=tk.DISABLED)
        self.break_end_btn.config(state=tk.DISABLED)

        self.status_circle.config(text="○", fg="#999")
        self.status_text.config(text="Not Clocked In", fg="#666")
        self.session_time_label.config(text="Session Time: --:--:--")

        self.show_toast("Clocked out successfully!", kind="success")

    def start_break(self):
        """Start break"""
        self.status_label.config(text="Starting break...")
        self._set_loading_indicator(True)
        self.root.update()

        threading.Thread(target=self._start_break, daemon=True).start()

    def _start_break(self):
        """Start break directly against the admin server."""
        try:
            response = requests.post(
                f"{self.API_URL}/api/worker-event/break-start",
                json={
                    "worker_id": self.worker_id,
                    "email": self.worker_data.get("email"),
                    "break_type": "short_break",
                    "timestamp": local_now().isoformat(),
                },
                headers=self._auth_headers(),
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                self.break_id = data.get("break_id")
                self.on_break = True

                self.root.after(0, self._update_dashboard_on_break)
            else:
                error_msg = response.json().get("message", "Break start failed")
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))

        except Exception as e:
            self.root.after(
                0, lambda: messagebox.showerror("Error", f"Connection error: {str(e)}")
            )

        self.root.after(0, lambda: self.status_label.config(text="Ready"))
        self.root.after(0, lambda: self._set_loading_indicator(False))

    def _update_dashboard_on_break(self):
        """Update UI when on break"""
        self.break_start_btn.config(state=tk.DISABLED)
        self.break_end_btn.config(state=tk.NORMAL)
        self.clock_in_btn.config(state=tk.DISABLED)
        self.clock_out_btn.config(state=tk.DISABLED)

        self.status_circle.config(text="⏸", fg=self.warning_color)
        self.status_text.config(text="On Break", fg=self.warning_color)

        self.show_toast("Break started - screenshot capture paused", kind="success")

    def end_break(self):
        """End break"""
        self.status_label.config(text="Ending break...")
        self._set_loading_indicator(True)
        self.root.update()

        threading.Thread(target=self._end_break, daemon=True).start()

    def _end_break(self):
        """End break directly against the admin server."""
        try:
            response = requests.post(
                f"{self.API_URL}/api/worker-event/break-end",
                json={
                    "worker_id": self.worker_id,
                    "email": self.worker_data.get("email"),
                    "break_id": self.break_id,
                    "timestamp": local_now().isoformat(),
                },
                headers=self._auth_headers(),
                timeout=5,
            )

            if response.status_code == 200:
                self.break_id = None
                self.on_break = False

                self.root.after(0, self._update_dashboard_after_break)
            else:
                error_msg = response.json().get("message", "Break end failed")
                self.root.after(0, lambda: messagebox.showerror("Error", error_msg))

        except Exception as e:
            self.root.after(
                0, lambda: messagebox.showerror("Error", f"Connection error: {str(e)}")
            )

        self.root.after(0, lambda: self.status_label.config(text="Ready"))
        self.root.after(0, lambda: self._set_loading_indicator(False))

    def _update_dashboard_after_break(self):
        """Update UI after break"""
        self.break_start_btn.config(state=tk.NORMAL)
        self.break_end_btn.config(state=tk.DISABLED)
        self.clock_in_btn.config(state=tk.DISABLED)
        self.clock_out_btn.config(state=tk.NORMAL)

        self.status_circle.config(text="✓", fg=self.success_color)
        self.status_text.config(text="Clocked In", fg=self.success_color)

        self.show_toast("Break ended - screenshot capture resumed", kind="success")

    def _start_monitoring(self):
        """Start local screenshot monitoring for the active worker session."""
        if self.monitor_active or not self.work_session_id:
            return

        self.monitor_active = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.activity_active = True
        self.activity_thread = threading.Thread(target=self._activity_loop, daemon=True)
        self.activity_thread.start()

    def _stop_monitoring(self):
        """Stop local screenshot monitoring."""
        self._flush_activity_segment()
        self.monitor_active = False
        self.activity_active = False
        self.login_in_progress = False

    def _monitor_loop(self):
        """Capture and upload screenshots until the session ends or break starts."""
        while self.monitor_active and self.is_logged_in and self.work_session_id:
            if self.on_break:
                time.sleep(1)
                continue

            try:
                self._capture_and_upload_screenshot()
            except Exception as e:
                print(f"Screenshot capture error: {str(e)}")

            time.sleep(self.screenshot_interval)

    def _activity_loop(self):
        """Track foreground app/browser segments with one-second resolution."""
        while self.activity_active and self.is_logged_in and self.work_session_id:
            if self.on_break:
                self._flush_activity_segment()
                time.sleep(1)
                continue

            try:
                self._track_foreground_activity()
            except Exception as e:
                print(f"Activity tracking error: {str(e)}")

            time.sleep(1)

    def _track_foreground_activity(self):
        """Record a foreground segment when the active app or tab changes."""
        context = self._get_activity_context()
        if context.get("ignore_activity"):
            if self.current_activity_signature and self.current_activity_start_time:
                self._flush_activity_segment()
            return

        signature = context.get("signature")
        now = local_now()

        if not self.current_activity_signature:
            self.current_activity_signature = signature
            self.current_activity_start_time = now
            self.current_activity_context = context
            return

        if signature == self.current_activity_signature:
            self.current_activity_context = context
            return

        self._flush_activity_segment(now)
        self.current_activity_signature = signature
        self.current_activity_start_time = now
        self.current_activity_context = context

    def _flush_activity_segment(self, end_time=None):
        """Send the currently active foreground segment to the admin API."""
        if not self.current_activity_signature or not self.current_activity_start_time:
            return

        if not self.is_logged_in or not self.work_session_id or not self.worker_id:
            self.current_activity_signature = None
            self.current_activity_start_time = None
            self.current_activity_context = {}
            return

        ended_at = end_time or local_now()
        duration_seconds = max(
            1, int((ended_at - self.current_activity_start_time).total_seconds())
        )

        payload = {
            "worker_id": self.worker_id,
            "work_session_id": self.work_session_id,
            "started_at": self.current_activity_start_time.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_seconds": duration_seconds,
            "app_name": self.current_activity_context.get("app_name", ""),
            "process_name": self.current_activity_context.get("process_name", ""),
            "window_title": self.current_activity_context.get("window_title", ""),
            "browser_name": self.current_activity_context.get("browser_name", ""),
            "browser_window_title": self.current_activity_context.get(
                "browser_window_title", ""
            ),
            "browser_tab_url": self.current_activity_context.get("browser_tab_url", ""),
            "browser_domain": self.current_activity_context.get("browser_domain", ""),
            "tab_capture_method": self.current_activity_context.get(
                "tab_capture_method", ""
            ),
        }

        domain = payload.get("browser_domain", "")
        tab_url = payload.get("browser_tab_url", "")
        if domain or tab_url:
            print(
                f"[Activity] {payload['app_name']} | {domain or 'N/A'} | {tab_url or 'N/A'} | {duration_seconds}s"
            )

        try:
            response = requests.post(
                f"{self.API_URL}/api/worker-event/activity-segment",
                json=payload,
                headers=self._auth_headers(),
                timeout=5,
            )
            if response.status_code not in (200, 201):
                print(
                    f"Failed to upload activity segment: {response.status_code} {response.text}"
                )
        except Exception as e:
            print(f"Activity upload error: {str(e)}")
        finally:
            self.current_activity_signature = None
            self.current_activity_start_time = None
            self.current_activity_context = {}

    def _capture_and_upload_screenshot(self):
        """Capture a screenshot, compress to 200KB max, and upload to admin server."""
        if not self.worker_id or not self.work_session_id:
            return

        if not (ImageGrab or mss):
            print("[Screenshot] Not available - skipping capture")
            return

        screenshot = _capture_screenshot()
        if screenshot is None:
            print("[Screenshot] Capture failed - skipping upload")
            return

        capture_timestamp = local_now()

        # Track last screenshot timestamp for auto checkout
        with self.last_screenshot_lock:
            self.last_screenshot_timestamp = capture_timestamp

        # Track screenshot count and delay
        self._increment_screenshot_count()
        delay_count, delay_seconds = self._calculate_screenshot_delay()

        task_id = f"{self.worker_id}_{capture_timestamp.strftime('%Y%m%d_%H%M%S')}_{int(time.time())}"
        tab_context = self._get_browser_tab_context()

        try:
            # Compress screenshot to max 200KB (JPEG format)
            compressed_buf = self._compress_screenshot_to_max_size(screenshot)
            file_bytes = compressed_buf.getvalue()
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            file_size = len(file_bytes)

            # Prepare file upload
            files = {
                "screenshot": ("screenshot.jpg", BytesIO(file_bytes), "image/jpeg")
            }

            data = {
                "worker_id": self.worker_id,
                "email": self.worker_data.get("email"),
                "work_session_id": self.work_session_id,
                "timestamp": capture_timestamp.isoformat(),
                "file_hash": file_hash,
                "file_size": file_size,
                "browser_name": tab_context.get("browser_name", ""),
                "browser_window_title": tab_context.get("browser_window_title", ""),
                "browser_tab_title": tab_context.get("browser_tab_title", ""),
                "browser_tab_url": tab_context.get("browser_tab_url", ""),
                "tab_capture_method": tab_context.get("tab_capture_method", ""),
                "screenshot_count": self.screenshot_count,
                "expected_screenshot_count": self.expected_screenshot_count,
                "delay_count": delay_count,
                "delay_seconds": delay_seconds,
            }

            response = requests.post(
                f"{self.API_URL}/api/worker-event/screenshot-upload",
                files=files,
                data=data,
                headers=self._auth_headers(),
                timeout=10,
            )

            # Clean up buffer
            compressed_buf.close()

            if response.status_code == 201:
                delay_msg = (
                    f" (Delay: {delay_count} screenshots, {delay_seconds}s)"
                    if delay_count > 0
                    else " (On schedule)"
                )
                print(
                    f"Screenshot #{self.screenshot_count} uploaded for worker {self.worker_id} ({task_id}) - Size: {file_size / 1024:.1f}KB{delay_msg}"
                )
            else:
                print(
                    f"Failed to upload screenshot: {response.status_code} {response.text}"
                )
        except Exception as e:
            print(f"Screenshot capture error: {str(e)}")

    def _push_live_stream_frame(self, image):
        """Compress and push a frame to the admin server live stream at 420p (non-blocking)."""
        try:
            target_h = 480
            target_w = 854
            img = image.convert("RGB")
            ratio = min(target_w / img.width, target_h / img.height, 1.0)
            if ratio < 1.0:
                new_size = (
                    max(1, int(img.width * ratio)),
                    max(1, int(img.height * ratio)),
                )
                img = img.resize(new_size, Image.LANCZOS)
            canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            x_offset = (target_w - img.width) // 2
            y_offset = (target_h - img.height) // 2
            canvas.paste(img, (x_offset, y_offset))

            buf = BytesIO()
            canvas.save(buf, format="JPEG", quality=75)
            frame_data = buf.getvalue()
            buf.close()

            threading.Thread(
                target=self._send_live_frame,
                args=(frame_data,),
                daemon=True,
            ).start()
        except Exception as e:
            print(f"Live stream frame error: {e}")

    def _send_live_frame(self, frame_data):
        """Send a frame to the admin live frame endpoint."""
        try:
            url = f"{self.API_URL}/api/admin/workers/live-frame"
            headers = {"Authorization": f"Bearer {self.token}"}
            requests.post(
                url,
                data=frame_data,
                headers={**headers, "Content-Type": "image/jpeg"},
                params={"worker_id": self.worker_id},
                timeout=5,
            )
        except Exception:
            pass

    def update_session_time(self):
        """Update session time display"""
        if self.session_start_time and self.is_logged_in:
            elapsed = local_now() - self.session_start_time
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)

            if hasattr(self, "session_time_label"):
                self.session_time_label.config(
                    text=f"Session Time: {hours:02d}:{minutes:02d}:{seconds:02d}"
                )

        self.root.after(1000, self.update_session_time)

    def logout(self):
        """Handle logout"""
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            if self.session_id:
                messagebox.showwarning(
                    "Warning", "You are still clocked in. Please clock out first."
                )
                return

            self._stop_monitoring()
            if self.profile_refresh_job is not None:
                try:
                    self.root.after_cancel(self.profile_refresh_job)
                except Exception:
                    pass
                self.profile_refresh_job = None
            self.monitor_thread = None
            self.worker_id = None
            self.token = None
            self.session_id = None
            self.work_session_id = None
            self.is_logged_in = False
            self.session_start_time = None
            self.worker_data = {}
            self.login_in_progress = False
            self.minimize_after_login = False

            self.show_login_screen()

    def _send_clock_out_request(self, payload):
        """Send a clock-out request to the server."""
        return requests.post(
            f"{self.API_URL}/api/worker-event/clock-out",
            json=payload,
            headers=self._auth_headers(),
            timeout=5,
        )

    def _load_pending_clock_out(self):
        """Load a queued clock-out request from disk."""
        try:
            if self.pending_clock_out_path.exists():
                with open(self.pending_clock_out_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return None

    def _save_pending_clock_out(self, payload):
        """Persist a queued clock-out request for later retry."""
        try:
            self.app_data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.pending_clock_out_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception as exc:
            print(f"Failed to save pending clock out: {exc}")

    def _clear_pending_clock_out(self):
        """Delete any queued clock-out request."""
        try:
            if self.pending_clock_out_path.exists():
                self.pending_clock_out_path.unlink()
        except Exception as exc:
            print(f"Failed to clear pending clock out: {exc}")
        self.pending_clock_out = None

    def _queue_pending_clock_out(self, payload):
        """Store the clock-out request and keep retrying until it succeeds."""
        with self.pending_clock_out_lock:
            self.pending_clock_out = dict(payload)
            self._save_pending_clock_out(self.pending_clock_out)

        self._start_pending_clock_out_retry_loop()

    def _start_live_poll(self):
        """Start a background thread that captures and pushes live frames at ~2fps."""
        if self.live_active:
            return
        self.live_active = True
        self.live_thread = threading.Thread(target=self._live_loop, daemon=True)
        self.live_thread.start()

    def _live_loop(self):
        """Continuously capture and push frames to admin server at ~2fps."""
        while self.live_active and self.is_logged_in and self.worker_id and self.token:
            if self.on_break:
                time.sleep(1)
                continue
            try:
                screenshot = _capture_screenshot()
                if screenshot is None:
                    continue
                screenshot = self._apply_watermark(screenshot)
                self._push_live_stream_frame(screenshot)
            except Exception as e:
                print(f"Live poll error: {e}")
            time.sleep(0.5)  # ~2fps

    def _stop_live_poll(self):
        """Stop the live poll loop."""
        self.live_active = False
        if self.live_thread and self.live_thread.is_alive():
            self.live_thread.join(timeout=2)

    def _start_pending_clock_out_retry_loop(self):
        if self.pending_clock_out_retry_active:
            return

        self.pending_clock_out_retry_active = True
        self.pending_clock_out_retry_thread = threading.Thread(
            target=self._pending_clock_out_retry_loop,
            daemon=True,
        )
        self.pending_clock_out_retry_thread.start()

    def _pending_clock_out_retry_loop(self):
        """Retry queued clock-out requests until one succeeds or no request remains."""
        while self.pending_clock_out_retry_active:
            pending = None
            with self.pending_clock_out_lock:
                pending = dict(self.pending_clock_out or {})

            if not pending:
                self.pending_clock_out_retry_active = False
                return

            pending_worker_id = (pending.get("worker_id") or "").strip()
            pending_email = (pending.get("email") or "").strip()
            current_worker_id = (self.worker_id or "").strip()
            current_email = (self.worker_data.get("email") or "").strip()

            if (
                not self.is_logged_in
                or not current_worker_id
                or (pending_worker_id and current_worker_id != pending_worker_id)
                or (pending_email and current_email and pending_email != current_email)
            ):
                time.sleep(3)
                continue

            try:
                response = self._send_clock_out_request(pending)
                if response.status_code == 200:
                    self.root.after(0, self._complete_pending_clock_out)
                    return
            except Exception:
                pass

            time.sleep(5)

    def _complete_pending_clock_out(self):
        """Finalize a successful queued clock-out."""
        self._clear_pending_clock_out()
        self._stop_monitoring()
        self.session_id = None
        self.work_session_id = None
        self.session_start_time = None
        self.on_break = False
        self._update_dashboard_after_clock_out()

    def clear_window(self):
        """Clear all widgets from window"""
        for widget in self.root.winfo_children():
            widget.destroy()


def main():
    try:
        root = tk.Tk()
        app = WorkerApp(root)
        root.mainloop()
    except Exception:
        _show_fatal_error(*sys.exc_info())
        raise


if __name__ == "__main__":
    main()
