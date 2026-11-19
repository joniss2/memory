# Spiegelt Android-Handys über USB in die aktuelle OBS-Szene.
# scrcpy holt das Bild, OBS nimmt das scrcpy-Fenster auf.
# Vor Odin alle Spiegel stoppen: Download-Modus hat kein USB-Debugging,
# und scrcpy belegt dasselbe Kabel. Nicht zusammen mit record-display.ps1
# auf demselben Handy starten.

import ctypes
import os
import re
import subprocess
import threading
from ctypes import wintypes

try:
    import obspython as obs
except ImportError:
    obs = None

METHOD_WGC = 2
PRIORITY_TITLE = 1
CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010
ALIGN_CENTER = 0
ALIGN_LEFT = 1
ALIGN_TOP = 4
POLL_MS = 2000
GIVE_UP_AFTER = 3

script_settings = None


class Settings:
    def __init__(self, aktiv, fps, bitrate, max_size, stay_awake, borderless, control, auto_scene):
        self.aktiv = aktiv
        self.fps = fps
        self.bitrate = bitrate
        self.max_size = max_size
        self.stay_awake = stay_awake
        self.borderless = borderless
        self.control = control
        self.auto_scene = auto_scene

    def signature(self):
        return (
            self.fps,
            self.bitrate,
            self.max_size,
            self.stay_awake,
            self.borderless,
            self.control,
        )


class Mirror:
    def __init__(self, serial, title, args, proc):
        self.serial = serial
        self.title = title
        self.args = args
        self.proc = proc
        self.log = ""
        self.window_seen = False
        self._chunks = []
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _drain(self):
        try:
            while True:
                piece = self.proc.stderr.readline()
                if not piece:
                    break
                self._chunks.append(piece)
                if len(self._chunks) > 40:
                    self._chunks = self._chunks[-40:]
        except Exception:
            return
        self.log = "".join(self._chunks)[-2000:]

    def running(self):
        return self.proc.poll() is None

    def finish_log(self):
        self.thread.join(timeout=0.5)


class State:
    def __init__(self):
        self.settings = None
        self.paused = False
        self.mirrors = {}
        self.names = {}
        self.models = {}
        self.placed = set()
        self.gave_up = set()
        self.errors = {}
        self.tools = None
        self.server_started = False
        self.busy = False
        self.status = "Noch nicht gesucht."


state = State()


def encode_obs_field(value):
    # OBS speichert Fenster als Titel:Klasse:Exe und maskiert die Trennzeichen.
    return value.replace("#", "#22").replace(":", "#3A")


def window_capture_value(title, class_name, exe):
    return ":".join(encode_obs_field(part) for part in (title, class_name, exe))


def is_network_serial(serial):
    return ":" in serial or "._tcp" in serial


def parse_adb_devices(text):
    devices = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, mode = parts[0], parts[1]
        if mode not in ("device", "unauthorized", "offline"):
            continue
        model = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1]
                break
        devices.append(
            {
                "serial": serial,
                "state": mode,
                "usb": any(token.startswith("usb:") for token in parts[2:]),
                "model": model,
            }
        )
    return devices


def usb_phones(devices):
    ready = []
    waiting = []
    for device in devices:
        if device["serial"].startswith("emulator-") or is_network_serial(device["serial"]):
            continue
        if device["state"] == "device" and device["usb"]:
            ready.append(device)
        elif device["state"] in ("unauthorized", "offline"):
            waiting.append(device)
    return ready, waiting


def source_name(serial, model, assigned, peers_same_model):
    if serial in assigned:
        return assigned[serial]
    base = (model or serial).strip() or serial
    if peers_same_model > 1:
        name = f"Handy {base} {serial[-4:]}"
    else:
        name = f"Handy {base}"
    assigned[serial] = name
    return name


def window_title_for(serial):
    token = re.sub(r"[^A-Za-z0-9._-]", "-", serial)[:80] or "handy"
    return f"USB-Handy-{token}"


def scrcpy_command(scrcpy, serial, title, index, settings):
    args = [
        scrcpy,
        f"--serial={serial}",
        "--no-audio",
        "--video-codec=h264",
        f"--video-bit-rate={settings.bitrate}M",
        f"--max-fps={settings.fps}",
        f"--window-title={title}",
        f"--window-x={80 + index * 48}",
        f"--window-y={80 + index * 36}",
    ]
    if settings.stay_awake:
        args.append("--stay-awake")
    if settings.borderless:
        args.append("--window-borderless")
    if not settings.control:
        args.append("--no-control")
    if settings.max_size > 0:
        args.append(f"--max-size={settings.max_size}")
    return args


