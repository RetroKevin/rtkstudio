"""Shared .def / .tbl / .txt helpers for viewer studios.

GameData files are often PyroTechnix-gzipped. All writes go through the
mod override layer; this module only parses and rewrites text in memory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pyro_inflate

FIELD_RE = re.compile(r"^([A-Za-z_][\w]*)\s*:\s*(.*)$")
HEADER_RE = re.compile(
    r"^(Scene|SceneDef|View|GroupDef|CombatDef|TouchPlateDef|"
    r"PressurePlateDef|ConversationDef|CharacterDef|LightInst|"
    r"Shop|CTrackGroup|CStrikeDefGroup)\s+(.+?)\s*$",
    re.I,
)
IMPLICIT = {
    "formation", "members", "groups", "inventoryitems", "spellitems",
    "storeitems", "groupmemberconversationlinks", "timelineplaysoundevents",
}
BEGIN = {"begin"}
END = {"end"}


def inflate_text(raw: bytes) -> str:
    if raw.startswith(pyro_inflate.SIG):
        raw = pyro_inflate.inflate(raw)
    return raw.decode("latin-1")


def encode_text(text: str) -> bytes:
    return text.encode("latin-1")


def floats(s) -> list:
    out = []
    for part in re.split(r"[,\s]+", (s or "").strip()):
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            break
    return out


def name_index(db) -> dict:
    """basename.lower() -> [asset keys]."""
    by = {}
    for a in db.assets:
        name = Path(a.name).name.lower()
        by.setdefault(name, []).append(a.key)
    return by


def find_name(index: dict, name: str):
    keys = index.get(name.lower())
    return keys[0] if keys else None


def find_suffix(db, suffix: str):
    suffix = suffix.replace("\\", "/").lower()
    for a in db.assets:
        if a.key.replace("\\", "/").lower().endswith(suffix):
            return a.key
    return None


class Block:
    __slots__ = ("kind", "name", "fields", "children", "sections",
                 "script", "start", "end", "lines")

    def __init__(self, kind, name, start=0):
        self.kind = kind
        self.name = name
        self.fields = {}
        self.children = []
        self.sections = {}
        self.script = ""
        self.start = start
        self.end = start
        self.lines = []

    def field(self, key, default=""):
        for k, v in self.fields.items():
            if k.lower() == key.lower():
                return v
        return default

    def walk(self, kind=None):
        if kind is None or self.kind.lower() == kind.lower():
            yield self
        for c in self.children:
            yield from c.walk(kind)

    def as_dict(self):
        return {
            "kind": self.kind,
            "name": self.name,
            "fields": dict(self.fields),
            "children": [c.as_dict() for c in self.children],
            "sections": {k: list(v) for k, v in self.sections.items()},
            "script": self.script,
        }


def parse_document(text: str) -> Block:
    lines = text.splitlines()
    root = Block("Document", "", 0)
    i = 0
    n = len(lines)

    def peek_stripped(j):
        while j < n and not lines[j].strip():
            j += 1
        return (lines[j].strip() if j < n else ""), j

    def parse_block(kind, name, start, implicit=False):
        block = Block(kind, name, start)
        i = start
        in_script = False
        script = []
        item_depth = 0
        while i < n:
            raw = lines[i]
            s = raw.strip()
            low = s.lower()
            if in_script:
                if low == "scriptcodeend":
                    in_script = False
                    block.script = "\n".join(script)
                    script = []
                else:
                    script.append(raw)
                i += 1
                continue
            if low == "scriptcodebegin":
                in_script = True
                i += 1
                continue
            if low in BEGIN and not implicit:
                i += 1
                continue
            if low in END:
                if implicit and item_depth:
                    item_depth -= 1
                    block.lines.append(s)
                    i += 1
                    continue
                block.end = i
                return block, i + 1
            if implicit and low == "item":
                item_depth += 1
                block.lines.append(s)
                i += 1
                continue
            nxt, nj = peek_stripped(i + 1)
            hm = HEADER_RE.match(s)
            if hm and nxt.lower() in BEGIN:
                child, i = parse_block(hm.group(1), hm.group(2).strip(), nj + 1)
                block.children.append(child)
                continue
            if hm and hm.group(1).lower() in IMPLICIT:
                child, i = parse_block(hm.group(1), hm.group(2).strip(), i + 1,
                                       implicit=True)
                block.children.append(child)
                continue
            word = s.split(None, 1)[0] if s else ""
            if word.lower() in IMPLICIT and (nxt.lower() in BEGIN or
                                             ":" not in s or
                                             nxt.lower() not in BEGIN):
                rest = s[len(word):].lstrip(" :")
                child, i = parse_block(word, rest, i + 1, implicit=True)
                block.children.append(child)
                block.sections.setdefault(word.lower(), []).extend(child.lines)
                continue
            fm = FIELD_RE.match(s)
            if fm:
                key, val = fm.group(1), fm.group(2).rstrip()
                # Formation-style: next lines are member rows until end.
                if key.lower() == "formation":
                    child, i = parse_block("Formation", val, i + 1, implicit=True)
                    block.children.append(child)
                    continue
                if implicit:
                    block.lines.append(s)
                    i += 1
                    continue
                if key.lower() not in block.fields:
                    block.fields[key] = val
                else:
                    block.fields[key] = block.fields[key] + "\n" + val
                i += 1
                continue
            if s:
                block.lines.append(s)
            i += 1
        block.end = n
        if script:
            block.script = "\n".join(script)
        return block, i

    while i < n:
        s = lines[i].strip()
        nxt, nj = peek_stripped(i + 1)
        hm = HEADER_RE.match(s)
        if hm:
            child, i = parse_block(
                hm.group(1), hm.group(2).strip(),
                (nj + 1) if nxt.lower() in BEGIN else i + 1,
                implicit=nxt.lower() not in BEGIN)
            root.children.append(child)
            continue
        i += 1
    root.end = n
    return root


def _header_match(line, kind, name):
    return re.match(
        r"^\s*%s\s+%s\s*$" % (re.escape(kind), re.escape(name)), line, re.I)


def replace_field(text: str, kind: str, name: str, field: str, value: str,
                  parent_kind: str = None, parent_name: str = None) -> str:
    """Replace `Field : ...` inside the first matching block. Preserves indent.

    When parent_kind/parent_name are set, only a block nested inside that
    parent is eligible — View Vw1 is repeated in every Scene of Loc_All.def.
    """
    lines = text.splitlines()
    in_parent = parent_kind is None
    parent_depth = 0
    in_block = False
    depth = 0
    out = []
    replaced = False
    field_re = re.compile(r"^(\s*)(%s)\s*:\s*.*$" % re.escape(field), re.I)
    for line in lines:
        s = line.strip()
        if parent_kind and not in_parent and _header_match(line, parent_kind, parent_name):
            in_parent = True
            parent_depth = 0
            out.append(line)
            continue
        if in_parent and parent_kind and not in_block:
            if s.lower() in BEGIN:
                parent_depth += 1
            elif s.lower() in END:
                if parent_depth <= 1:
                    in_parent = False
                    out.append(line)
                    continue
                parent_depth -= 1
        if in_parent and not in_block and _header_match(line, kind, name):
            in_block = True
            depth = 0
            out.append(line)
            continue
        if in_block:
            if s.lower() in BEGIN:
                depth += 1
            elif s.lower() in END:
                if depth <= 1:
                    if not replaced:
                        indent = re.match(r"^(\s*)", line).group(1) + "    "
                        out.append("%s%s : %s" % (indent, field, value))
                        replaced = True
                    in_block = False
                    out.append(line)
                    continue
                depth -= 1
            if not replaced and field_re.match(line):
                indent = re.match(r"^(\s*)", line).group(1)
                out.append("%s%s : %s" % (indent, field, value))
                replaced = True
                continue
        out.append(line)
    if not replaced:
        where = "%s %s" % (kind, name)
        if parent_kind:
            where = "%s %s / %s" % (parent_kind, parent_name, where)
        raise ValueError("no %s / %s field" % (where, field))
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def replace_section(text: str, kind: str, name: str, section: str,
                    body_lines: list) -> str:
    """Replace the body of an implicit section (InventoryItems, StoreItems)."""
    lines = text.splitlines()
    in_block = False
    in_section = False
    depth = 0
    out = []
    done = False
    header_re = re.compile(r"^(\s*)(%s)\s+%s\s*$" % (
        re.escape(kind), re.escape(name)), re.I)
    for line in lines:
        s = line.strip()
        if not in_block and header_re.match(line):
            in_block = True
            depth = 0
            out.append(line)
            continue
        if in_block and not in_section and not done:
            if s.lower() == section.lower():
                in_section = True
                indent = re.match(r"^(\s*)", line).group(1)
                out.append(line)
                for row in body_lines:
                    out.append(indent + "  " + row)
                continue
        if in_section:
            if s.lower() in END:
                in_section = False
                done = True
                out.append(line)
                continue
            # skip old section body
            continue
        if in_block:
            if s.lower() in BEGIN:
                depth += 1
            elif s.lower() in END:
                if depth <= 1:
                    in_block = False
                else:
                    depth -= 1
        out.append(line)
    if not done:
        raise ValueError("no %s %s / %s section" % (kind, name, section))
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


TELEPORT_RE = re.compile(
    r"Teleport\s*\(\s*(\d+)\s*,\s*(\d+)(\s*,\s*(TRUE|FALSE))?\s*\)",
    re.I,
)
CONV_GET_RE = re.compile(r'GetConversation\s*\(\s*"([^"]+)"\s*\)', re.I)
DOOR_NAME_RE = re.compile(r"(door|exit)", re.I)


def teleports(script: str) -> list:
    found = []
    for m in TELEPORT_RE.finditer(script or ""):
        found.append({
            "scene": int(m.group(1)),
            "view": int(m.group(2)),
            "fade": (m.group(4) or "").upper() == "TRUE",
        })
    return found


def conversation_names(script: str, dest_field: str = "") -> list:
    names = []
    for m in CONV_GET_RE.finditer(script or ""):
        names.append(m.group(1))
    for part in re.split(r"[,\s]+", dest_field or ""):
        if part:
            names.append(part)
    return names


def looks_like_door(name: str) -> bool:
    return bool(DOOR_NAME_RE.search(name or ""))


def _fmt_num(n):
    v = float(n)
    if abs(v - round(v)) < 1e-6:
        return "%d.000000" % int(round(v))
    return "%.6f" % v


def format_xyz_list(pts) -> str:
    parts = []
    for p in pts or []:
        for x in list(p)[:3]:
            parts.append(_fmt_num(x))
    return ", ".join(parts)


def format_teleport(scene, view, fade=False) -> str:
    if fade:
        return "Teleport (%d, %d, TRUE)" % (int(scene), int(view))
    return "Teleport (%d, %d)" % (int(scene), int(view))


def _block_span(lines, kind, name, parent_kind=None, parent_name=None):
    """Return (header_index, end_index inclusive) for a named block."""
    in_parent = parent_kind is None
    parent_depth = 0
    in_block = False
    depth = 0
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if parent_kind and not in_parent and _header_match(line, parent_kind, parent_name):
            in_parent = True
            parent_depth = 0
            continue
        if in_parent and parent_kind and not in_block:
            if s.lower() in BEGIN:
                parent_depth += 1
            elif s.lower() in END:
                if parent_depth <= 1:
                    in_parent = False
                    continue
                parent_depth -= 1
        if in_parent and not in_block and _header_match(line, kind, name):
            in_block = True
            depth = 0
            start = i
            continue
        if in_block:
            if s.lower() in BEGIN:
                depth += 1
            elif s.lower() in END:
                if depth <= 1:
                    return start, i
                depth -= 1
    raise ValueError("no %s %s block" % (kind, name))


def replace_teleport(text: str, kind: str, name: str, index: int,
                     scene: int, view: int, fade=None,
                     parent_kind: str = None, parent_name: str = None) -> str:
    """Rewrite the Nth Teleport(...) inside a named block's script."""
    lines = text.splitlines()
    start, end = _block_span(lines, kind, name, parent_kind, parent_name)
    body = "\n".join(lines[start:end + 1])
    matches = list(TELEPORT_RE.finditer(body))
    if not matches:
        raise ValueError("no Teleport in %s %s" % (kind, name))
    if index < 0 or index >= len(matches):
        raise ValueError("Teleport index %d out of %d" % (index, len(matches)))
    m = matches[index]
    keep_fade = matches[index].group(4) if fade is None else ("TRUE" if fade else None)
    repl = format_teleport(scene, view, bool(keep_fade and str(keep_fade).upper() == "TRUE"))
    body = body[:m.start()] + repl + body[m.end():]
    new_block = body.splitlines()
    out = lines[:start] + new_block + lines[end + 1:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def add_teleport(text: str, kind: str, name: str, scene: int, view: int,
                 fade=False, parent_kind: str = None, parent_name: str = None) -> str:
    """Insert a Teleport into OnTrigger, or create that event if missing."""
    lines = text.splitlines()
    start, end = _block_span(lines, kind, name, parent_kind, parent_name)
    body_lines = lines[start:end + 1]
    body = "\n".join(body_lines)
    if TELEPORT_RE.search(body):
        return replace_teleport(text, kind, name, 0, scene, view, fade,
                                parent_kind, parent_name)
    call = "                	%s;" % format_teleport(scene, view, fade)
    event = [
        "                Event OnTrigger ()",
        "                {",
        call,
        "                }",
        "                <EndEvent>",
    ]
    inserted = False
    out_block = []
    for line in body_lines:
        if (not inserted) and line.strip() == "}" and "BasedOn" not in line:
            indent = re.match(r"^(\s*)", line).group(1)
            for ev in event:
                out_block.append(ev)
            inserted = True
        out_block.append(line)
    if not inserted:
        # Fall back: inject just before ScriptCodeEnd.
        out_block = []
        for line in body_lines:
            if (not inserted) and line.strip().lower() == "scriptcodeend":
                out_block.extend([
                    "            ScriptCodeBegin",
                    "            Object %s BasedOn basedOnNameGoesHere" % name,
                    "            {",
                    "                Properties",
                    "                EndProperties",
                ])
                out_block.extend(event)
                out_block.append("            }")
                inserted = True
            out_block.append(line)
    if not inserted:
        raise ValueError("could not insert Teleport into %s %s" % (kind, name))
    out = lines[:start] + out_block + lines[end + 1:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def replace_formation_xyz(text: str, group: str, formation: str, member: str,
                          xyz) -> str:
    """Rewrite one Formation member row inside a GroupDef."""
    lines = text.splitlines()
    in_group = False
    in_form = False
    gdepth = 0
    out = []
    done = False
    g_re = re.compile(r"^\s*GroupDef\s+%s\s*$" % re.escape(group), re.I)
    f_re = re.compile(r"^\s*Formation\s*:\s*%s\s*$" % re.escape(formation), re.I)
    m_re = re.compile(r"^(\s*)(%s)\s*:\s*.*$" % re.escape(member), re.I)
    vals = list(xyz) + [0, 0, 0, 0]
    row = "%s, %s, %s, %s" % (
        _fmt_num(vals[0]), _fmt_num(vals[1]), _fmt_num(vals[2]), _fmt_num(vals[3]))
    for line in lines:
        s = line.strip()
        if not in_group and g_re.match(line):
            in_group = True
            gdepth = 0
            out.append(line)
            continue
        if in_group and not in_form and not done and f_re.match(line):
            in_form = True
            out.append(line)
            continue
        if in_form:
            if s.lower() in END:
                in_form = False
                out.append(line)
                continue
            mm = m_re.match(line)
            if mm and not done:
                out.append("%s%s : %s" % (mm.group(1), member, row))
                done = True
                continue
        if in_group:
            if s.lower() in BEGIN:
                gdepth += 1
            elif s.lower() in END:
                if gdepth <= 1:
                    in_group = False
                else:
                    gdepth -= 1
        out.append(line)
    if not done:
        raise ValueError("no GroupDef %s / Formation %s / %s" % (
            group, formation, member))
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
