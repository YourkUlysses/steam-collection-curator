"""Validation and bounded local I/O shared by the two entry points."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

LIMIT = 64 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def appid(value):
    require(type(value) in (int, str), "Invalid AppID")
    value = str(value).strip()
    require(re.fullmatch(r"[1-9][0-9]{0,9}", value) and int(value) <= 2**32 - 1,
            "Invalid AppID")
    return int(value)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON property")
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError("Non-finite JSON number")


def decode(data):
    return json.loads(data, object_pairs_hook=unique, parse_constant=reject_constant)


def encode(data):
    return (json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def windows_reserved(part):
    if hasattr(os.path, "isreserved"):
        return os.path.isreserved(part)
    return Path(part).is_reserved()


def private_json_output(value):
    path = path_for(value, missing=True)
    parts = {part.casefold() for part in path.parts}
    require(path.suffix.casefold() == ".json" and not (parts & {"cloudstorage", "userdata", ".git"})
            and not path.name.casefold().startswith(("cloud-storage-", ".curator-", "loginusers")),
            "Use a separate private JSON output path")
    return path


def path_for(value, *, missing=False):
    path = Path(value).expanduser()
    require(".." not in path.parts, "Parent traversal is forbidden")
    path = path.absolute()
    require(os.name != "nt" or (len(path.drive) == 2 and path.drive[1] == ":"
            and all(":" not in part and not part.endswith((" ", ".")) and
                    not windows_reserved(part) for part in path.parts[1:])),
            "Invalid Windows path")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing and part == path:
                break
            raise
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Links and reparse points are forbidden")
        if part != path:
            require(stat.S_ISDIR(info.st_mode), "Invalid parent directory")
    return path


def file_info(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not getattr(info, "st_file_attributes", 0) & 0x400,
            "Expected a regular file without aliases")
    return info


def read(path):
    path = path_for(path)
    expected = file_info(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        require(os.path.samestat(expected, opened) and opened.st_nlink == 1
                and opened.st_size <= LIMIT, "Unsafe or oversized input")
        data = handle.read(LIMIT + 1)
        current = os.fstat(handle.fileno())
        require(len(data) <= LIMIT and opened.st_size == len(data)
                and current.st_mtime_ns == opened.st_mtime_ns
                and os.path.samestat(current, file_info(path_for(path))), "Input changed while reading")
    return data


def sync_dir(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def protect_windows_copy(source, destination):
    """Apply the original read/write policy before filling a private copy."""
    system = ctypes.WinDLL("advapi32", use_last_error=True)
    size = ctypes.c_ulong()
    flags = 4  # DACL_SECURITY_INFORMATION
    system.GetFileSecurityW(str(source), flags, None, 0, ctypes.byref(size))
    if not size.value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = ctypes.create_string_buffer(size.value)
    if not system.GetFileSecurityW(str(source), flags, descriptor, size.value, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    present, defaulted = ctypes.c_int(), ctypes.c_int()
    dacl = ctypes.c_void_p()
    if not system.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl),
                                            ctypes.byref(defaulted)):
        raise ctypes.WinError(ctypes.get_last_error())
    require(present.value and dacl.value, "Source has an unrestricted Windows DACL")
    result = system.SetNamedSecurityInfoW(str(destination), 1, ctypes.c_ulong(0x80000004),
                                         None, None, dacl, None)
    if result:
        raise ctypes.WinError(result)


def stage(path, data, mode=0o600, acl_from=None):
    require(len(data) <= LIMIT, "Output is too large")
    path = path_for(path, missing=True)
    fd, filename = tempfile.mkstemp(prefix=".curator-", suffix=".tmp", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "wb") as handle:
            if os.name != "nt":
                os.fchmod(handle.fileno(), mode)
            elif acl_from is not None:
                protect_windows_copy(path_for(acl_from), path_for(temporary))
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_local(path, data, *, acl_from=None):
    path = path_for(path, missing=True)
    if path.exists():
        file_info(path)
    tmp = stage(path, data, acl_from=acl_from or (path if path.exists() else None))
    try:
        os.replace(tmp, path_for(path, missing=True))
        sync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def label(value, limit=128):
    require(isinstance(value, str), "Expected text")
    value = " ".join(value.split())
    require(0 < len(value) <= limit and not any(unicodedata.category(c).startswith("C") for c in value),
            "Invalid display text")
    return value


def label_key(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


KINDS = {"manual": r"M0[1-8]", "primary": r"[0-9]{2,4}", "series": r"S[0-9]{2,4}",
         "theme": r"T[0-9]{2,4}", "experience": r"E[0-9]{2,4}"}


def validate_plan(plan):
    require(type(plan) is dict and plan.get("schema_version") == 2, "Generate a version 2 plan")
    require(type(plan["records"]) is dict and type(plan["collections"]) is list, "Invalid plan")
    groups, names = {}, set()
    for group in plan["collections"]:
        code, kind, name = group["id"], group["kind"], label(group["label"])
        require(kind in KINDS and re.fullmatch(KINDS[kind], code) and code not in groups
                and name == group["label"] and label_key(name) not in names, "Invalid collection definition")
        if kind == "manual":
            require(name.startswith(f"00-{code[1:]} "), "Invalid manual collection prefix")
        require(type(group["members"]) is list, "Invalid members")
        groups[code] = group
        names.add(label_key(name))
    expected = {code: set() for code in groups}
    pending = []
    for key, record in plan["records"].items():
        aid = appid(key)
        require(key == str(aid) and type(record["review"]) is bool and type(record["extra"]) is list,
                "Invalid classification record")
        primary = record["primary"]
        require((primary is None and record["review"]) or
                (primary in groups and groups[primary]["kind"] == "primary"), "Invalid primary")
        extras = record["extra"]
        require(len(set(extras)) == len(extras) and all(c in groups and groups[c]["kind"] in
                {"series", "theme", "experience"} for c in extras), "Invalid overlay")
        if record["review"]:
            pending.append(aid)
        else:
            for code in [primary, *extras]:
                expected[code].add(aid)
    require(type(plan["review_queue"]) is list and sorted(pending) ==
            sorted(appid(a) for a in plan["review_queue"]), "Review queue mismatch")
    for code, group in groups.items():
        members = [appid(a) for a in group["members"]]
        require(len(members) == len(set(members)) and set(members) == expected[code],
                "Membership does not match confirmed records")
    return groups