def command_signature(args):
    return tuple(
        arg for arg in args if not arg.startswith("--window-x=") and not arg.startswith("--window-y=")
    )


def find_tools():
    scrcpy = _which("scrcpy")
    if not scrcpy:
        root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
        scrcpy = _find_named(root, "scrcpy.exe")
    if not scrcpy:
        raise FileNotFoundError("scrcpy nicht gefunden. Installation: winget install --id Genymobile.scrcpy -e")
    adb = os.path.join(os.path.dirname(scrcpy), "adb.exe")
    if not os.path.isfile(adb):
        adb = _which("adb")
    if not adb:
        raise FileNotFoundError("adb liegt nicht neben scrcpy und nicht im PATH.")
    return scrcpy, adb


def _which(name):
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for folder in paths:
        candidate = os.path.join(folder, name + ".exe")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _find_named(root, filename):
    if not root or not os.path.isdir(root):
        return None
    for dirpath, _dirnames, files in os.walk(root):
        if filename in files:
            return os.path.join(dirpath, filename)
    return None


def run_adb(adb, args, timeout):
    completed = subprocess.run(
        [adb, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
        encoding="utf-8",
        errors="replace",
    )
    return completed.returncode, completed.stdout, completed.stderr


def _bind_win32():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return user32, kernel32


_user32, _kernel32 = _bind_win32()


def _exe_name(pid):
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value)
    finally:
        _kernel32.CloseHandle(handle)


def find_scrcpy_window(title):
    found = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        text = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, text, length + 1)
        if text.value != title:
            return True
        class_name = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, class_name, 256)
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _exe_name(pid.value)
        if exe.lower() != "scrcpy.exe":
            return True
        found["hwnd"] = hwnd
        found["class_name"] = class_name.value or "SDL_app"
        found["exe"] = exe
        return False

    _user32.EnumWindows(visit, 0)
    if not found:
        return None
    return found["hwnd"], found["class_name"], found["exe"]


