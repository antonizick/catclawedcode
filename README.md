# catclawedcode / CatLock

A cat-proof keyboard lock for Linux. Hit a hotkey combo when you see the
cat coming, and your keyboard stops sending anything to the OS - no
accidental keystrokes, no unsaved-work chaos, no cat-typed Slack messages
- while your screen, mouse/trackpad, and everything else keep working
normally. Hold the same combo again to unlock.

## How it works

CatLock exclusively "grabs" one physical keyboard device at the kernel
input (evdev) level and re-emits every event, unchanged, on a virtual
keyboard device it creates with `uinput`. That virtual device is what
your compositor/desktop actually sees, so from the OS's point of view
nothing changes.

While **unlocked**, every keystroke is forwarded through immediately -
you shouldn't notice CatLock is running at all.

When you hold the configured key combo for a set duration (default:
1.5s), CatLock stops forwarding events from that device. Cat walks,
sits, or naps on the keyboard: nothing gets through. Holding the same
combo again for the same duration resumes forwarding.

Because the grab happens *before* your compositor ever sees the raw
device, the hotkey has to be recognized by CatLock itself - it cannot be
a normal Hyprland/window-manager keybind on that keyboard, since Hyprland
only ever sees the virtual passthrough device once CatLock is running.

This is the same general technique used by key remappers like `keyd` and
`interception-tools`, just scoped to one narrow job.

## Platform scope

Developed and tested on **Omarchy** (Arch Linux + Hyprland, Wayland).
The core mechanism (`python-evdev` + `uinput`) is a Linux kernel-level
facility, not a Hyprland or Wayland feature, so this should work
unmodified on other Wayland compositors, X11 desktops, and other Linux
distros with evdev/uinput support. It has **not** been tested outside
Omarchy - if you try it elsewhere, please open an issue with what did or
didn't work.

This will **not** work on macOS or Windows; it depends on Linux's
`/dev/input` and `/dev/uinput` interfaces.

## Before you trust this daemon

Read this before relying on CatLock to protect real work:

- **This has the same capabilities as a keylogger / input-injection
  tool.** Grabbing a raw input device and creating a virtual one are
  exactly the primitives a malicious keylogger would use. Read
  `catlock.py` yourself before running it - it's a few hundred lines by
  design, so that this is realistic to do.
- **A bug or crash could leave the keyboard non-functional** until the
  process is restarted. CatLock installs signal handlers to release its
  grab cleanly on `SIGINT`/`SIGTERM`, and the provided systemd unit
  restarts it automatically on failure - but no such handling is
  bulletproof.
- **Test extensively before you rely on it.** Toggle lock/unlock
  dozens of times, with different held-down durations, before trusting
  it during real work. Keep an external USB keyboard, or SSH access from
  another machine, available the first several days in case you need to
  `pkill -f catlock.py` to get your keyboard back. (Your mouse/trackpad
  alone won't get you out of a stuck lock - you need another keyboard or
  a remote shell.)
- **Match `device_name` carefully.** It's a case-insensitive substring
  match against the device name reported by
  `python3 catlock.py --list-devices`. Make sure it matches only your
  intended internal keyboard, especially on a machine anyone else might
  use, or where you might plug in an external keyboard you'd forget is
  also being grabbed.
- Locking only affects the one device CatLock grabs. It has no effect on
  screen lock, power button, or anything else - by design, so the screen
  stays alive and you can keep watching whatever's running.

## Requirements

- Linux with `/dev/input` and `/dev/uinput` (standard on any modern
  distro)
- Python 3.9+
- Python packages: `evdev`, `PyYAML` (see `requirements.txt`)
- `notify-send` (optional, for lock/unlock desktop notifications)

## Installation

```sh
cd catclawedcode
./install.sh
```

The installer is interactive and asks before every step that needs
`sudo` or touches system config. It will:

1. Install `evdev`/`PyYAML` - via `pacman -S python-evdev python-yaml` on
   Arch/Omarchy (both are in the official `extra` repo, avoiding pip and
   Arch's PEP-668 "externally managed" restriction entirely), or via
   `pip install --user` elsewhere
2. Copy `config.example.yaml` to `config.yaml` if you don't have one yet
3. Optionally install a udev rule granting your user's `input` group
   access to `/dev/uinput`, so CatLock doesn't need to run as root
4. Optionally add you to the `input` group (needed for `/dev/input`
   read access) - **requires logging out and back in** to take effect
5. Optionally install (but not enable) a systemd `--user` service

### Manual installation

If you'd rather do it by hand or the installer doesn't fit your setup:

```sh
# Arch/Omarchy:
sudo pacman -S python-evdev python-yaml
# Elsewhere (or if you'd rather not touch system packages at all):
#   python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
#   (then run everything below with ./.venv/bin/python instead of python3,
#   and update ExecStart in systemd/catlock.service accordingly)

cp config.example.yaml config.yaml

# find your keyboard's device name
python3 catlock.py --list-devices
# edit config.yaml: set device_name to match

# uinput permissions, so you don't need root
sudo cp udev/99-catlock-uinput.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG input "$USER"   # then log out and back in

# test it by hand first
python3 catlock.py --config config.yaml -v
```

### Permissions

CatLock needs:

- Read access to the specific `/dev/input/eventX` node for your
  keyboard - normally granted to the `input` group by distro-default
  udev rules.
- Read/write access to `/dev/uinput` - not granted by group membership
  by default; the provided udev rule (`udev/99-catlock-uinput.rules`)
  fixes that for the `input` group.

If you'd rather not touch udev/group config at all, you can instead run
CatLock as root (e.g. a system-level systemd unit with `User=root`), but
group-based permissions are preferred: it's the same privilege scope
CatLock actually needs, no more.

## Configuration

Copy `config.example.yaml` to `config.yaml` and edit:

| Key            | Meaning                                                            |
|----------------|---------------------------------------------------------------------|
| `device_name`  | Case-insensitive substring match against the keyboard's evdev name |
| `lock_keys`    | List of `evdev.ecodes` `KEY_*` names, all held together, to lock   |
| `unlock_keys`  | Same, to unlock (defaults to the same combo as `lock_keys`)        |
| `hold_seconds` | How long the combo must be held before it triggers                 |
| `notify`       | Send a desktop notification via `notify-send` on lock/unlock       |
| `log_file`     | Optional extra log file path, besides stdout                       |

Find your keyboard's device name with:

```sh
python3 catlock.py --list-devices
```

## Running

By hand, in a terminal, with verbose logging while you test:

```sh
python3 catlock.py --config config.yaml -v
```

Hold your configured combo for `hold_seconds` to lock; hold it again to
unlock. Watch the log output to confirm each toggle and its reason.

### Running as a service

Once you've tested manually and are confident in your config:

```sh
systemctl --user enable --now catlock.service
journalctl --user -u catlock.service -f   # watch logs
```

`install.sh` copies `systemd/catlock.service` into
`~/.config/systemd/user/` with the correct absolute paths filled in, but
does not enable or start it for you - that's a deliberate manual step
once you trust your setup.

To stop relying on it entirely:

```sh
systemctl --user disable --now catlock.service
```

## Optional: status indicator (Waybar, etc.)

CatLock logs every lock/unlock with a timestamp and reason via the
standard `logging` module (journal, stdout, and/or `log_file`). If you
want a live on-screen indicator (e.g. in Waybar) rather than relying on
the notification, the simplest approach is to have your own small
wrapper script `tail -f` the log for the most recent `LOCKED`/`unlocked`
line and expose that as a Waybar custom module. This isn't bundled here
to keep the core tool minimal - happy to take a PR that adds a state
file if that's useful to you.

## Troubleshooting

- **`--list-devices` doesn't show my keyboard** - make sure you're in
  the `input` group (`id -nG`) and have logged out/in since being added.
- **`PermissionError` on startup** - see the "Permissions" section
  above; you likely need the udev rule and/or `input` group membership.
- **Keyboard seems stuck locked** - from another device or SSH session,
  run `pkill -f catlock.py`; CatLock's exit handler releases its grab.
  If it was killed with `SIGKILL` (`-9`) instead of a normal signal, the
  grab may need `sudo fuser -k /dev/input/eventX` or a reboot as a last
  resort - this is why testing thoroughly before relying on it matters.
- **Modifier keys seem stuck after toggling** - please open an issue
  with your config and the `-v` log output around the toggle; this is
  exactly the class of bug the "release all keys on lock" / "wait for
  clean release on unlock" logic in `catlock.py` is meant to prevent.

## License

MIT - see `LICENSE`.
