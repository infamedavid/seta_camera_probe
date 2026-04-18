#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CommandResult:
    name: str
    command: List[str]
    returncode: int
    duration_sec: float
    stdout_file: Optional[str]
    stderr_file: Optional[str]
    ok: bool
    error_category: Optional[str] = None
    error_details: Optional[List[str]] = None
    note: str = ""


ERROR_PATTERNS: List[Tuple[str, str]] = [
    (r"Could not claim the USB device", "USB_CLAIM_FAILED"),
    (r"Device or resource busy", "DEVICE_BUSY"),
    (r"PTP I/O error", "PTP_IO_ERROR"),
    (r"I/O problem", "IO_PROBLEM"),
    (r"No camera found", "NO_CAMERA_FOUND"),
    (r"Could not find the requested device", "REQUESTED_DEVICE_NOT_FOUND"),
    (r"Permission denied", "PERMISSION_DENIED"),
    (r"Read-only file system", "READ_ONLY"),
    (r"Unsupported operation", "UNSUPPORTED_OPERATION"),
    (r"not supported", "NOT_SUPPORTED"),
    (r"Could not lock the device", "DEVICE_LOCK_FAILED"),
    (r"Could not capture", "CAPTURE_FAILED"),
    (r"Could not set config", "SET_CONFIG_FAILED"),
    (r"Could not get config", "GET_CONFIG_FAILED"),
    (r"Could not close session", "SESSION_CLOSE_FAILED"),
    (r"Could not open session", "SESSION_OPEN_FAILED"),
    (r"Error .* initializing the camera", "CAMERA_INIT_FAILED"),
    (r"Broken pipe", "BROKEN_PIPE"),
]


CONFIG_ALIASES: Dict[str, List[str]] = {
    "iso": ["iso"],
    "shutter_speed": ["shutterspeed", "shutter speed"],
    "aperture": ["aperture", "f-number", "fnumber", "f number"],
    "image_format": ["imageformat", "image format"],
    "capture_target": ["capturetarget", "capture target"],
    "viewfinder": ["viewfinder", "eosviewfinder"],
    "movie": ["movie"],
    "output": ["output"],
    "focus_mode": ["focusmode", "focus mode"],
    "manual_focus_drive": ["manualfocusdrive", "manual focus drive"],
    "autofocus_drive": ["autofocusdrive", "autofocus drive"],
    "white_balance": ["whitebalance", "white balance"],
    "exposure_compensation": ["exposurecompensation", "exposure compensation"],
    "battery": ["batterylevel", "battery level"],
}


DRIVER_SUPPORTED_SETTING_ORDER = [
    "iso",
    "shutter_speed",
    "aperture",
    "white_balance",
    "exposure_compensation",
    "image_format",
    "capture_target",
    "focus_mode",
    "manual_focus_drive",
    "autofocus_drive",
    "battery",
]


# ============================================================
# generic helpers
# ============================================================

def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown_camera"


def quoted(cmd: List[str]) -> str:
    return " ".join(shlex.quote(x) for x in cmd)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", errors="replace")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def ensure_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"'{name}' was not found in PATH.")
    return path


def file_nonempty(path: Path, min_bytes: int = 1024) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size >= min_bytes