def last_error_line(log):
    lines = [line.strip() for line in (log or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][:180]


def read_settings(settings):
    return Settings(
        aktiv=bool(obs.obs_data_get_bool(settings, "aktiv")),
        fps=int(obs.obs_data_get_int(settings, "fps") or 60),
        bitrate=int(obs.obs_data_get_int(settings, "bitrate") or 16),
        max_size=int(obs.obs_data_get_int(settings, "max_size") or 0),
        stay_awake=bool(obs.obs_data_get_bool(settings, "stay_awake")),
        borderless=bool(obs.obs_data_get_bool(settings, "borderless")),
        control=bool(obs.obs_data_get_bool(settings, "control")),
        auto_scene=bool(obs.obs_data_get_bool(settings, "auto_scene")),
    )


def apply_settings(settings):
    if obs is None or settings is None:
        return
    global script_settings
    script_settings = settings
    new = read_settings(settings)
    previous = state.settings
    changed = previous is not None and new.signature() != previous.signature()
    turned_on = new.aktiv and (previous is None or not previous.aktiv)
    state.settings = new
    if not new.aktiv:
        state.paused = True
        stop_all()
        return
    if turned_on:
        state.paused = False
        state.gave_up.clear()
        kick()
    elif changed and not state.paused:
        state.gave_up.clear()
        stop_all()
        kick()


def set_status(text):
    if text == state.status:
        return
    state.status = text
    if obs is not None:
        obs.script_log(obs.LOG_INFO, text)
        if script_settings is not None:
            obs.obs_data_set_string(script_settings, "status", text)


def stop_all():
    for serial in list(state.mirrors):
        close_mirror(state.mirrors[serial])


def close_mirror(mirror):
    proc = mirror.proc
    if proc.poll() is None:
        window = find_scrcpy_window(mirror.title)
        if window is not None:
            _user32.PostMessageW(window[0], WM_CLOSE, 0, 0)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
        else:
            proc.terminate()
        if proc.poll() is None:
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
    state.mirrors.pop(mirror.serial, None)


def start_mirror(scrcpy, serial, title, index, settings):
    args = scrcpy_command(scrcpy, serial, title, index, settings)
    signature = command_signature(args)
    current = state.mirrors.get(serial)
    if current and current.running() and current.args == signature:
        return current
    if current:
        close_mirror(current)
    env = os.environ.copy()
    adb = state.tools[1]
    env["ADB"] = adb
    proc = subprocess.Popen(
        args,
        cwd=os.path.dirname(scrcpy),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    mirror = Mirror(serial, title, signature, proc)
    state.mirrors[serial] = mirror
    return mirror


def ensure_source(name, title, class_name, exe, index, force):
    desired = window_capture_value(title, class_name, exe)
    source = obs.obs_get_source_by_name(name)
    if source is None:
        data = capture_settings(desired)
        source = obs.obs_source_create("window_capture", name, data, None)
        obs.obs_data_release(data)
    if source is None:
        return
    try:
        current_data = obs.obs_source_get_settings(source)
        current = obs.obs_data_get_string(current_data, "window") if current_data is not None else ""
        if current_data is not None:
            obs.obs_data_release(current_data)
        if force or current != desired:
            data = capture_settings(desired)
            obs.obs_source_update(source, data)
            obs.obs_data_release(data)
        if state.settings.auto_scene and name not in state.placed:
            if place_in_current_scene(source, name, index):
                state.placed.add(name)
    finally:
        obs.obs_source_release(source)


def capture_settings(window_value):
    data = obs.obs_data_create()
    obs.obs_data_set_string(data, "window", window_value)
    obs.obs_data_set_int(data, "method", METHOD_WGC)
    obs.obs_data_set_int(data, "priority", PRIORITY_TITLE)
    obs.obs_data_set_bool(data, "cursor", False)
    obs.obs_data_set_bool(data, "client_area", True)
    obs.obs_data_set_bool(data, "capture_audio", False)
    return data


def place_in_current_scene(source, name, index):
    scene_source = obs.obs_frontend_get_current_preview_scene()
    if scene_source is None:
        return False
    try:
        scene = obs.obs_scene_from_source(scene_source)
        if scene is None:
            return False
        existing = obs.obs_scene_find_source(scene, name)
        if existing is not None:
            return True
        item = obs.obs_scene_add(scene, source)
        if item is None:
            return False
        info = obs.obs_video_info()
        if not obs.obs_get_video_info(info):
            return True
        canvas_h = float(info.base_height or 1080)
        canvas_w = float(info.base_width or 1920)
        bound_h = canvas_h * 0.92
        bound_w = bound_h * 0.45
        gap = max(24.0, canvas_w * 0.02)
        pos = obs.vec2()
        pos.x = gap + index * (bound_w + gap)
        pos.y = canvas_h * 0.04
        obs.obs_sceneitem_set_pos(item, pos)
        bounds = obs.vec2()
        bounds.x = bound_w
        bounds.y = bound_h
        obs.obs_sceneitem_set_bounds(item, bounds)
        obs.obs_sceneitem_set_bounds_type(item, obs.OBS_BOUNDS_SCALE_INNER)
        obs.obs_sceneitem_set_alignment(item, ALIGN_LEFT | ALIGN_TOP)
        obs.obs_sceneitem_set_bounds_alignment(item, ALIGN_CENTER)
        return True
    finally:
        obs.obs_source_release(scene_source)


def read_model(adb, serial, fallback):
    if serial in state.models:
        return state.models[serial]
    model = ""
    try:
        code, out, _err = run_adb(adb, ["-s", serial, "shell", "getprop", "ro.product.model"], 4)
        if code == 0:
            model = out.strip()
    except subprocess.TimeoutExpired:
        model = ""
    if not model:
        model = (fallback or serial).replace("_", " ")
    state.models[serial] = model
    return model


def adb_text(adb):
    if not state.server_started:
        run_adb(adb, ["start-server"], 8)
        state.server_started = True
    _code, out, _err = run_adb(adb, ["devices", "-l"], 5)
    return out


def note_failure(serial, mirror):
    mirror.finish_log()
    state.errors[serial] = last_error_line(mirror.log) or f"scrcpy beendet ({mirror.proc.returncode})"
    count = state.errors.get(serial + ":count", 0) + 1
    state.errors[serial + ":count"] = count
    if count >= GIVE_UP_AFTER:
        state.gave_up.add(serial)


def sync():
    if state.busy:
        return state.status
    if state.settings is None or not state.settings.aktiv or state.paused:
        return state.status
    state.busy = True
    try:
        return _sync()
    except subprocess.TimeoutExpired:
        set_status("adb antwortet nicht. Kabel prüfen, dann das Skript neu laden.")
        return state.status
    except FileNotFoundError as exc:
        set_status(str(exc))
        return state.status
    except Exception as exc:
        if obs is not None:
            obs.script_log(obs.LOG_ERROR, str(exc))
        set_status(f"Spiegel fehlgeschlagen: {exc}")
        return state.status
    finally:
        state.busy = False


def _sync():
    if state.tools is None or isinstance(state.tools, FileNotFoundError):
        try:
            state.tools = find_tools()
        except FileNotFoundError as exc:
            state.tools = exc
    if isinstance(state.tools, FileNotFoundError):
        set_status(str(state.tools))
        return state.status
    scrcpy, adb = state.tools
    devices = parse_adb_devices(adb_text(adb))
    ready, waiting = usb_phones(devices)
    present = {device["serial"] for device in ready}
    for serial in list(state.gave_up):
        if serial not in present:
            state.gave_up.discard(serial)
            state.errors.pop(serial, None)
            state.errors.pop(serial + ":count", None)
    for serial in list(state.mirrors):
        if serial not in present:
            close_mirror(state.mirrors[serial])

    model_counts = {}
    models = {}
    for device in ready:
        model = read_model(adb, device["serial"], device["model"])
        models[device["serial"]] = model
        model_counts[model] = model_counts.get(model, 0) + 1

    parts = []
    for index, device in enumerate(ready):
        serial = device["serial"]
        model = models[serial]
        label = model or serial
        if serial in state.gave_up:
            parts.append(f"{label}: {state.errors.get(serial, 'scrcpy beendet')}")
            continue
        previous = state.mirrors.get(serial)
        if previous is not None and not previous.running():
            note_failure(serial, previous)
            close_mirror(previous)
            if serial in state.gave_up:
                parts.append(f"{label}: {state.errors.get(serial, 'scrcpy beendet')}")
                continue
        title = window_title_for(serial)
        mirror = start_mirror(scrcpy, serial, title, index, state.settings)
        if not mirror.running():
            note_failure(serial, mirror)
            close_mirror(mirror)
            parts.append(f"{label}: {state.errors.get(serial, 'scrcpy beendet')}")
            continue
        window = find_scrcpy_window(title)
        if window is None:
            class_name, exe = "SDL_app", "scrcpy.exe"
            force = False
            parts.append(f"{label}: Fenster startet")
        else:
            _hwnd, class_name, exe = window
            force = not mirror.window_seen
            mirror.window_seen = True
            parts.append(f"{label}: Spiegel läuft")
        name = source_name(serial, model, state.names, model_counts[model])
        ensure_source(name, title, class_name, exe, index, force)

    for device in waiting:
        label = device["model"].replace("_", " ") or device["serial"]
        if device["state"] == "unauthorized":
            parts.append(f"{label}: am Handy „Immer von diesem Computer zulassen“ tippen")
        else:
            parts.append(f"{label}: {device['state']}")

    if not parts:
        text = "Kein USB-Handy. USB-Debugging an, Datenkabel, Dateiübertragung."
        if any(device["serial"].startswith("emulator-") for device in devices):
            text += " Der Emulator an adb wird nicht gespiegelt."
    else:
        text = " | ".join(parts)
    set_status(text)
    return text


def on_timer():
    sync()


def soon():
    if obs is not None:
        obs.timer_remove(soon)
    sync()


def kick():
    if obs is None:
        return
    obs.timer_remove(soon)
    obs.timer_add(soon, 300)


def on_refresh(*_args):
    state.paused = False
    state.gave_up.clear()
    state.server_started = False
    if isinstance(state.tools, FileNotFoundError):
        state.tools = None
    if script_settings is not None and obs is not None:
        obs.obs_data_set_bool(script_settings, "aktiv", True)
        if state.settings is not None:
            state.settings.aktiv = True
    sync()
    return True


def on_stop(*_args):
    state.paused = True
    stop_all()
    if script_settings is not None and obs is not None:
        obs.obs_data_set_bool(script_settings, "aktiv", False)
        if state.settings is not None:
            state.settings.aktiv = False
    set_status("Spiegel gestoppt. Das Kabel ist frei für Odin. Zum Weiterspiegeln die Automatik wieder einschalten.")
    return True


def script_description():
    return (
        "Spiegelt Android-Handys, die per USB mit USB-Debugging hängen, "
        "in die aktuelle Szene. Jedes Handy wird eine Fensteraufnahme "
        "„Handy <Modell>“. Ton bleibt aus.\n\n"
        "Auf dem PC muss scrcpy installiert sein "
        "(winget install --id Genymobile.scrcpy -e). "
        "Python 3.12 64-bit eintragen unter Skripte, Python-Einstellungen: "
        "%LocalAppData%\\Programs\\Python\\Python312\n\n"
        "Am Handy den Dialog mit „Immer von diesem Computer zulassen“ bestätigen. "
        "Das scrcpy-Fenster offen lassen und nicht minimieren. "
        "Vor Odin „Alle Spiegel stoppen“: scrcpy und Odin teilen sich das Kabel. "
        "Nicht gleichzeitig mit record-display.ps1 auf demselben Handy."
    )


def script_defaults(settings):
    obs.obs_data_set_default_bool(settings, "aktiv", True)
    obs.obs_data_set_default_int(settings, "fps", 60)
    obs.obs_data_set_default_int(settings, "bitrate", 16)
    obs.obs_data_set_default_int(settings, "max_size", 0)
    obs.obs_data_set_default_bool(settings, "stay_awake", True)
    obs.obs_data_set_default_bool(settings, "borderless", True)
    obs.obs_data_set_default_bool(settings, "control", False)
    obs.obs_data_set_default_bool(settings, "auto_scene", True)
    obs.obs_data_set_default_string(settings, "status", "Noch nicht gesucht.")


def script_properties():
    props = obs.obs_properties_create()
    obs.obs_properties_add_bool(props, "aktiv", "USB-Handys automatisch spiegeln")
    obs.obs_properties_add_int(props, "fps", "Bilder pro Sekunde", 15, 120, 5)
    obs.obs_properties_add_int(props, "bitrate", "Bitrate (Mbit/s)", 2, 64, 1)
    obs.obs_properties_add_int(props, "max_size", "Längere Kante in Pixeln (0 = Handy-Auflösung)", 0, 2560, 120)
    obs.obs_properties_add_bool(props, "stay_awake", "Display am Handy wach halten")
    obs.obs_properties_add_bool(props, "borderless", "Spiegel ohne Fensterrand")
    obs.obs_properties_add_bool(props, "control", "Klicks im Spiegel ans Handy schicken")
    obs.obs_properties_add_bool(props, "auto_scene", "Neue Handys in die aktuelle Szene legen")
    obs.obs_properties_add_button(props, "refresh", "Handys jetzt suchen", on_refresh)
    obs.obs_properties_add_button(props, "stop", "Alle Spiegel stoppen", on_stop)
    obs.obs_properties_add_text(props, "status", "Status", obs.OBS_TEXT_INFO)
    return props


def script_update(settings):
    apply_settings(settings)


def script_load(settings):
    apply_settings(settings)
    obs.timer_remove(on_timer)
    obs.timer_add(on_timer, POLL_MS)


def script_unload():
    for callback in (on_timer, soon):
        try:
            obs.timer_remove(callback)
        except Exception:
            pass
    stop_all()


def _self_check():
    sample = """
List of devices attached
R58TEST123         device usb:2-1 product:a14xx model:SM-A146P device:a14 transport_id:1
192.168.1.20:5555  device product:x model:Pixel_7 transport_id:2
ABCDEF             unauthorized
emulator-5554      device
"""
    devices = parse_adb_devices(sample)
    ready, waiting = usb_phones(devices)
    assert [item["serial"] for item in ready] == ["R58TEST123"]
    assert [item["serial"] for item in waiting] == ["ABCDEF"]
    assert encode_obs_field("a:b#c") == "a#3Ab#22c"
    assert window_capture_value("USB-Handy-1", "SDL_app", "scrcpy.exe") == "USB-Handy-1:SDL_app:scrcpy.exe"
    settings = Settings(True, 60, 16, 0, True, True, False, True)
    args = scrcpy_command("scrcpy", "R58TEST123", "USB-Handy-R58TEST123", 1, settings)
    assert "--serial=R58TEST123" in args
    assert "--no-audio" in args
    assert "--no-control" in args
    assert "--max-fps=60" in args
    assert command_signature(args) != tuple(args)
    assigned = {}
    assert source_name("R58TEST123", "SM-A146P", assigned, 1) == "Handy SM-A146P"
    assert source_name("R58TEST123", "SM-A146P", assigned, 2) == "Handy SM-A146P"
    assert source_name("ABCD9999", "SM-A146P", assigned, 2) == "Handy SM-A146P 9999"
    scrcpy, adb = find_tools()
    assert os.path.isfile(scrcpy)
    assert os.path.isfile(adb)
    assert find_scrcpy_window("USB-Handy-gibt-es-nicht") is None
    print("ok")
    print(scrcpy)
    print(adb)


if __name__ == "__main__":
    _self_check()
