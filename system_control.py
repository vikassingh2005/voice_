"""
System Control Module - Executes system-level commands
Opens/closes apps, screenshots, file search, process management, etc.
"""
import os
import sys
import re
import subprocess
import shlex
import shutil
import psutil
import platform
import webbrowser
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


class SystemController:
    """Executes real system commands"""

    def __init__(self):
        self.os_name = platform.system().lower()
        self.home = Path.home()
        self.screenshot_dir = self.home / "Pictures" / "Screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        # Cache of PATH-detectable apps
        self._path_apps_cache = None
        self._bg_jobs: list[dict] = []

    # ============== APP MANAGEMENT ==============

    def _discover_path_apps(self) -> set[str]:
        """Discover all executables in PATH for dynamic app resolution"""
        if self._path_apps_cache is not None:
            return self._path_apps_cache
        path_dirs = os.environ.get("PATH", "").split(":")
        apps = set()
        for d in path_dirs:
            if not d or not os.path.isdir(d):
                continue
            try:
                for f in os.listdir(d):
                    fp = os.path.join(d, f)
                    if os.path.isfile(fp) and os.access(fp, os.X_OK):
                        apps.add(f.lower())
            except PermissionError:
                continue
        self._path_apps_cache = apps
        return apps

    def _resolve_app(self, app_name: str) -> Optional[str]:
        """Resolve an app name to a launch command.
        Returns command string or None if not found."""
        name = app_name.lower().strip()

        app_map = {
            # Browsers
            "firefox": "firefox",
            "mozilla firefox": "firefox",
            "google chrome": "google-chrome",
            "chrome": "google-chrome",
            "chromium": "chromium-browser",
            "brave": "brave-browser",
            "edge": "microsoft-edge",
            "opera": "opera",
            "tor": "torbrowser-launcher",
            "browser": "xdg-open https://google.com",

            # Terminals
            "terminal": "gnome-terminal",
            "gnome terminal": "gnome-terminal",
            "konsole": "konsole",
            "kitty": "kitty",
            "alacritty": "alacritty",
            "terminator": "terminator",
            "xterm": "xterm",
            "console": "gnome-terminal",

            # Editors / IDEs
            "vscode": "code",
            "visual studio code": "code",
            "code": "code",
            "sublime": "subl",
            "sublime text": "subl",
            "vim": "vim",
            "neovim": "nvim",
            "nvim": "nvim",
            "emacs": "emacs",
            "gedit": "gedit",
            "text editor": "gedit",
            "notepad": "gedit",
            "notepadqq": "notepadqq",
            "atom": "atom",
            "pycharm": "pycharm-community",
            "idea": "idea",
            "intellij": "idea",
            "webstorm": "webstorm",
            "phpstorm": "phpstorm",

            # File Managers
            "file manager": "nautilus",
            "files": "nautilus",
            "nautilus": "nautilus",
            "nemo": "nemo",
            "thunar": "thunar",
            "dolphin": "dolphin",
            "pcmanfm": "pcmanfm",
            "caja": "caja",
            "explorer": "nautilus",

            # Office
            "libreoffice": "libreoffice",
            "writer": "libreoffice --writer",
            "calc": "libreoffice --calc",
            "spreadsheet": "libreoffice --calc",
            "impress": "libreoffice --impress",
            "presentation": "libreoffice --impress",
            "draw": "libreoffice --draw",
            "base": "libreoffice --base",
            "math": "libreoffice --math",
            "word": "libreoffice --writer",
            "excel": "libreoffice --calc",
            "powerpoint": "libreoffice --impress",
            "onlyoffice": "onlyoffice-desktopeditors",

            # Media / Graphics
            "vlc": "vlc",
            "video player": "vlc",
            "mpv": "mpv",
            "spotify": "spotify",
            "music player": "spotify",
            "rhythmbox": "rhythmbox",
            "audacious": "audacious",
            "clementine": "clementine",
            "gimp": "gimp",
            "blender": "blender",
            "inkscape": "inkscape",
            "krita": "krita",
            "shotwell": "shotwell",
            "eog": "eog",
            "image viewer": "eog",
            "gwenview": "gwenview",
            "kolourpaint": "kolourpaint",
            "photoscape": "photoscape",

            # Communication
            "discord": "discord",
            "slack": "slack",
            "telegram": "telegram-desktop",
            "whatsapp": "whatsapp-nativefier",
            "signal": "signal-desktop",
            "thunderbird": "thunderbird",
            "mail": "thunderbird",
            "email": "thunderbird",
            "evolution": "evolution",
            "outlook": "evolution",
            "zoom": "zoom",
            "teams": "teams",
            "skype": "skypeforlinux",
            "element": "element-desktop",
            "hexchat": "hexchat",

            # Utilities
            "calculator": "gnome-calculator",
            "calc": "gnome-calculator",
            "gnome calc": "gnome-calculator",
            "gnome calculator": "gnome-calculator",
            "settings": "gnome-control-center",
            "system settings": "gnome-control-center",
            "preferences": "gnome-control-center",
            "control panel": "gnome-control-center",
            "software center": "gnome-software",
            "snap store": "snap-store",
            "disks": "gnome-disks",
            "disk utility": "gnome-disks",
            "gparted": "gparted",
            "partition manager": "gparted",
            "screenshot": "gnome-screenshot --interactive",
            "font manager": "font-manager",
            "archive manager": "file-roller",
            "compression": "file-roller",
            "task manager": "gnome-system-monitor",
            "system monitor": "gnome-system-monitor",
            "resource monitor": "gnome-system-monitor",
            "htop": "gnome-terminal -- htop",
            "baobab": "baobab",
            "disk usage": "baobab",
            "cheese": "cheese",
            "webcam": "cheese",
            "flameshot": "flameshot gui",

            # Development
            "docker": "docker",
            "docker desktop": "docker-desktop",
            "postman": "postman",
            "insomnia": "insomnia",
            "mysql workbench": "mysql-workbench",
            "dbeaver": "dbeaver-ce",
            "datagrip": "datagrip",
            "tableplus": "tableplus",
            "virtualbox": "virtualbox",
            "vagrant": "vagrant",
            "kvm": "virt-manager",
            "virt-manager": "virt-manager",
            "gcc": "gcc",
            "python": "python3",
            "node": "node",
            "npm": "npm",
            "git": "git-bash",
            "gitkraken": "gitkraken",
            "github desktop": "github-desktop",
            "obsidian": "obsidian",
            "jupyter": "jupyter-notebook",

            # Gaming
            "steam": "steam",
            "lutris": "lutris",
            "heroic": "heroic-games-launcher",
            "minecraft": "minecraft-launcher",
            "prism": "prismlauncher",
            "games": "steam",
        }

        if name in app_map:
            return app_map[name]

        # Try finding in PATH
        path_apps = self._discover_path_apps()
        if name in path_apps:
            return name

        # Fuzzy match in PATH (e.g. "chrome" matches "google-chrome")
        for pa in path_apps:
            if name in pa or pa in name:
                return pa

        return None

    def open_app(self, app_name: str) -> str:
        """Open an application by name (resolves via map + PATH)"""
        app_name = app_name.lower().strip()

        cmd = self._resolve_app(app_name)
        if cmd:
            try:
                subprocess.Popen(shlex.split(cmd), start_new_session=True)
                return f"Opening {app_name}, sir."
            except Exception as e:
                return f"Failed to open {app_name}: {e}"

        # Last resort: xdg-open
        try:
            subprocess.Popen(["xdg-open", app_name], start_new_session=True)
            return f"Opening {app_name}, sir."
        except:
            pass

        return f"I couldn't find {app_name}. Try specifying the full command."

    def close_app(self, app_name: str) -> str:
        """Close a running application"""
        app_name = app_name.lower().strip()

        process_map = {
            "firefox": "firefox",
            "chrome": "chrome",
            "chromium": "chromium",
            "code": "code",
            "vscode": "code",
            "spotify": "spotify",
            "discord": "discord",
            "slack": "slack",
            "zoom": "zoom",
            "vlc": "vlc",
            "terminal": "gnome-terminal",
            "thunar": "Thunar",
            "nautilus": "nautilus",
            "dolphin": "dolphin",
            "gedit": "gedit",
            "libreoffice": "soffice",
            "steam": "steam",
            "telegram": "telegram-desktop",
            "thunderbird": "thunderbird",
            "gimp": "gimp",
            "blender": "blender",
        }

        process_name = process_map.get(app_name, app_name)

        killed = False
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if process_name.lower() in proc.info['name'].lower():
                    proc.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if killed:
            return f"Closed {app_name}, sir."
        return f"Could not find {app_name} running."

    # ============== FILE / LOCATION OPENING ==============

    def open_file(self, filename: str) -> str:
        """Search common directories for a file and open it"""
        search_dirs = [
            self.home / "Desktop",
            self.home / "Downloads",
            self.home / "Documents",
            self.home / "Pictures",
            self.home / "Music",
            self.home / "Videos",
            self.home,
        ]

        # Direct path?
        direct = Path(filename).expanduser()
        if direct.exists():
            try:
                subprocess.Popen(["xdg-open", str(direct)], start_new_session=True)
                return f"Opening {direct.name}, sir."
            except Exception as e:
                return f"Failed to open file: {e}"

        # Search in common directories
        name_lower = filename.lower()
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for f in d.iterdir():
                    if f.is_file() and name_lower in f.name.lower():
                        subprocess.Popen(["xdg-open", str(f)], start_new_session=True)
                        return f"Opening {f.name}, sir."
            except PermissionError:
                continue

        return f"I couldn't find '{filename}' on your Desktop, Downloads, or Documents."

    def open_location(self, path: str) -> str:
        """Open a system location (folder)"""
        expanded = Path(path).expanduser()
        try:
            subprocess.Popen(["xdg-open", str(expanded)], start_new_session=True)
            return f"Opening {expanded.name}, sir."
        except Exception as e:
            return f"Failed to open location: {e}"

    # ============== SCREENSHOTS ==============

    def take_screenshot(self, name: str = None) -> str:
        """Capture the screen"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = name or f"screenshot_{timestamp}"
        filepath = self.screenshot_dir / f"{filename}.png"

        try:
            try:
                subprocess.run(["gnome-screenshot", "-f", str(filepath)], check=True)
            except:
                try:
                    subprocess.run(["scrot", str(filepath)], check=True)
                except:
                    raise ImportError("No screenshot tool available")
            return f"Screenshot saved to {filepath}"
        except Exception as e:
            return f"Failed to take screenshot: {e}"

    # ============== FILE OPERATIONS ==============

    def find_file(self, filename: str, search_path: str = None) -> str:
        """Search for a file"""
        if search_path is None:
            search_path = str(self.home)

        matches = []
        filename_lower = filename.lower()

        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.cache', 'venv', '.venv']]
            for f in files:
                if filename_lower in f.lower():
                    matches.append(os.path.join(root, f))
                    if len(matches) >= 10:
                        break
            if len(matches) >= 10:
                break

        if matches:
            result = f"Found {len(matches)} matches:\n"
            for m in matches[:5]:
                result += f"  {m}\n"
            if len(matches) > 5:
                result += f"  ... and {len(matches) - 5} more"
            return result
        return f"No files found matching '{filename}'"

    def create_folder(self, name: str, path: str = None) -> str:
        """Create a new folder"""
        if path is None:
            path = str(self.home)
        folder_path = Path(path) / name
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            return f"Created folder '{name}' at {folder_path}"
        except Exception as e:
            return f"Failed to create folder: {e}"

    def create_file(self, name: str, path: str = None, content: str = "") -> str:
        """Create a new file"""
        if path is None:
            path = str(self.home)
        if not name.endswith(('.txt', '.py', '.md', '.json', '.yaml', '.yml', '.sh', '.html', '.css', '.js')):
            name += ".txt"
        file_path = Path(path) / name
        try:
            file_path.write_text(content)
            return f"Created file '{name}' at {file_path}"
        except Exception as e:
            return f"Failed to create file: {e}"

    def read_file(self, filepath: str, lines: int = 50) -> str:
        """Read contents of a file"""
        try:
            p = Path(filepath).expanduser()
            if not p.exists():
                return f"File not found: {filepath}"
            content = p.read_text()
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            return content
        except Exception as e:
            return f"Failed to read file: {e}"

    def delete_file(self, filepath: str) -> str:
        """Delete a file"""
        try:
            p = Path(filepath).expanduser()
            if p.is_file():
                p.unlink()
                return f"Deleted file: {filepath}"
            elif p.is_dir():
                shutil.rmtree(p)
                return f"Deleted folder: {filepath}"
            return f"Path not found: {filepath}"
        except Exception as e:
            return f"Failed to delete: {e}"

    # ============== WEB ==============

    def web_search(self, query: str) -> str:
        """Perform web search"""
        try:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            return f"Searching the web for '{query}', sir."
        except Exception as e:
            return f"Search failed: {e}"

    def play_youtube(self, query: str) -> str:
        """Play a video on YouTube"""
        try:
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(url)
            return f"Playing '{query}' on YouTube, sir."
        except Exception as e:
            return f"Failed: {e}"

    # ============== SYSTEM INFO ==============

    def get_system_info(self) -> str:
        """Get detailed system information"""
        info = []
        info.append(f"System: {platform.system()} {platform.release()}")
        info.append(f"Machine: {platform.machine()}")
        info.append(f"Processor: {platform.processor()}")

        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        info.append(f"CPU: {cpu_percent}% usage ({cpu_count} cores)")

        mem = psutil.virtual_memory()
        info.append(f"RAM: {mem.percent}% used ({mem.used // (1024**3)}/{mem.total // (1024**3)} GB)")

        disk = psutil.disk_usage('/')
        info.append(f"Disk: {disk.percent}% used ({disk.used // (1024**3)}/{disk.total // (1024**3)} GB)")

        try:
            battery = psutil.sensors_battery()
            if battery:
                info.append(f"Battery: {battery.percent}% {'(Plugged in)' if battery.power_plugged else '(On battery)'}")
        except:
            pass

        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        info.append(f"Uptime: {uptime.days}d {uptime.seconds // 3600}h")

        return "\n".join(info)

    def get_system_stats(self) -> dict:
        """Get system stats as dict"""
        return {
            "cpu": psutil.cpu_percent(interval=0.5),
            "memory": psutil.virtual_memory().percent,
            "memory_used_gb": psutil.virtual_memory().used / (1024**3),
            "memory_total_gb": psutil.virtual_memory().total / (1024**3),
            "disk": psutil.disk_usage('/').percent,
            "disk_used_gb": psutil.disk_usage('/').used / (1024**3),
            "disk_total_gb": psutil.disk_usage('/').total / (1024**3),
        }

    # ============== PROCESS MANAGEMENT ==============

    def list_processes(self, top: int = 10) -> str:
        """List top processes by CPU usage"""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append(proc.info)
            except:
                pass
        processes.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
        result = "Top processes by CPU:\n"
        for p in processes[:top]:
            result += f"  {p['name']}: {p['cpu_percent']:.1f}% CPU\n"
        return result

    def kill_process(self, name: str) -> str:
        """Kill a process by name"""
        killed = []
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if name.lower() in proc.info['name'].lower():
                    proc.kill()
                    killed.append(proc.info['name'])
            except:
                pass
        if killed:
            return f"Killed {len(killed)} process(es): {', '.join(set(killed))}"
        return f"No process found matching '{name}'"

    # ============== POWER ==============

    def shutdown(self) -> str:
        """Shutdown the system"""
        try:
            if self.os_name == "linux":
                subprocess.run(["shutdown", "-h", "now"], check=True)
            elif self.os_name == "windows":
                subprocess.run(["shutdown", "/s", "/t", "0"], check=True)
            elif self.os_name == "darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'])
            return "Shutting down, sir. Goodbye."
        except Exception as e:
            return f"Shutdown failed: {e}"

    def restart(self) -> str:
        """Restart the system"""
        try:
            if self.os_name == "linux":
                subprocess.run(["shutdown", "-r", "now"], check=True)
            elif self.os_name == "windows":
                subprocess.run(["shutdown", "/r", "/t", "0"], check=True)
            elif self.os_name == "darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'])
            return "Restarting, sir."
        except Exception as e:
            return f"Restart failed: {e}"

    def lock(self) -> str:
        """Lock the workstation"""
        try:
            if self.os_name == "linux":
                # Try various lock commands
                for cmd in [["gnome-screensaver-command", "-l"],
                             ["xdg-screensaver", "lock"],
                             ["dm-tool", "lock"],
                             ["loginctl", "lock-session"]]:
                    try:
                        subprocess.run(cmd, check=True)
                        return "Locking your workstation, sir."
                    except:
                        continue
            elif self.os_name == "darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to sleep'])
                return "Locking your workstation, sir."
            elif self.os_name == "windows":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
                return "Locking your workstation, sir."
            return "Lock command failed: no suitable lock tool found."
        except Exception as e:
            return f"Failed to lock workstation: {e}"

    def logoff(self) -> str:
        """Log off the current user"""
        try:
            if self.os_name == "linux":
                subprocess.run(["gnome-session-quit", "--logout", "--no-prompt"], check=True)
            elif self.os_name == "windows":
                subprocess.run(["shutdown", "/l"], check=True)
            elif self.os_name == "darwin":
                subprocess.run(["osascript", "-e", 'tell app "System Events" to log out'])
            return "Logging off, sir."
        except Exception as e:
            return f"Logoff failed: {e}"

    def hibernate(self) -> str:
        """Hibernate the system"""
        try:
            if self.os_name == "linux":
                subprocess.run(["systemctl", "hibernate"], check=True)
            elif self.os_name == "windows":
                subprocess.run(["shutdown", "/h"], check=True)
            elif self.os_name == "darwin":
                subprocess.run(["pmset", "sleepnow"])
            return "System entering hibernation, sir."
        except Exception as e:
            return f"Hibernate failed: {e}"

    def sleep(self) -> str:
        """Put system to sleep"""
        try:
            if self.os_name == "linux":
                subprocess.run(["systemctl", "suspend"], check=True)
            elif self.os_name == "windows":
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
            elif self.os_name == "darwin":
                subprocess.run(["pmset", "sleepnow"])
            return "System entering sleep mode, sir."
        except Exception as e:
            return f"Sleep failed: {e}"

    # ============== DATE / TIME ==============

    def get_time(self) -> str:
        now = datetime.now()
        return f"The time is {now.strftime('%I:%M %p')}, sir."

    def get_date(self) -> str:
        now = datetime.now()
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        return f"Today is {days[now.weekday()]}, {months[now.month - 1]} {now.day}, {now.year}."

    # ============== VOLUME ==============

    def volume_control(self, action: str) -> str:
        """Control volume (up, down, mute)"""
        try:
            if self.os_name == "linux":
                if action == "up":
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "5%+"])
                elif action == "down":
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "5%-"])
                elif action == "mute":
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "toggle"])
            elif self.os_name == "darwin":
                if action == "up":
                    subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) + 5)"])
                elif action == "down":
                    subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) - 5)"])
                elif action == "mute":
                    subprocess.run(["osascript", "-e", "set volume with output muted"])
            return f"Volume {action}ed, sir."
        except Exception as e:
            return f"Volume control failed: {e}"

    # ============== CLIPBOARD ==============

    def clipboard_control(self, action: str) -> str:
        """Control clipboard: copy, cut, paste, select_all"""
        try:
            if action == "copy":
                subprocess.run(["xdotool", "key", "ctrl+c"], check=True)
                return "Copied to clipboard, sir."
            elif action == "cut":
                subprocess.run(["xdotool", "key", "ctrl+x"], check=True)
                return "Cut to clipboard, sir."
            elif action == "paste":
                subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
                return "Pasted from clipboard, sir."
            elif action == "select_all":
                subprocess.run(["xdotool", "key", "ctrl+a"], check=True)
                return "Selected all, sir."
            return f"Unknown clipboard action: {action}"
        except FileNotFoundError:
            return "Clipboard control requires xdotool. Install with: sudo apt install xdotool"
        except Exception as e:
            return f"Clipboard action failed: {e}"

    # ============== FOLDER OPENING ==============

    def open_folder(self, path: str = None) -> str:
        """Open a folder in file manager"""
        if path is None:
            path = str(self.home)
        try:
            subprocess.Popen(["xdg-open", path], start_new_session=True)
            return f"Opening folder: {path}"
        except Exception as e:
            return f"Failed to open folder: {e}"

    # ============== EXECUTE TERMINAL COMMAND ==============

    def run_terminal_command(self, command: str) -> str:
        """Execute a terminal command"""
        background = False
        trimmed = command.strip()
        if trimmed.startswith('bg '):
            background = True
            command = trimmed[3:].strip()
        try:
            if background:
                proc = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                job = {
                    "id": str(len(self._bg_jobs) + 1),
                    "command": command,
                    "pid": proc.pid,
                    "status": "running",
                }
                self._bg_jobs.append(job)
                return f"Started background job [{job['id']}] PID {proc.pid}: {command}"
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout.strip() if result.stdout else result.stderr.strip()
            if not output:
                output = "Command executed successfully."
            return output[:1000]  # Limit output length
        except subprocess.TimeoutExpired:
            return "Command timed out."
        except Exception as e:
            return f"Command failed: {e}"

    def list_jobs(self) -> str:
        """List tracked background jobs"""
        if not self._bg_jobs:
            return "No background jobs."
        lines = ["Background jobs:"]
        for job in self._bg_jobs:
            lines.append(f"  [{job['id']}] PID {job['pid']} - {job['status']} - {job['command']}")
        return "\n".join(lines)

    # ============== WEATHER (via wttr.in) ==============

    def get_weather(self, location: str = "") -> str:
        """Get weather (uses wttr.in)"""
        try:
            import urllib.request
            url = f"https://wttr.in/{location}?format=3" if location else "https://wttr.in/?format=3"
            with urllib.request.urlopen(url, timeout=5) as response:
                weather = response.read().decode().strip()
            return weather
        except Exception as e:
            return f"Could not fetch weather: {e}"

    # ============== CALCULATOR ==============

    def calculate(self, expression: str) -> str:
        """Simple calculator"""
        try:
            result = eval(expression, {"__builtins__": {}})
            return f"{expression} = {result}"
        except Exception as e:
            return f"Calculation error: {e}"

    def read_notifications(self) -> str:
        """Read recent notifications from the OS notification store (GNOME/D-Bus best effort)."""
        try:
            import dbus
            bus = dbus.SessionBus()
            notif = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            iface = dbus.Interface(notif, "org.freedesktop.Notifications")
            caps = iface.GetCapabilities()
            if "body" in caps:
                return "Notifications are available via D-Bus."
            return "D-Bus notifications interface unavailable."
        except Exception:
            pass
        try:
            saved = subprocess.run(
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications", "--object-path", "/org/freedesktop/Notifications", "--method", "org.freedesktop.Notifications.GetServerInformation"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if saved.returncode == 0:
                return "Notifications available via freedesktop portal."
        except Exception:
            pass
        return "I cannot read notifications in this environment yet."
