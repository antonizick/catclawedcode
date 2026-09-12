#!/usr/bin/env python3
"""
catlock - grab a keyboard device exclusively and pass every event through
to a virtual keyboard unchanged, EXCEPT while "locked", during which all
key events from that device are swallowed. The same key combination,
held for a configurable duration, toggles between locked and unlocked.

Why a passthrough proxy instead of just disabling the device: once a
device is exclusively grabbed, the compositor (Hyprland, X11, whatever)
never sees its raw events again - only what this script re-emits on the
virtual device. That means the lock/unlock hotkey has to be recognized
here, inside this process, not as a compositor-level keybind.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import evdev
    from evdev import UInput, ecodes
except ImportError:
    sys.exit(
        "error: the 'evdev' package is required.\n"
        "       pip install -r requirements.txt"
    )

try:
    import yaml
except ImportError:
    yaml = None

REPO_DIR = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "device_name": "AT Translated Set 2 keyboard",
    "lock_keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_L"],
    "unlock_keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_L"],
    "hold_seconds": 1.5,
    "notify": True,
    "sound": True,
    "sound_file": "sounds/meow.wav",
    "log_file": None,
}

# Tried in this order; the first one found on PATH is used for the whole run.
SOUND_PLAYERS = [
    ["pw-play"],
    ["paplay"],
    ["aplay", "-q"],
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
]

log = logging.getLogger("catlock")


def load_config(path: Optional[Path]) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path is None:
        return cfg
    if not path.exists():
        log.warning("config file %s not found, using built-in defaults", path)
        return cfg
    if yaml is None:
        sys.exit("error: pyyaml is required to read a config file (pip install pyyaml)")
    with path.open() as f:
        user_cfg = yaml.safe_load(f) or {}
    cfg.update(user_cfg)
    return cfg


def resolve_keys(names: list[str]) -> set[int]:
    codes = set()
    for name in names:
        code = getattr(ecodes, name, None)
        if code is None:
            sys.exit(f"error: unknown key name '{name}' (see evdev.ecodes)")
        codes.add(code)
    return codes


def find_device(name_substring: str) -> Optional[evdev.InputDevice]:
    needle = name_substring.lower()
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if needle in dev.name.lower():
            return dev
    return None


def list_devices() -> None:
    paths = evdev.list_devices()
    if not paths:
        print(
            "No accessible input devices found. python-evdev silently skips\n"
            "devices it can't open, so this usually means your user isn't in\n"
            "the 'input' group yet (check with 'id -nG'). See the README's\n"
            "'Permissions' section, or run install.sh."
        )
        return
    print(f"{'path':<20} {'name':<40} phys")
    for path in paths:
        dev = evdev.InputDevice(path)
        print(f"{dev.path:<20} {dev.name:<40} {dev.phys}")


def notify(summary: str, body: str) -> None:
    import shutil
    import subprocess

    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.run(
            ["notify-send", "--urgency=low", "--app-name=catlock", summary, body],
            check=False,
            timeout=2,
        )
    except Exception as exc:  # notifications are best-effort, never fatal
        log.debug("notify-send failed (non-fatal): %s", exc)


def find_sound_player() -> Optional[list[str]]:
    import shutil

    for cmd in SOUND_PLAYERS:
        if shutil.which(cmd[0]) is not None:
            return cmd
    return None


def resolve_sound_path(sound_file: str) -> Path:
    p = Path(sound_file)
    return p if p.is_absolute() else (REPO_DIR / p)


def play_sound(player_cmd: list[str], sound_path: Path) -> None:
    import subprocess

    if not sound_path.exists():
        log.warning("sound file %s not found, skipping playback", sound_path)
        return
    try:
        # Fire-and-forget: never let audio playback block or delay the
        # lock/unlock toggle itself.
        subprocess.Popen(
            [*player_cmd, str(sound_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # sound is best-effort, never fatal
        log.debug("sound playback failed (non-fatal): %s", exc)


class CatLock:
    def __init__(
        self,
        device: evdev.InputDevice,
        lock_keys: set[int],
        unlock_keys: set[int],
        hold_seconds: float,
        do_notify: bool,
        sound_player: Optional[list[str]] = None,
        sound_path: Optional[Path] = None,
    ):
        self.device = device
        self.lock_keys = lock_keys
        self.unlock_keys = unlock_keys
        self.hold_seconds = hold_seconds
        self.do_notify = do_notify
        self.sound_player = sound_player
        self.sound_path = sound_path

        self.pressed: set[int] = set()
        self.locked = False
        self.combo_since: Optional[float] = None
        self.suppress_until_clear = False

        self.ui = UInput.from_device(device, name="catlock-virtual-kbd")

    def close(self) -> None:
        log.info("shutting down: releasing grab on %s and destroying virtual device", self.device.path)
        try:
            self.device.ungrab()
        except OSError as exc:
            log.warning("ungrab failed (device may already be gone): %s", exc)
        try:
            self.ui.close()
        except Exception as exc:
            log.warning("closing virtual device failed: %s", exc)

    def run(self) -> None:
        self.device.grab()
        log.info(
            "grabbed '%s' (%s) exclusively; forwarding via virtual device %s",
            self.device.name,
            self.device.path,
            self.ui.device.path,
        )
        log.info(
            "lock combo=%s unlock combo=%s hold=%.2fs",
            sorted(ecodes.KEY[c] for c in self.lock_keys),
            sorted(ecodes.KEY[c] for c in self.unlock_keys),
            self.hold_seconds,
        )
        try:
            # A plain `for event in device.read_loop()` only re-evaluates
            # anything when a new event arrives - if you hold the combo
            # perfectly still, no further key events fire and the "held
            # long enough" check never gets a chance to re-run. Polling
            # with a short timeout lets us check elapsed hold time on a
            # steady cadence regardless of whether new events show up.
            import select

            while True:
                ready, _, _ = select.select([self.device.fd], [], [], 0.1)
                if self.device.fd in ready:
                    for event in self.device.read():
                        self._handle_event(event)
                self._check_combo_timeout()
        finally:
            self.close()

    def _release_all_on_virtual_device(self) -> None:
        # Reset the virtual device's key state so nothing reads as "stuck
        # down" once we stop forwarding real events for it.
        for code in list(self.pressed):
            self.ui.write(ecodes.EV_KEY, code, 0)
        self.ui.syn()

    def _handle_event(self, event) -> None:
        if event.type == ecodes.EV_KEY and event.value in (0, 1):
            if event.value == 1:
                self.pressed.add(event.code)
            else:
                self.pressed.discard(event.code)

            target = self.unlock_keys if self.locked else self.lock_keys
            if target and target.issubset(self.pressed):
                if self.combo_since is None:
                    self.combo_since = time.monotonic()
            else:
                self.combo_since = None

            if self.suppress_until_clear and not self.pressed:
                self.suppress_until_clear = False
                log.debug("chord fully released, resuming normal forwarding")

        if self.locked or self.suppress_until_clear:
            log.debug("swallowed event while locked: %r", event)
            return

        self.ui.write_event(event)

    def _check_combo_timeout(self) -> None:
        if self.combo_since is None:
            return
        if time.monotonic() - self.combo_since >= self.hold_seconds:
            self._toggle()
            self.combo_since = None

    def _toggle(self) -> None:
        self.locked = not self.locked
        state = "LOCKED" if self.locked else "unlocked"
        reason = f"combo held for >= {self.hold_seconds:.2f}s"
        log.info("keyboard %s (%s)", state, reason)

        if self.locked:
            # Reset the virtual device so modifier/key state can't get
            # stuck "down" for the rest of the session.
            self._release_all_on_virtual_device()
            self.suppress_until_clear = False
        else:
            # Don't resume forwarding until the physical chord keys are
            # all released, so we never emit an "up" with no matching
            # "down" on the virtual device.
            self.suppress_until_clear = True

        if self.do_notify:
            notify("catlock", f"Keyboard {state.lower()}")

        if self.sound_player and self.sound_path:
            play_sound(self.sound_player, self.sound_path)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    p.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.list_devices:
        list_devices()
        return

    cfg = load_config(args.config)

    handlers = [logging.StreamHandler()]
    if cfg.get("log_file"):
        handlers.append(logging.FileHandler(cfg["log_file"]))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    log.info("starting catlock with config: %s", {k: v for k, v in cfg.items()})

    device = find_device(cfg["device_name"])
    if device is None:
        log.error(
            "no input device matched name substring '%s'. Run "
            "'python3 catlock.py --list-devices' to see available devices "
            "and update device_name in your config.",
            cfg["device_name"],
        )
        sys.exit(1)

    lock_keys = resolve_keys(cfg["lock_keys"])
    unlock_keys = resolve_keys(cfg["unlock_keys"])

    sound_player = None
    sound_path = None
    if cfg.get("sound"):
        sound_player = find_sound_player()
        sound_path = resolve_sound_path(cfg["sound_file"])
        if sound_player is None:
            log.warning(
                "sound is enabled but no player found (tried: %s); "
                "install one of pipewire, pulseaudio-utils, alsa-utils, or ffmpeg",
                ", ".join(cmd[0] for cmd in SOUND_PLAYERS),
            )
        elif not sound_path.exists():
            log.warning("sound is enabled but sound_file %s does not exist", sound_path)
        else:
            log.info("sound enabled via '%s', file=%s", sound_player[0], sound_path)

    catlock = CatLock(
        device=device,
        lock_keys=lock_keys,
        unlock_keys=unlock_keys,
        hold_seconds=float(cfg["hold_seconds"]),
        do_notify=bool(cfg["notify"]),
        sound_player=sound_player,
        sound_path=sound_path,
    )

    def _handle_signal(signum, _frame):
        log.info("received signal %s, shutting down", signal.Signals(signum).name)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        catlock.run()
    except PermissionError:
        log.error(
            "permission denied opening/grabbing %s. See the README section "
            "'Permissions' - you likely need the udev rule and/or 'input' "
            "group membership installed by install.sh.",
            device.path,
        )
        sys.exit(1)
    except SystemExit:
        pass
    except Exception:
        log.exception("catlock crashed unexpectedly")
        sys.exit(1)


if __name__ == "__main__":
    main()