def ask_yes_no(question: str) -> bool:
    while True:
        answer = input(f"{question} [y/n]: ").strip().lower()
        if answer in {"y", "yes", "s", "si"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def append_command_log(log_path: Path, title: str, cmd: List[str]) -> None:
    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n[{datetime.now().isoformat()}] {title}\n")
        f.write(quoted(cmd) + "\n")


def mkdirs(base: Path) -> Dict[str, Path]:
    dirs = {
        "root": base,
        "detect": base / "detect",
        "config": base / "config",
        "captures": base / "captures",
        "preview_stills": base / "preview_stills",
        "stream": base / "stream",
        "generated": base / "generated",
        "logs": base / "logs",
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)
    return dirs


def classify_gphoto_output(stdout_text: str, stderr_text: str, returncode: int) -> Tuple[Optional[str], List[str]]:
    combined = "\n".join([stdout_text or "", stderr_text or ""])
    hits: List[str] = []

    for pattern, category in ERROR_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            hits.append(category)

    if returncode == 124 and "TIMEOUT" not in hits:
        hits.append("TIMEOUT")

    if returncode != 0 and not hits:
        hits.append("UNKNOWN_GPHOTO_ERROR")

    if not hits:
        return None, []

    unique_hits = list(dict.fromkeys(hits))
    return unique_hits[0], unique_hits


def run_command(
    name: str,
    cmd: List[str],
    logs_dir: Path,
    timeout: Optional[int] = None,
    ok_returncodes: Optional[List[int]] = None,
) -> CommandResult:
    ok_returncodes = ok_returncodes or [0]

    stdout_file = logs_dir / f"{name}.stdout.txt"
    stderr_file = logs_dir / f"{name}.stderr.txt"
    commands_log = logs_dir / "commands.log"

    append_command_log(commands_log, name, cmd)

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = time.time() - start

        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""

        write_text(stdout_file, stdout_text)
        write_text(stderr_file, stderr_text)

        error_category, error_details = classify_gphoto_output(stdout_text, stderr_text, proc.returncode)

        return CommandResult(
            name=name,
            command=cmd,
            returncode=proc.returncode,
            duration_sec=duration,
            stdout_file=str(stdout_file),
            stderr_file=str(stderr_file),
            ok=proc.returncode in ok_returncodes,
            error_category=error_category,
            error_details=error_details,
            note="",
        )

    except subprocess.TimeoutExpired as e:
        duration = time.time() - start
        stdout_text = e.stdout or ""
        stderr_text = e.stderr or ""
        if isinstance(stdout_text, bytes):
            stdout_text = stdout_text.decode("utf-8", errors="replace")
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode("utf-8", errors="replace")

        write_text(stdout_file, stdout_text)
        write_text(stderr_file, stderr_text + f"\nTIMEOUT after {timeout} seconds\n")

        return CommandResult(
            name=name,
            command=cmd,
            returncode=124,
            duration_sec=duration,
            stdout_file=str(stdout_file),
            stderr_file=str(stderr_file),
            ok=False,
            error_category="TIMEOUT",
            error_details=["TIMEOUT"],
            note=f"Timeout after {timeout} seconds",
        )

    except Exception as e:
        duration = time.time() - start
        write_text(stdout_file, "")
        write_text(stderr_file, f"EXCEPTION: {e}\n")

        return CommandResult(
            name=name,
            command=cmd,
            returncode=1,
            duration_sec=duration,
            stdout_file=str(stdout_file),
            stderr_file=str(stderr_file),
            ok=False,
            error_category="PYTHON_EXCEPTION",
            error_details=["PYTHON_EXCEPTION"],
            note=f"Exception: {e}",
        )


def get_binary_version(bin_path: str, arg: str = "--version") -> str:
    try:
        proc = subprocess.run(
            [bin_path, arg],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = (proc.stdout or proc.stderr or "").strip()
        return text.splitlines()[0] if text else ""
    except Exception:
        return ""


def parse_auto_detect(text: str) -> List[Dict[str, str]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    devices = []

    for line in lines:
        if line.lower().startswith("model"):
            continue
        if set(line.strip()) == {"-"}:
            continue

        m = re.match(r"^(.*?)\s{2,}(usb:\S+|serial:\S+)\s*$", line)
        if m:
            devices.append({
                "model": m.group(1).strip(),
                "port": m.group(2).strip(),
            })

    return devices


def choose_device_interactively(devices: List[Dict[str, str]]) -> Dict[str, str]:
    print("\nMultiple cameras were detected:")
    for idx, dev in enumerate(devices, start=1):
        print(f"  {idx}) {dev['model']} @ {dev['port']}")

    while True:
        raw = input("Choose the number of the camera to test: ").strip()
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(devices):
                return devices[n - 1]
        print("Invalid selection.")


def make_gphoto_cmd(
    gphoto2_bin: str,
    port: Optional[str],
    args: List[str],
    debug_logfile: Optional[Path] = None,
    include_port: bool = True,
) -> List[str]:
    cmd = [gphoto2_bin]
    if include_port and port:
        cmd.extend(["--port", port])
    if debug_logfile is not None:
        cmd.extend(["--debug", "--debug-logfile", str(debug_logfile)])
    cmd.extend(args)
    return cmd


def list_config_keys(list_config_text: str) -> List[str]:
    keys = []
    for line in list_config_text.splitlines():
        line = line.strip()
        if line.startswith("/"):
            keys.append(line)
    return keys


def basename_key(path: str) -> str:
    return path.strip("/").split("/")[-1].strip().lower()


def find_alias_matches(keys: List[str]) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}

    for alias, candidates in CONFIG_ALIASES.items():
        normalized_candidates = [c.lower() for c in candidates]
        exact_matches = []
        partial_matches = []

        for key in keys:
            base = basename_key(key)
            full = key.lower()

            if base in normalized_candidates:
                exact_matches.append(key)
                continue

            for cand in normalized_candidates:
                if cand in full or cand in base:
                    partial_matches.append(key)
                    break

        preferred = exact_matches[0] if exact_matches else (partial_matches[0] if partial_matches else None)

        results[alias] = {
            "preferred": preferred,
            "exact_matches": exact_matches,
            "partial_matches": partial_matches,
        }

    return results


def slug_to_pascal(slug: str) -> str:
    parts = [p for p in safe_slug(slug).split("_") if p]
    return "".join(part.capitalize() for part in parts) or "UnknownCamera"


def display_name_to_class_name(display_name: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", display_name)
    if not tokens:
        return "UnknownCamera"

    acronyms = {"EOS", "USB", "PTP", "MJPEG", "FFPLAY", "SETA"}
    parts: List[str] = []

    for token in tokens:
        token_upper = token.upper()
        if token_upper in acronyms:
            parts.append(token_upper)
            continue

        m = re.match(r"^(\d+)([A-Za-z]+)$", token)
        if m:
            parts.append(f"{m.group(1)}{m.group(2).upper()}")
            continue

        m = re.match(r"^([A-Za-z]+)(\d+)([A-Za-z]*)$", token)
        if m:
            prefix = m.group(1).capitalize()
            suffix = m.group(3).upper()
            parts.append(f"{prefix}{m.group(2)}{suffix}")
            continue

        if token.isupper():
            parts.append(token)
        elif token.islower():
            parts.append(token.capitalize())
        else:
            parts.append(token[0].upper() + token[1:])

    return "".join(parts) or "UnknownCamera"


def shell_regex_escape(text: str) -> str:
    return re.escape(text)


# ============================================================
# user-facing helpers
# ============================================================

def print_intro() -> None:
    print()
    print("SETA camera probe")
    print("-----------------")
    print("Before starting:")
    print("  - connect the camera via USB")
    print("  - set it to photo mode")
    print("  - if possible, disable auto power-off")
    print("  - close programs that may claim the camera")
    print()
    input("Press Enter to continue...")


def try_open_path(path: Path, no_open: bool) -> Dict[str, Any]:
    result = {
        "path": str(path),
        "open_attempted": False,
        "open_success": False,
        "open_command": None,
        "open_note": "",
    }

    if no_open:
        result["open_note"] = "Automatic open disabled by --no-open."
        return result

    xdg_open = shutil.which("xdg-open")
    if not xdg_open:
        result["open_note"] = "xdg-open was not found. Open the file manually."
        return result

    result["open_attempted"] = True
    result["open_command"] = [xdg_open, str(path)]

    try:
        proc = subprocess.Popen(
            [xdg_open, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result["open_success"] = True
        result["open_note"] = f"xdg-open launched with PID {proc.pid}."
    except Exception as exc:
        result["open_note"] = f"xdg-open failed: {exc}"

    return result


def validate_preview_human(preview_file: Path, no_open: bool) -> Dict[str, Any]:
    print()
    print("Human validation for still preview")
    print(f"Preview saved at: {preview_file}")
    open_info = try_open_path(preview_file, no_open)
    if open_info["open_note"]:
        print(open_info["open_note"])
    print("Review it visually and answer.")

    saw_file = ask_yes_no("Were you able to see the preview file?")
    looks_correct = ask_yes_no("Does the preview image look correct?")
    usable_for_preview = ask_yes_no("Is it usable as a working preview?")

    return {
        "file": str(preview_file),
        "saw_file": saw_file,
        "looks_correct": looks_correct,
        "usable_for_preview": usable_for_preview,
        **open_info,
    }


def validate_captures_human(capture_files: List[Path], no_open: bool) -> Dict[str, Any]:
    print()
    print("Human validation for captures")
    print("Generated captures:")
    for path in capture_files:
        print(f"  - {path}")

    target = capture_files[0].parent if capture_files else Path(".")
    open_info = try_open_path(target, no_open)
    if open_info["open_note"]:
        print(open_info["open_note"])
    print("Review them visually and answer.")

    saw_files = ask_yes_no("Were you able to see the captures?")
    looks_correct = ask_yes_no("Do the photos look correct?")
    usable_for_capture = ask_yes_no("Are they usable for capture in SETA?")

    return {
        "files": [str(p) for p in capture_files],
        "saw_files": saw_files,
        "looks_correct": looks_correct,
        "usable_for_capture": usable_for_capture,
        **open_info,
    }


def describe_error_actions(category: Optional[str]) -> str:
    actions = {
        "USB_CLAIM_FAILED": "The system could not claim the USB device. Close apps using the camera and try again.",
        "DEVICE_BUSY": "The camera is busy. Close file managers, import tools, or related gvfs processes.",
        "PTP_IO_ERROR": "PTP communication failed. Check cable, USB port, and camera USB mode.",
        "NO_CAMERA_FOUND": "No camera was detected. Check connection, power, and USB/PTP mode.",
        "REQUESTED_DEVICE_NOT_FOUND": "The requested port no longer exists or changed. Run auto-detect again.",
        "PERMISSION_DENIED": "USB permissions are missing. Check udev or run in an environment with proper permissions.",
        "NOT_SUPPORTED": "The operation exists in gphoto2 but this model does not support it in a useful way.",
        "UNSUPPORTED_OPERATION": "The camera was detected, but it does not expose this operation.",
        "CAPTURE_FAILED": "The camera responded but capture failed. Check shooting mode, card, and battery.",
        "TIMEOUT": "The operation took too long. It may be a lockup, wrong mode, or unstable support.",
        "UNKNOWN_GPHOTO_ERROR": "gphoto2 returned a generic error. It may be a transient state or unsupported recipe.",
    }
    return actions.get(category, "")


TRANSIENT_ERROR_CATEGORIES = {
    "DEVICE_BUSY",
    "USB_CLAIM_FAILED",
    "PTP_IO_ERROR",
    "IO_PROBLEM",
    "DEVICE_LOCK_FAILED",
    "SESSION_OPEN_FAILED",
    "SESSION_CLOSE_FAILED",
    "CAMERA_INIT_FAILED",
    "BROKEN_PIPE",
    "TIMEOUT",
    "CAPTURE_FAILED",
    "UNKNOWN_GPHOTO_ERROR",
}


def is_likely_transient_error(category: Optional[str]) -> bool:
    return bool(category in TRANSIENT_ERROR_CATEGORIES)


def settle_sleep(seconds: float, reason: str = "") -> None:
    if seconds <= 0:
        return
    label = f" ({reason})" if reason else ""
    print(f"Waiting {seconds:.1f}s{label}...")
    time.sleep(seconds)


def soft_reconnect_check(gphoto2_bin: str, selected_port: Optional[str], dirs: Dict[str, Path], tag: str) -> Dict[str, Any]:
    debug_log = dirs["logs"] / f"{tag}.gphoto.debug.log"
    cmd = make_gphoto_cmd(gphoto2_bin, selected_port, ["--summary"], debug_logfile=debug_log)
    result = run_command(tag, cmd, dirs["logs"], timeout=20)
    return asdict(result)


# ============================================================
# Probe logic
# ============================================================

def run_auto_detect(gphoto2_bin: str, dirs: Dict[str, Path], report: Dict[str, Any]) -> List[Dict[str, str]]:
    cmd = [gphoto2_bin, "--auto-detect"]
    result = run_command("auto_detect", cmd, dirs["logs"], timeout=20)
    report["auto_detect"] = asdict(result)

    auto_detect_path = dirs["detect"] / "auto_detect.txt"
    shutil.copy2(result.stdout_file, auto_detect_path)

    devices = parse_auto_detect(read_text(auto_detect_path))
    report["detected_devices"] = devices
    return devices


def resolve_selected_device(
    devices: List[Dict[str, str]],
    requested_port: Optional[str],
    requested_index: Optional[int],
) -> Dict[str, str]:
    if requested_port:
        for dev in devices:
            if dev["port"] == requested_port:
                return dev
        return {"model": "manual_port", "port": requested_port}

    if requested_index is not None:
        if not devices:
            raise RuntimeError("No cameras were detected to use with --device-index.")
        if requested_index < 0 or requested_index >= len(devices):
            raise RuntimeError(f"--device-index out of range: {requested_index}")
        return devices[requested_index]

    if len(devices) == 1:
        return devices[0]

    if len(devices) > 1:
        return choose_device_interactively(devices)

    return {"model": "unknown_camera", "port": None}


def probe_device_info(
    gphoto2_bin: str,
    selected_port: Optional[str],
    dirs: Dict[str, Path],
    report: Dict[str, Any],
) -> None:
    steps = [
        ("summary", ["--summary"], 20),
        ("abilities", ["--abilities"], 20),
        ("list_config", ["--list-config"], 30),
    ]

    report["device_info_steps"] = []

    for name, args, timeout in steps:
        debug_log = dirs["logs"] / f"{name}.gphoto.debug.log"
        cmd = make_gphoto_cmd(gphoto2_bin, selected_port, args, debug_logfile=debug_log)
        result = run_command(name, cmd, dirs["logs"], timeout=timeout)
        report["device_info_steps"].append(asdict(result))

        if result.stdout_file:
            shutil.copy2(result.stdout_file, dirs["detect"] / f"{name}.txt")
        if result.stderr_file:
            shutil.copy2(result.stderr_file, dirs["detect"] / f"{name}.stderr.txt")

    list_config_text = read_text(dirs["detect"] / "list_config.txt")
    keys = list_config_keys(list_config_text)
    alias_matches = find_alias_matches(keys)

    report["config_keys_count"] = len(keys)
    report["config_alias_matches"] = alias_matches

    write_text(dirs["config"] / "all_keys.json", json.dumps(keys, indent=2, ensure_ascii=False))
    write_text(dirs["config"] / "alias_matches.json", json.dumps(alias_matches, indent=2, ensure_ascii=False))

    get_config_results = []
    for alias, info in alias_matches.items():
        preferred = info.get("preferred")
        if not preferred:
            continue

        safe_name = safe_slug(alias)
        debug_log = dirs["logs"] / f"get_config_{safe_name}.gphoto.debug.log"
        cmd = make_gphoto_cmd(
            gphoto2_bin,
            selected_port,
            ["--get-config", preferred],
            debug_logfile=debug_log,
        )
        result = run_command(f"get_config_{safe_name}", cmd, dirs["logs"], timeout=20)
        get_config_results.append({
            "alias": alias,
            "config_path": preferred,
            "result": asdict(result),
        })

        if result.stdout_file:
            shutil.copy2(result.stdout_file, dirs["config"] / f"{safe_name}.txt")
        if result.stderr_file:
            shutil.copy2(result.stderr_file, dirs["config"] / f"{safe_name}.stderr.txt")

    report["get_config_results"] = get_config_results


def test_capture_preview(
    gphoto2_bin: str,
    selected_port: Optional[str],
    dirs: Dict[str, Path],
    report: Dict[str, Any],
    no_open: bool,
) -> None:
    preview_file = dirs["preview_stills"] / "preview_01.jpg"
    debug_log = dirs["logs"] / "capture_preview.gphoto.debug.log"
    cmd = make_gphoto_cmd(
        gphoto2_bin,
        selected_port,
        ["--capture-preview", "--filename", str(preview_file)],
        debug_logfile=debug_log,
    )

    result = run_command("capture_preview", cmd, dirs["logs"], timeout=30)
    ok_file = file_nonempty(preview_file, min_bytes=1024)
    result.ok = result.ok and ok_file

    if not preview_file.exists():
        result.note = "No preview file was generated."
    elif not ok_file:
        result.note = "Preview generated but empty or too small."
    else:
        result.note = "Preview OK."

    data = asdict(result)
    data["output_file"] = str(preview_file)
    data["output_exists"] = preview_file.exists()
    data["output_size"] = preview_file.stat().st_size if preview_file.exists() else 0
    data["suggested_action"] = describe_error_actions(result.error_category)

    human_validation = None
    if preview_file.exists():
        human_validation = validate_preview_human(preview_file, no_open)

    data["human_validation"] = human_validation
    report["preview_test"] = data


def test_capture_images(
    gphoto2_bin: str,
    selected_port: Optional[str],
    dirs: Dict[str, Path],
    report: Dict[str, Any],
    no_open: bool,
    capture_retries: int,
    settle_seconds: float,
    retry_delay_seconds: float,
) -> None:
    results = []
    capture_files: List[Path] = []
    rerun_recommended = False

    for i in range(1, 3):
        shot_file = dirs["captures"] / f"shot_{i:02d}.jpg"
        attempt_results: List[Dict[str, Any]] = []
        recovered_after_retry = False
        final_result: Optional[CommandResult] = None
        success = False

        for attempt_no in range(1, capture_retries + 1):
            if attempt_no > 1:
                settle_sleep(retry_delay_seconds, f"capture {i} retry attempt {attempt_no}")
                reconnect_info = soft_reconnect_check(
                    gphoto2_bin,
                    selected_port,
                    dirs,
                    f"capture_image_{i:02d}_reconnect_{attempt_no:02d}",
                )
                attempt_results.append({
                    "kind": "soft_reconnect",
                    "attempt": attempt_no,
                    "result": reconnect_info,
                })
                settle_sleep(settle_seconds, "settling after summary")

            debug_log = dirs["logs"] / f"capture_image_{i:02d}_attempt_{attempt_no:02d}.gphoto.debug.log"
            cmd = make_gphoto_cmd(
                gphoto2_bin,
                selected_port,
                [
                    "--capture-image-and-download",
                    "--filename",
                    str(shot_file),
                    "--force-overwrite",
                ],
                debug_logfile=debug_log,
            )

            result = run_command(
                f"capture_image_{i:02d}_attempt_{attempt_no:02d}",
                cmd,
                dirs["logs"],
                timeout=90,
            )
            ok_file = file_nonempty(shot_file, min_bytes=1024)
            result.ok = result.ok and ok_file
            final_result = result

            attempt_data = asdict(result)
            attempt_data["output_file"] = str(shot_file)
            attempt_data["output_exists"] = shot_file.exists()
            attempt_data["output_size"] = shot_file.stat().st_size if shot_file.exists() else 0
            attempt_data["suggested_action"] = describe_error_actions(result.error_category)
            attempt_data["likely_transient"] = is_likely_transient_error(result.error_category)
            attempt_data["attempt"] = attempt_no
            attempt_results.append({
                "kind": "capture_attempt",
                "attempt": attempt_no,
                "result": attempt_data,
            })

            if result.ok:
                success = True
                recovered_after_retry = attempt_no > 1
                if not shot_file.exists():
                    result.note = "Capture OK, but the file was not available locally."
                elif not ok_file:
                    result.note = "Capture file generated but empty or too small."
                else:
                    result.note = "Capture OK."
                    capture_files.append(shot_file)
                break

            if attempt_no < capture_retries and is_likely_transient_error(result.error_category):
                print(f"Capture {i} failed with {result.error_category or 'unknown error'}. Retrying.")
                continue
            if attempt_no < capture_retries and not is_likely_transient_error(result.error_category):
                print(f"Capture {i} failed with a non-transient error ({result.error_category or 'unknown'}). No more retries.")
                break

        if final_result is None:
            raise RuntimeError("No capture test was executed.")

        if not shot_file.exists():
            final_result.note = final_result.note or "No capture file was generated."
        elif not file_nonempty(shot_file, min_bytes=1024):
            final_result.note = final_result.note or "File generated but empty or too small."
        else:
            final_result.note = final_result.note or "Capture OK."

        data = asdict(final_result)
        data["output_file"] = str(shot_file)
        data["output_exists"] = shot_file.exists()
        data["output_size"] = shot_file.stat().st_size if shot_file.exists() else 0
        data["suggested_action"] = describe_error_actions(final_result.error_category)
        data["attempts"] = attempt_results
        data["attempt_count"] = len([x for x in attempt_results if x.get("kind") == "capture_attempt"])
        data["recovered_after_retry"] = recovered_after_retry
        data["likely_transient_failure"] = (not success) and is_likely_transient_error(final_result.error_category)
        results.append(data)

        if data["likely_transient_failure"]:
            rerun_recommended = True

        settle_sleep(settle_seconds, f"settling after capture {i}")

    human_validation = None
    if capture_files:
        human_validation = validate_captures_human(capture_files, no_open)

    report["capture_tests"] = results
    report["capture_human_validation"] = human_validation
    report["capture_retry_policy"] = {
        "capture_retries": capture_retries,
        "settle_seconds": settle_seconds,
        "retry_delay_seconds": retry_delay_seconds,
    }
    report["rerun_recommended"] = bool(report.get("rerun_recommended") or rerun_recommended)



def _config_candidates_from_alias(report: Dict[str, Any], alias: str, fallback_names: List[str]) -> List[str]:
    values: List[str] = []
    seen = set()

    for raw in fallback_names:
        if raw and raw not in seen:
            values.append(raw)
            seen.add(raw)

    alias_matches = report.get("config_alias_matches") or {}
    info = alias_matches.get(alias) or {}
    preferred = info.get("preferred")
    if preferred:
        for raw in [preferred, basename_key(preferred)]:
            if raw and raw not in seen:
                values.append(raw)
                seen.add(raw)

    return values



def build_stream_recipe_candidates(report: Dict[str, Any], movie_seconds: int) -> List[Dict[str, Any]]:
    recipes: List[Dict[str, Any]] = []
    seen = set()

    def add_recipe(name: str, description: str, pre_steps: List[List[str]], stream_args: List[str], preview_value: Optional[str] = None) -> None:
        key = (tuple(tuple(step) for step in pre_steps), tuple(stream_args), preview_value)
        if key in seen:
            return
        seen.add(key)
        recipes.append({
            "name": name,
            "description": description,
            "pre_steps": pre_steps,
            "stream_args": stream_args,
            "preview_value": preview_value,
        })

    viewfinder_candidates = _config_candidates_from_alias(report, "viewfinder", ["viewfinder", "eosviewfinder"])
    movie_candidates = _config_candidates_from_alias(report, "movie", ["movie"])

    for key in viewfinder_candidates:
        assignment = f"{key}=1"
        add_recipe(
            name=f"inline_set_config_{safe_slug(key)}",
            description=f"Inline --set-config {assignment} + --capture-movie --stdout",
            pre_steps=[],
            stream_args=["--set-config", assignment, "--capture-movie", str(movie_seconds), "--stdout"],
            preview_value=assignment,
        )
        add_recipe(
            name=f"prestep_set_config_{safe_slug(key)}",
            description=f"Pre-step --set-config {assignment}, then --capture-movie --stdout",
            pre_steps=[["--set-config", assignment]],
            stream_args=["--capture-movie", str(movie_seconds), "--stdout"],
            preview_value=assignment,
        )

    add_recipe(
        name="direct_capture_movie_stdout",
        description="Only --capture-movie --stdout",
        pre_steps=[],
        stream_args=["--capture-movie", str(movie_seconds), "--stdout"],
        preview_value=None,
    )

    for key in movie_candidates:
        assignment = f"{key}=1"
        add_recipe(
            name=f"movie_mode_prestep_{safe_slug(key)}",
            description=f"Pre-step --set-config {assignment}, then --capture-movie --stdout",
            pre_steps=[["--set-config", assignment]],
            stream_args=["--capture-movie", str(movie_seconds), "--stdout"],
            preview_value=None,
        )
        add_recipe(
            name=f"movie_mode_inline_{safe_slug(key)}",
            description=f"Inline --set-config {assignment} + --capture-movie --stdout",
            pre_steps=[],
            stream_args=["--set-config", assignment, "--capture-movie", str(movie_seconds), "--stdout"],
            preview_value=None,
        )

    return recipes



def _run_stream_recipe_once(
    recipe: Dict[str, Any],
    gphoto2_bin: str,
    ffplay_bin: str,
    selected_port: Optional[str],
    dirs: Dict[str, Path],
    movie_seconds: int,
    recipe_index: int,
) -> Dict[str, Any]:
    commands_log = dirs["logs"] / "commands.log"
    recipe_slug = f"stream_recipe_{recipe_index:02d}_{safe_slug(recipe['name'])}"
    recipe_dir = dirs["stream"] / recipe_slug
    recipe_dir.mkdir(parents=True, exist_ok=True)

    pre_step_results: List[Dict[str, Any]] = []
    for idx, pre_args in enumerate(recipe.get("pre_steps") or [], start=1):
        debug_log = dirs["logs"] / f"{recipe_slug}_pre_{idx:02d}.gphoto.debug.log"
        cmd = make_gphoto_cmd(gphoto2_bin, selected_port, pre_args, debug_logfile=debug_log)
        result = run_command(f"{recipe_slug}_pre_{idx:02d}", cmd, dirs["logs"], timeout=15)
        pre_step_results.append(asdict(result))
        if not result.ok:
            return {
                "recipe_index": recipe_index,
                "name": recipe["name"],
                "description": recipe["description"],
                "pre_steps": pre_step_results,
                "stream_command": None,
                "ffplay_command": None,
                "duration_sec": result.duration_sec,
                "ok_process": False,
                "gphoto2_returncode": result.returncode,
                "ffplay_returncode": None,
                "error_category": result.error_category,
                "error_details": result.error_details,
                "note": f"Pre-step #{idx} failed: {result.note or result.error_category or 'unknown'}",
                "suggested_action": describe_error_actions(result.error_category),
                "user_validation": {
                    "user_saw_stream": False,
                    "user_stream_good": False,
                },
                "selected": False,
                "recipe_dir": str(recipe_dir),
                "preview_value": recipe.get("preview_value"),
            }

    gp_stderr = dirs["logs"] / f"{recipe_slug}.gphoto2.stderr.txt"
    fp_stderr = dirs["logs"] / f"{recipe_slug}.ffplay.stderr.txt"
    gp_debug_log = dirs["logs"] / f"{recipe_slug}.gphoto.debug.log"

    gp_cmd = make_gphoto_cmd(gphoto2_bin, selected_port, recipe["stream_args"], debug_logfile=gp_debug_log)
    fp_cmd = [
        ffplay_bin,
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-framedrop",
        "-analyzeduration", "0",
        "-probesize", "32",
        "-sync", "video",
        "-autoexit",
        "-loglevel", "warning",
        "-i", "pipe:0",
    ]

    append_command_log(commands_log, recipe_slug, gp_cmd)
    append_command_log(commands_log, f"{recipe_slug}_ffplay", fp_cmd)

    start = time.time()
    gp_proc = None
    fp_proc = None
    ok_process = False
    note = ""
    gp_rc = None
    fp_rc = None

    try:
        with gp_stderr.open("w", encoding="utf-8", errors="replace") as gp_err,              fp_stderr.open("w", encoding="utf-8", errors="replace") as fp_err:
            gp_proc = subprocess.Popen(
                gp_cmd,
                stdout=subprocess.PIPE,
                stderr=gp_err,
            )
            fp_proc = subprocess.Popen(
                fp_cmd,
                stdin=gp_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=fp_err,
            )

            if gp_proc.stdout is not None:
                gp_proc.stdout.close()

            gp_rc = gp_proc.wait(timeout=movie_seconds + 30)
            fp_rc = fp_proc.wait(timeout=movie_seconds + 30)
            ok_process = (gp_rc == 0 and fp_rc == 0)
            note = f"gphoto2 rc={gp_rc}, ffplay rc={fp_rc}"

    except subprocess.TimeoutExpired:
        note = "Timeout during stream test."
        ok_process = False
        if fp_proc and fp_proc.poll() is None:
            fp_proc.kill()
        if gp_proc and gp_proc.poll() is None:
            gp_proc.kill()

    except Exception as exc:
        note = f"Exception during stream: {exc}"
        ok_process = False
        if fp_proc and fp_proc.poll() is None:
            fp_proc.kill()
        if gp_proc and gp_proc.poll() is None:
            gp_proc.kill()

    duration = time.time() - start
    gp_err_text = read_text(gp_stderr)
    error_category, error_details = classify_gphoto_output("", gp_err_text, gp_rc if gp_rc is not None else 1)

    print()
    print(f"Stream recipe {recipe_index}: {recipe['description']}")
    print("Stream test finished.")
    user_saw_stream = ask_yes_no("Did you see live preview in the ffplay window?")
    user_stream_good = ask_yes_no("Did it look usable for onion skin?")

    return {
        "recipe_index": recipe_index,
        "name": recipe["name"],
        "description": recipe["description"],
        "pre_steps": pre_step_results,
        "stream_command": gp_cmd,
        "ffplay_command": fp_cmd,
        "gphoto2_stderr_file": str(gp_stderr),
        "ffplay_stderr_file": str(fp_stderr),
        "gphoto2_debug_log": str(gp_debug_log),
        "duration_sec": duration,
        "ok_process": ok_process,
        "gphoto2_returncode": gp_rc,
        "ffplay_returncode": fp_rc,
        "error_category": error_category,
        "error_details": error_details,
        "note": note,
        "suggested_action": describe_error_actions(error_category),
        "user_validation": {
            "user_saw_stream": user_saw_stream,
            "user_stream_good": user_stream_good,
        },
        "selected": False,
        "recipe_dir": str(recipe_dir),
        "preview_value": recipe.get("preview_value"),
    }



def test_stream_ffplay(
    gphoto2_bin: str,
    ffplay_bin: str,
    selected_port: Optional[str],
    dirs: Dict[str, Path],
    report: Dict[str, Any],
    movie_seconds: int,
    stream_recipe_retries: int,
    settle_seconds: float,
    retry_delay_seconds: float,
) -> None:
    recipes = build_stream_recipe_candidates(report, movie_seconds)
    attempted: List[Dict[str, Any]] = []
    selected_attempt: Optional[Dict[str, Any]] = None
    rerun_recommended = False

    print()
    print("Several equivalent stream recipes will be tested.")
    print(f"Duration per recipe: {movie_seconds} seconds.")

    for recipe_index, recipe in enumerate(recipes, start=1):
        print()
        print(f"[{recipe_index}/{len(recipes)}] Testing: {recipe['description']}")

        for retry_no in range(1, stream_recipe_retries + 1):
            if retry_no > 1:
                settle_sleep(retry_delay_seconds, f"stream recipe {recipe_index} retry attempt {retry_no}")
                soft_reconnect_check(
                    gphoto2_bin,
                    selected_port,
                    dirs,
                    f"stream_recipe_{recipe_index:02d}_reconnect_{retry_no:02d}",
                )
                settle_sleep(settle_seconds, "settling before stream retry")

            attempt = _run_stream_recipe_once(
                recipe=recipe,
                gphoto2_bin=gphoto2_bin,
                ffplay_bin=ffplay_bin,
                selected_port=selected_port,
                dirs=dirs,
                movie_seconds=movie_seconds,
                recipe_index=recipe_index,
            )
            attempt["retry_no"] = retry_no
            attempt["recovered_after_retry"] = False
            attempted.append(attempt)

            hv = attempt.get("user_validation") or {}
            if attempt.get("ok_process") and hv.get("user_saw_stream") and hv.get("user_stream_good"):
                attempt["selected"] = True
                attempt["recovered_after_retry"] = retry_no > 1
                selected_attempt = attempt
                break

            if retry_no < stream_recipe_retries and is_likely_transient_error(attempt.get("error_category")):
                print("The recipe failed in a potentially transient way. The same recipe will be retried.")
                continue
            break

        if selected_attempt is not None:
            break

        last_attempt = attempted[-1] if attempted else {}
        if is_likely_transient_error(last_attempt.get("error_category")):
            rerun_recommended = True
        print("This recipe was not validated. The next one will be tested if available.")
        settle_sleep(settle_seconds, "settling between stream recipes")

    validation_file = dirs["stream"] / "user_validation.json"
    selected_validation = {
        "selected_recipe": selected_attempt.get("name") if selected_attempt else None,
        "user_saw_stream": bool((selected_attempt or {}).get("user_validation", {}).get("user_saw_stream")),
        "user_stream_good": bool((selected_attempt or {}).get("user_validation", {}).get("user_stream_good")),
    }
    write_text(validation_file, json.dumps(selected_validation, indent=2, ensure_ascii=False))

    if selected_attempt is None:
        last = attempted[-1] if attempted else {}
        report["stream_test"] = {
            "recipes_attempted": attempted,
            "selected_recipe": None,
            "duration_sec": sum(x.get("duration_sec", 0.0) for x in attempted),
            "ok_process": False,
            "gphoto2_returncode": last.get("gphoto2_returncode"),
            "ffplay_returncode": last.get("ffplay_returncode"),
            "error_category": last.get("error_category"),
            "error_details": last.get("error_details"),
            "note": "No stream recipe was validated.",
            "suggested_action": last.get("suggested_action") or describe_error_actions(last.get("error_category")),
            "user_validation_file": str(validation_file),
            "user_saw_stream": False,
            "user_stream_good": False,
            "preview_value": None,
            "recipe_retry_policy": {
                "stream_recipe_retries": stream_recipe_retries,
                "settle_seconds": settle_seconds,
                "retry_delay_seconds": retry_delay_seconds,
            },
        }
        report["rerun_recommended"] = bool(report.get("rerun_recommended") or rerun_recommended)
        return

    report["stream_test"] = {
        "recipes_attempted": attempted,
        "selected_recipe": {
            "name": selected_attempt.get("name"),
            "description": selected_attempt.get("description"),
            "stream_command": selected_attempt.get("stream_command"),
            "ffplay_command": selected_attempt.get("ffplay_command"),
            "preview_value": selected_attempt.get("preview_value"),
        },
        "duration_sec": selected_attempt.get("duration_sec"),
        "ok_process": selected_attempt.get("ok_process", False),
        "gphoto2_returncode": selected_attempt.get("gphoto2_returncode"),
        "ffplay_returncode": selected_attempt.get("ffplay_returncode"),
        "error_category": selected_attempt.get("error_category"),
        "error_details": selected_attempt.get("error_details"),
        "note": selected_attempt.get("note"),
        "suggested_action": selected_attempt.get("suggested_action"),
        "user_validation_file": str(validation_file),
        "user_saw_stream": bool((selected_attempt.get("user_validation") or {}).get("user_saw_stream")),
        "user_stream_good": bool((selected_attempt.get("user_validation") or {}).get("user_stream_good")),
        "preview_value": selected_attempt.get("preview_value"),
        "recipe_retry_policy": {
            "stream_recipe_retries": stream_recipe_retries,
            "settle_seconds": settle_seconds,
            "retry_delay_seconds": retry_delay_seconds,
        },
        "recovered_after_retry": bool(selected_attempt.get("recovered_after_retry")),
    }
    report["rerun_recommended"] = bool(report.get("rerun_recommended") or rerun_recommended)


# ============================================================
# Final report / profile / driver generation
# ============================================================

def preview_human_ok(report: Dict[str, Any]) -> bool:
    hv = report.get("preview_test", {}).get("human_validation") or {}
    return bool(hv.get("saw_file") and hv.get("looks_correct") and hv.get("usable_for_preview"))


def capture_human_ok(report: Dict[str, Any]) -> bool:
    hv = report.get("capture_human_validation") or {}
    return bool(hv.get("saw_files") and hv.get("looks_correct") and hv.get("usable_for_capture"))


def stream_human_ok(report: Dict[str, Any]) -> bool:
    stream = report.get("stream_test") or {}
    return bool(stream.get("user_saw_stream") and stream.get("user_stream_good"))


def preview_technical_ok(report: Dict[str, Any]) -> bool:
    return bool(report.get("preview_test", {}).get("ok"))


def capture_technical_ok(report: Dict[str, Any]) -> bool:
    capture_tests = report.get("capture_tests", [])
    return bool(capture_tests) and all(x.get("ok") for x in capture_tests)


def stream_technical_ok(report: Dict[str, Any]) -> bool:
    return bool(report.get("stream_test", {}).get("ok_process"))


def preview_effective_ok(report: Dict[str, Any]) -> bool:
    return preview_technical_ok(report) and preview_human_ok(report)


def capture_effective_ok(report: Dict[str, Any]) -> bool:
    return capture_technical_ok(report) and capture_human_ok(report)


def stream_effective_ok(report: Dict[str, Any]) -> bool:
    return stream_technical_ok(report) and stream_human_ok(report)


def fully_usable_for_seta(report: Dict[str, Any]) -> bool:
    return bool(
        report.get("camera_detected")
        and capture_effective_ok(report)
        and stream_effective_ok(report)
    )


def collect_validated_settings(report: Dict[str, Any]) -> Dict[str, str]:
    get_results = report.get("get_config_results") or []
    success_aliases: Dict[str, str] = {}
    for entry in get_results:
        alias = entry.get("alias")
        config_path = entry.get("config_path")
        result = (entry.get("result") or {})
        if alias and config_path and result.get("ok"):
            success_aliases[alias] = config_path

    ordered: Dict[str, str] = {}
    for alias in DRIVER_SUPPORTED_SETTING_ORDER:
        if alias in success_aliases:
            ordered[alias] = success_aliases[alias]
    return ordered


def build_match_patterns(display_name: str) -> List[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", display_name)]
    if not words:
        return [r"unknown_camera"]

    brand = words[0]
    model_bits = words[1:] or words
    compact_model = r".*".join(re.escape(bit) for bit in model_bits)

    if compact_model:
        return [rf"{brand}.*{compact_model}|{compact_model}.*{brand}"]
    return [re.escape(display_name.lower())]


def derive_preview_viewfinder_value(report: Dict[str, Any]) -> Optional[str]:
    selected_recipe = (report.get("stream_test") or {}).get("selected_recipe") or {}
    preview_value = selected_recipe.get("preview_value") or (report.get("stream_test") or {}).get("preview_value")
    if preview_value:
        return preview_value

    alias_matches = report.get("config_alias_matches") or {}
    viewfinder_info = alias_matches.get("viewfinder") or {}
    preferred = viewfinder_info.get("preferred")
    if not preferred:
        return None
    base = basename_key(preferred)
    if not base:
        return None
    return f"{base}=1"


def generate_driver_profile(report: Dict[str, Any], dirs: Dict[str, Path]) -> Dict[str, Any]:
    selected = report.get("selected_device") or {}
    port = selected.get("port")

    preview_ok = preview_effective_ok(report)
    capture_ok = capture_effective_ok(report)
    stream_ok = stream_effective_ok(report)

    alias_matches = report.get("config_alias_matches", {})
    preferred_configs = {
        alias: info.get("preferred")
        for alias, info in alias_matches.items()
        if info.get("preferred")
    }

    usable_for_seta = fully_usable_for_seta(report)

    return {
        "schema": "seta.gphoto.driver_profile.v1",
        "generated_at": datetime.now().isoformat(),
        "probe_report_file": str(dirs["root"] / "report.json"),
        "camera": {
            "model": selected.get("model"),
            "port": port,
        },
        "support": {
            "capture_still": capture_ok,
            "preview_still": preview_ok,
            "preview_stream_ffplay": stream_ok,
            "preview_still_required": False,
            "usable_for_seta": usable_for_seta,
        },
        "validated_commands": {
            "capture_preview": {
                "ok": preview_ok,
                "required_for_seta": False,
                "template": ["gphoto2", "--port", port, "--capture-preview", "--filename", "{preview_file}"] if port else None,
            },
            "capture_image_and_download": {
                "ok": capture_ok,
                "template": ["gphoto2", "--port", port, "--capture-image-and-download", "--filename", "{capture_file}"] if port else None,
            },
            "capture_movie_stdout": {
                "ok": stream_ok,
                "selected_recipe": (report.get("stream_test") or {}).get("selected_recipe"),
                "attempted_recipes": (report.get("stream_test") or {}).get("recipes_attempted"),
                "template": ((report.get("stream_test") or {}).get("selected_recipe") or {}).get("stream_command"),
                "ffplay_template": ["ffplay", "-fflags", "nobuffer", "-flags", "low_delay", "-framedrop", "-analyzeduration", "0", "-probesize", "32", "-sync", "video", "-autoexit", "-loglevel", "warning", "-i", "pipe:0"],
            },
        },
        "config": {
            "preferred_paths": preferred_configs,
            "validated_setting_key_to_path": collect_validated_settings(report),
            "all_keys_count": report.get("config_keys_count", 0),
            "all_keys_file": str(dirs["config"] / "all_keys.json"),
            "alias_matches_file": str(dirs["config"] / "alias_matches.json"),
        },
        "human_validation": {
            "preview_still": report.get("preview_test", {}).get("human_validation"),
            "captures": report.get("capture_human_validation"),
            "stream": {
                "saw_stream": report.get("stream_test", {}).get("user_saw_stream"),
                "usable_for_onion_skin": report.get("stream_test", {}).get("user_stream_good"),
            },
        },
        "errors": {
            "preview_error_category": report.get("preview_test", {}).get("error_category"),
            "capture_error_categories": [x.get("error_category") for x in report.get("capture_tests", []) if x.get("error_category")],
            "stream_error_category": report.get("stream_test", {}).get("error_category"),
        },
        "notes": [
            "This file is a compatibility profile and baseline for generating a declarative driver.",
            "usable_for_seta=true requires positive human validation for capture and stream; still preview is informative and non-blocking.",
        ],
    }


def render_driver_source(report: Dict[str, Any]) -> Tuple[str, str]:
    selected = report.get("selected_device") or {}
    display_name = (selected.get("model") or "Unknown Camera").strip()
    driver_id = safe_slug(display_name)
    class_name = display_name_to_class_name(display_name)

    validated_settings = collect_validated_settings(report)
    supported_settings = list(validated_settings.keys())
    match_patterns = build_match_patterns(display_name)

    preview_viewfinder_value = None
    preview_cleanup_regex = None
    if stream_effective_ok(report):
        preview_viewfinder_value = derive_preview_viewfinder_value(report)
        if preview_viewfinder_value:
            preview_cleanup_regex = rf"gphoto2 .*--set-config {shell_regex_escape(preview_viewfinder_value)} .*--capture-movie .*--stdout"

    lines: List[str] = []
    lines.append("from ..driver_api import GPhoto2CameraDriver")
    lines.append("")
    lines.append("")
    lines.append(f"class {class_name}(GPhoto2CameraDriver):")
    lines.append(f'    DRIVER_ID = "{driver_id}"')
    lines.append(f'    DISPLAY_NAME = "{display_name}"')
    lines.append('    BACKEND = "gphoto2"')
    lines.append("    PRIORITY = 100")
    lines.append("    IS_FALLBACK = False")
    lines.append("    MATCH_PATTERNS = (")
    for pattern in match_patterns:
        lines.append(f'        r"{pattern}",')
    lines.append("    )")
    lines.append("")
    lines.append("    SETTING_KEY_TO_PATH = {")
    for key, path in validated_settings.items():
        lines.append(f'        "{key}": "{path}",')
    lines.append("    }")
    supported_settings_str = "[" + ", ".join(f'\"{key}\"' for key in supported_settings) + "]"
    lines.append(f"    SUPPORTED_SETTINGS = {supported_settings_str}")

    if preview_viewfinder_value:
        lines.append(f'    PREVIEW_VIEWFINDER_VALUE = "{preview_viewfinder_value}"')
    if preview_cleanup_regex:
        lines.append(f'    PREVIEW_CLEANUP_REGEX = r"{preview_cleanup_regex}"')

    lines.append("")
    return f"{driver_id}.py", "\n".join(lines)


def maybe_generate_driver_py(report: Dict[str, Any], dirs: Dict[str, Path]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "generated": False,
        "reason": "",
        "file": None,
        "driver_id": None,
    }

    if not fully_usable_for_seta(report):
        result["reason"] = "Driver was skipped because the camera was not validated as FULLY_USABLE_FOR_SETA (capture + stream)."
        return result

    validated_settings = collect_validated_settings(report)
    if not validated_settings:
        result["reason"] = "Driver was skipped because no settings were validated by get-config to emit SETTING_KEY_TO_PATH."
        return result

    filename, source = render_driver_source(report)
    out_path = dirs["generated"] / filename
    write_text(out_path, source)

    result["generated"] = True
    result["reason"] = "Driver generated automatically because the camera passed capture and stream with positive human validation."
    result["file"] = str(out_path)
    result["driver_id"] = safe_slug((report.get("selected_device") or {}).get("model") or "unknown_camera")
    return result


def build_summary(report: Dict[str, Any]) -> str:
    selected = report.get("selected_device") or {}
    detected = bool(report.get("camera_detected"))

    preview_tech_ok = preview_technical_ok(report)
    preview_user_ok = preview_human_ok(report)

    capture_tech_ok = capture_technical_ok(report)
    capture_user_ok = capture_human_ok(report)
    capture_ok = capture_tech_ok and capture_user_ok

    stream = report.get("stream_test", {})
    stream_tech_ok = stream_technical_ok(report)
    stream_user_ok = stream_human_ok(report)
    stream_ok = stream_tech_ok and stream_user_ok

    if detected and capture_ok and stream_ok:
        final_status = "FULLY_USABLE_FOR_SETA"
    elif detected and capture_ok and not stream_ok:
        final_status = "CAPTURE_OK_BUT_NOT_USABLE_FOR_ONION_SKIN"
    elif detected and stream_ok and not capture_ok:
        final_status = "STREAM_OK_BUT_CAPTURE_NOT_VALIDATED"
    elif detected and capture_tech_ok and not capture_user_ok:
        final_status = "CAPTURE_TECH_OK_BUT_USER_NOT_CONFIRMED"
    elif detected:
        final_status = "DETECTED_BUT_NOT_VALIDATED"
    else:
        final_status = "NO_CAMERA_DETECTED"

    lines = [
        f"Final status: {final_status}",
        f"Camera detected: {detected}",
        f"Selected camera: {selected.get('model', 'N/A')} @ {selected.get('port', 'N/A')}",
        f"Preview still technical OK: {preview_tech_ok}",
        f"Preview still human OK: {preview_user_ok}",
        "Preview still required for SETA: False",
        f"Capture technical OK: {capture_tech_ok}",
        f"Capture human OK: {capture_user_ok}",
        f"Stream technical OK: {stream_tech_ok}",
        f"Stream human OK: {stream_user_ok}",
    ]

    preview_err = report.get("preview_test", {}).get("error_category")
    if preview_err:
        lines.append(f"Preview error category: {preview_err}")
    preview_action = report.get("preview_test", {}).get("suggested_action")
    if preview_action:
        lines.append(f"Preview suggested action: {preview_action}")

    capture_errs = [x.get("error_category") for x in report.get("capture_tests", []) if x.get("error_category")]
    if capture_errs:
        lines.append(f"Capture error categories: {', '.join(dict.fromkeys(capture_errs))}")
        for err in dict.fromkeys(capture_errs):
            action = describe_error_actions(err)
            if action:
                lines.append(f"Capture suggested action ({err}): {action}")

    recovered_captures = [x for x in report.get("capture_tests", []) if x.get("recovered_after_retry")]
    if recovered_captures:
        lines.append(f"Capture recovered after retry: True ({len(recovered_captures)} shot/s)")

    stream_err = stream.get("error_category")
    if stream_err:
        lines.append(f"Stream error category: {stream_err}")
    stream_recipe = stream.get("selected_recipe") or {}
    if stream_recipe:
        lines.append(f"Stream selected recipe: {stream_recipe.get('name')} - {stream_recipe.get('description')}")
    stream_action = stream.get("suggested_action")
    if stream_action:
        lines.append(f"Stream suggested action: {stream_action}")
    if stream.get("recovered_after_retry"):
        lines.append("Stream recovered after retry: True")

    driver_output = report.get("generated_driver") or {}
    if driver_output.get("generated"):
        lines.append(f"Generated driver file: {driver_output.get('file')}")
    elif driver_output.get("reason"):
        lines.append(f"Generated driver skipped: {driver_output.get('reason')}")

    if report.get("rerun_recommended") and not fully_usable_for_seta(report):
        lines.append("Rerun recommended: Yes. There were signs of a transient failure; run the probe again from scratch.")

    return "\n".join(lines)


# ============================================================
# main
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="SETA camera probe using system gphoto2 and ffplay.")
    parser.add_argument("--movie-seconds", type=int, default=20, help="Seconds per recipe for the stream test.")
    parser.add_argument("--settle-seconds", type=float, default=2.0, help="Short pause between critical operations.")
    parser.add_argument("--retry-delay-seconds", type=float, default=6.0, help="Pause before retrying after a transient failure.")
    parser.add_argument("--capture-retries", type=int, default=3, help="Maximum number of attempts per capture.")
    parser.add_argument("--stream-recipe-retries", type=int, default=2, help="Maximum number of attempts per stream recipe.")
    parser.add_argument("--output-dir", default="probe_runs", help="Base output directory.")
    parser.add_argument("--port", default=None, help="gphoto2 port to force, for example usb:001,012")
    parser.add_argument("--device-index", type=int, default=None, help="0-based index of the detected camera to use.")
    parser.add_argument("--no-open", action="store_true", help="Do not try to open preview/captures with xdg-open.")
    args = parser.parse_args()

    report: Dict[str, Any] = {
        "tool": "seta_camera_probe",
        "version": 6,
        "started_at": datetime.now().isoformat(),
        "movie_seconds": args.movie_seconds,
        "requested_port": args.port,
        "requested_device_index": args.device_index,
        "no_open": args.no_open,
        "settle_seconds": args.settle_seconds,
        "retry_delay_seconds": args.retry_delay_seconds,
        "capture_retries": args.capture_retries,
        "stream_recipe_retries": args.stream_recipe_retries,
        "rerun_recommended": False,
    }

    try:
        gphoto2_bin = ensure_binary("gphoto2")
        ffplay_bin = ensure_binary("ffplay")
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 2

    report["system_binaries"] = {
        "gphoto2": gphoto2_bin,
        "ffplay": ffplay_bin,
        "gphoto2_version": get_binary_version(gphoto2_bin),
        "ffplay_version": get_binary_version(ffplay_bin, "-version"),
        "xdg_open": shutil.which("xdg-open"),
        "python3_version": sys.version.splitlines()[0],
    }

    session_root = Path(args.output_dir) / now_stamp()
    dirs = mkdirs(session_root)

    print(f"Output: {session_root}")
    print_intro()

    try:
        devices = run_auto_detect(gphoto2_bin, dirs, report)
        report["camera_detected"] = bool(devices)

        if devices:
            print("Detected cameras:")
            for idx, dev in enumerate(devices):
                print(f"  [{idx}] {dev['model']} @ {dev['port']}")
        else:
            print("No camera was detected by auto-detect.")

        selected_device = resolve_selected_device(devices, args.port, args.device_index)
        report["selected_device"] = selected_device

        print(f"\nUsing camera: {selected_device.get('model')} @ {selected_device.get('port')}")

        print("Reading summary / abilities / list-config...")
        probe_device_info(gphoto2_bin, selected_device.get("port"), dirs, report)

        settle_sleep(args.settle_seconds, "settling after discovery/config")

        print("Testing photo capture...")
        test_capture_images(
            gphoto2_bin,
            selected_device.get("port"),
            dirs,
            report,
            args.no_open,
            args.capture_retries,
            args.settle_seconds,
            args.retry_delay_seconds,
        )

        settle_sleep(args.settle_seconds, "settling before stream")

        print(f"Testing USB stream in ffplay with equivalent recipes, {args.movie_seconds} seconds per recipe...")
        test_stream_ffplay(
            gphoto2_bin,
            ffplay_bin,
            selected_device.get("port"),
            dirs,
            report,
            args.movie_seconds,
            args.stream_recipe_retries,
            args.settle_seconds,
            args.retry_delay_seconds,
        )

        settle_sleep(args.settle_seconds, "settling before still preview")

        print("Testing still preview...")
        test_capture_preview(gphoto2_bin, selected_device.get("port"), dirs, report, args.no_open)

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        report["interrupted"] = True

    except Exception as exc:
        print(f"Unexpected ERROR: {exc}")
        report["fatal_error"] = str(exc)

    report["generated_driver"] = maybe_generate_driver_py(report, dirs)
    report["finished_at"] = datetime.now().isoformat()
    report["summary"] = build_summary(report)

    report_path = dirs["root"] / "report.json"
    summary_path = dirs["root"] / "summary.txt"
    driver_profile_path = dirs["root"] / "driver_profile.json"

    write_text(report_path, json.dumps(report, indent=2, ensure_ascii=False))
    write_text(summary_path, report["summary"])

    driver_profile = generate_driver_profile(report, dirs)
    write_text(driver_profile_path, json.dumps(driver_profile, indent=2, ensure_ascii=False))

    print()
    print(report["summary"])
    print()
    print(f"JSON report:       {report_path}")
    print(f"Summary:           {summary_path}")
    print(f"Driver profile:    {driver_profile_path}")
    if report["generated_driver"].get("generated"):
        print(f"Driver Python:     {report['generated_driver']['file']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
