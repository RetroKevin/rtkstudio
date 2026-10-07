"""ConversationDef browser and ChapterN.def rewrite (dialog.md).

A voiced node stores MenuText / JournalText, not the spoken words. The wav
is the AudioGroup Conversation row whose name matches the node.
"""

from __future__ import annotations

import re
from pathlib import Path

import rtkdef

CHAPTERS = range(0, 11)
GAME_DEF = "rtkgame.def"
TRACKS_TBL = "conversationtracks.tbl"

FIELDS = (
    "MenuText",
    "JournalText",
    "DisableWhenPlayed",
    "AddToJournal",
    "EnterNavMode",
    "IgnoreFormations",
    "RunToFormations",
    "IgnoreOtherGroupMembersOnMoveToFormation",
    "PotentialDest",
    "PotentialCombats",
    "UseCameras",
)

EVENT_RE = re.compile(
    r"(Event|Message)\s+(\S+)\s*\(\s*\)\s*\{", re.I)
END_EVENT_RE = re.compile(r"<EndEvent>", re.I)
CONV_GET_RE = rtkdef.CONV_GET_RE
TELEPORT_RE = rtkdef.TELEPORT_RE


def classify(name: str, has_audio: bool) -> str:
    u = (name or "").upper()
    if u.endswith("ROOT"):
        return "root"
    if u.endswith("FORM"):
        return "form"
    if has_audio or u.startswith("TK"):
        return "voiced"
    return "node"


def node_id(chapter, name) -> str:
    return "%s:%s" % (chapter, name)


def split_csv(raw) -> list:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


_BLOCK_OPEN = re.compile(r"^(SceneDef|ConversationDef)\s+(\S+)", re.I)


def scene_for_convs(text: str) -> list:
    """ConversationDef name -> scene by indent (dialog.md / survey_voice)."""
    scenes = []
    scene_name = ""
    scene_indent = -1
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        opened = _BLOCK_OPEN.match(line.strip())
        if opened and opened.group(1).lower() == "scenedef":
            scene_name = opened.group(2)
            scene_indent = indent
            continue
        if opened and opened.group(1).lower() == "conversationdef":
            scene = scene_name if indent > scene_indent else ""
            scenes.append((opened.group(2), scene))
            continue
        if scene_name and indent <= scene_indent:
            head = line.strip().lower()
            if not head.startswith("end") and not head.startswith("begin"):
                scene_name = ""
                scene_indent = -1
    return scenes


def parse_events(script: str) -> list:
    events = []
    text = script or ""
    for m in EVENT_RE.finditer(text):
        kind, name = m.group(1), m.group(2)
        depth = 1
        i = m.end()
        while i < len(text) and depth:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = text[m.end():i - 1]
        rest = text[i:]
        em = END_EVENT_RE.match(rest.lstrip())
        events.append({
            "kind": "Message" if kind.lower() == "message" else "Event",
            "name": name,
            "body": _dedent_event(body),
        })
        if em:
            pass
    return events


def _dedent_event(body: str) -> str:
    lines = body.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    indents = [len(ln) - len(ln.lstrip(" \t")) for ln in lines if ln.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(ln[cut:] if len(ln) >= cut else ln for ln in lines)


def can_play_flag(events) -> str:
    ev = next((e for e in events if e["name"].lower() == "oncanplay"), None)
    if ev is None:
        return "absent"
    compact = re.sub(r"//.*?$", "", ev["body"], flags=re.M)
    compact = re.sub(r"\s+", "", compact).lower()
    if compact in ("returntrue;", "returntrue"):
        return "always"
    if compact in ("returnfalse;", "returnfalse"):
        return "never"
    return "conditional"


def parse_links(block) -> list:
    out = []
    for ch in block.children:
        if ch.kind.lower() != "groupmemberconversationlinks":
            continue
        for i, line in enumerate(ch.lines):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                if line.strip():
                    out.append({
                        "slot": str(i), "group": "", "member": "",
                        "character": "", "raw": line,
                    })
                continue
            out.append({
                "slot": parts[0],
                "group": parts[1],
                "member": parts[2],
                "character": ",".join(parts[3:]).strip(),
                "raw": line,
            })
    return out


def parse_groups(block) -> list:
    for ch in block.children:
        if ch.kind.lower() == "groups":
            return [ln.strip() for ln in ch.lines if ln.strip()]
    return []


def parse_formations(block) -> list:
    out = []
    for ch in block.children:
        if ch.kind.lower() != "formation":
            continue
        members = []
        for line in ch.lines:
            fm = rtkdef.FIELD_RE.match(line)
            if not fm:
                continue
            xyz = rtkdef.floats(fm.group(2))
            members.append({
                "name": fm.group(1),
                "xyz": xyz[:3],
                "facing": xyz[3] if len(xyz) > 3 else 0,
                "raw": (fm.group(2) or "").strip(),
            })
        out.append({"group": ch.name, "members": members})
    return out


def parse_audio_rows(text: str) -> dict:
    rows = {}
    group = None
    for raw in text.splitlines():
        s = raw.strip()
        if s.lower().startswith("audiogroup "):
            group = s.split(None, 1)[1].strip()
            continue
        if group is None:
            continue
        if s.lower() == "end" or s.lower().startswith("end ") or \
                s.lower().startswith("ctrackgroup"):
            group = None
            continue
        if not s or s.startswith("//") or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 2:
            continue
        head = parts[0]
        path = parts[1]
        if re.search(r"\.(wav|trk)\s*$", head, re.I) or "\\" in head or "/" in head:
            bits = head.rsplit(None, 1)
            if len(bits) == 2:
                head, path = bits[0], bits[1]
                parts = [head, path] + parts[1:]
        rows[head.upper()] = {
            "name": head,
            "group": group,
            "path": (path or "").replace("\\", "/"),
            "tail": parts[2:],
        }
    return rows


def parse_track_rows(text: str) -> dict:
    rows = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("//") or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 2 or not parts[0].lower().endswith(".trk"):
            continue
        stem = Path(parts[0]).stem.lower()
        rows[stem] = {
            "file": parts[0],
            "tag": parts[1] if len(parts) > 1 else "",
            "frame": parts[2] if len(parts) > 2 else "",
        }
    return rows


def _conv_span(lines, rec):
    parent = rec.get("scene") or None
    want = int(rec.get("ordinal") or 0)
    found = -1
    try:
        if parent:
            start, end = rtkdef._block_span(
                lines, "ConversationDef", rec["name"],
                parent_kind="SceneDef", parent_name=parent)
            if want <= 0:
                return start, end
    except ValueError:
        pass
    in_parent = parent is None
    parent_depth = 0
    in_block = False
    depth = 0
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if parent and not in_parent and rtkdef._header_match(
                line, "SceneDef", parent):
            in_parent = True
            parent_depth = 0
            continue
        if in_parent and parent and not in_block:
            if s.lower() in rtkdef.BEGIN:
                parent_depth += 1
            elif s.lower() in rtkdef.END:
                if parent_depth <= 1:
                    in_parent = False
                    continue
                parent_depth -= 1
        if in_parent and not in_block and rtkdef._header_match(
                line, "ConversationDef", rec["name"]):
            in_block = True
            depth = 0
            start = i
            continue
        if in_block:
            if s.lower() in rtkdef.BEGIN:
                depth += 1
            elif s.lower() in rtkdef.END:
                if depth <= 1:
                    found += 1
                    if found == want:
                        return start, i
                    in_block = False
                else:
                    depth -= 1
    return rtkdef._block_span(lines, "ConversationDef", rec["name"])


def empty_script(name: str) -> str:
    return "\n".join((
        "            Object %s BasedOn basedOnNameGoesHere" % name,
        "            {",
        "                Properties",
        "                EndProperties",
        "                Event OnCanPlay ()",
        "                {",
        "                \treturn TRUE;",
        "                }",
        "                <EndEvent>",
        "            }",
    ))


def rebuild_script(name: str, events) -> str:
    lines = [
        "            Object %s BasedOn basedOnNameGoesHere" % name,
        "            {",
        "                Properties",
        "                EndProperties",
    ]
    for ev in events or []:
        ev_name = (ev.get("name") or "").strip()
        if not ev_name:
            continue
        kind = ev.get("kind") or "Event"
        if kind.lower() == "message":
            kind = "Message"
        else:
            kind = "Event"
        lines.append("                %s %s ()" % (kind, ev_name))
        lines.append("                {")
        body = ev.get("body") or ""
        if body.strip():
            for ln in body.splitlines():
                lines.append("                \t" + ln.lstrip() if ln.strip()
                             else ln)
        lines.append("                }")
        lines.append("                <EndEvent>")
    lines.append("            }")
    return "\n".join(lines)


def format_block(name, fields, groups, links, formations, script, indent):
    inner = indent + "    "
    sec = inner + "    "
    lines = [indent + "ConversationDef " + name, indent + "begin"]
    for key in FIELDS:
        lines.append("%s%s : %s" % (inner, key, fields.get(key, "")))
    lines.append(inner + "Groups")
    for g in groups or []:
        if str(g).strip():
            lines.append(sec + str(g).strip())
    lines.append(inner + "end")
    link_rows = [ln for ln in (links or []) if (ln.get("group") or ln.get("member")
                                                or ln.get("character"))]
    lines.append("%sGroupMemberConversationLinks %d" % (inner, len(link_rows)))
    for i, ln in enumerate(link_rows):
        slot = ln.get("slot")
        if slot in (None, ""):
            slot = i
        lines.append("%s%s, %s, %s, %s" % (
            sec, slot, ln.get("group") or "", ln.get("member") or "",
            ln.get("character") or ""))
    lines.append(inner + "end")
    for form in formations or []:
        gname = (form.get("group") or "").strip()
        if not gname:
            continue
        lines.append("%sFormation : %s" % (inner, gname))
        for mem in form.get("members") or []:
            mname = (mem.get("name") or "").strip()
            if not mname:
                continue
            raw = (mem.get("raw") or "").strip()
            if not raw:
                xyz = list(mem.get("xyz") or [0, 0, 0])
                while len(xyz) < 3:
                    xyz.append(0)
                raw = "%s, %s, %s, %s" % (
                    rtkdef._fmt_num(xyz[0]), rtkdef._fmt_num(xyz[1]),
                    rtkdef._fmt_num(xyz[2]),
                    rtkdef._fmt_num(mem.get("facing") or 0))
            lines.append("%s%s : %s" % (sec, mname, raw))
        lines.append(inner + "end")
    lines.append(inner + "TimelinePlaySoundEvents")
    lines.append(inner + "end")
    lines.append(inner + "ScriptCodeBegin")
    body = (script or "").strip("\n") or empty_script(name)
    lines.extend(body.splitlines())
    lines.append(inner + "ScriptCodeEnd")
    lines.append(indent + "end")
    return lines


class DialogIndex:
    def __init__(self, app):
        self.app = app
        self.index = rtkdef.name_index(app.db)
        self.chapter_keys = {}
        self.audio = {}
        self.tracks = {}
        self.nodes = []
        self.by_id = {}
        self._load()

    def _text(self, key):
        return rtkdef.inflate_text(self.app.read(key))

    def _find_suffix(self, rel):
        if not rel:
            return None
        return rtkdef.find_suffix(self.app.db, rel.replace("\\", "/"))

    def _load(self):
        game_key = rtkdef.find_name(self.index, GAME_DEF)
        if game_key:
            self.audio = parse_audio_rows(self._text(game_key))
        track_key = rtkdef.find_name(self.index, TRACKS_TBL)
        if track_key:
            self.tracks = parse_track_rows(self._text(track_key))
        self.nodes = []
        self.by_id = {}
        self.chapter_keys = {}
        for chapter in CHAPTERS:
            fname = "chapter%d.def" % chapter
            key = rtkdef.find_name(self.index, fname)
            if not key:
                key = rtkdef.find_suffix(
                    self.app.db, "gamedata/chapter%d/chapter%d.def" % (
                        chapter, chapter))
            if not key:
                continue
            self.chapter_keys[chapter] = key
            try:
                text = self._text(key)
                doc = rtkdef.parse_document(text)
            except Exception:
                continue
            parsed = list(doc.walk("ConversationDef"))
            scanned = scene_for_convs(text)
            pairs = list(zip(parsed, scanned))
            if len(parsed) > len(scanned):
                pairs.extend((b, (b.name, "")) for b in parsed[len(scanned):])
            seen = {}
            for conv, (scan_name, scene) in pairs:
                if conv.name != scan_name:
                    scene = scene or ""
                seen_key = (conv.name.upper(), scene)
                ordinal = seen.get(seen_key, 0)
                seen[seen_key] = ordinal + 1
                rec = self._summarize(chapter, scene, key, conv, ordinal)
                self.nodes.append(rec)
                self.by_id[rec["id"]] = rec
        self._link_graph()

    def _summarize(self, chapter, scene, key, conv, ordinal=0):
        dest = split_csv(conv.field("PotentialDest"))
        audio = self.audio.get(conv.name.upper())
        events = parse_events(conv.script or "")
        role = classify(conv.name, audio is not None
                        and (audio.get("group") or "").lower() == "conversation")
        if audio and (audio.get("group") or "").lower() != "conversation":
            audio = None
        wav_key = None
        trx_key = None
        trk_key = None
        if audio and audio.get("path"):
            wav_key = self._find_suffix("audio/" + audio["path"])
            if wav_key is None:
                wav_key = self._find_suffix(audio["path"])
        stem = conv.name.lower()
        track = self.tracks.get(stem)
        if track:
            trk_key = self._find_suffix("tracks/" + Path(track["file"]).name)
        trx_key = self._find_suffix("tracks/" + stem + ".trx")
        return {
            "id": node_id(chapter, conv.name) + (
                "#%d" % ordinal if ordinal else ""),
            "ordinal": ordinal,
            "chapter": chapter,
            "scene": scene,
            "name": conv.name,
            "key": key,
            "role": role,
            "menu_text": conv.field("MenuText"),
            "journal_text": conv.field("JournalText"),
            "add_to_journal": conv.field("AddToJournal"),
            "disable_when_played": conv.field("DisableWhenPlayed"),
            "enter_nav_mode": conv.field("EnterNavMode"),
            "ignore_formations": conv.field("IgnoreFormations"),
            "run_to_formations": conv.field("RunToFormations"),
            "ignore_other_on_move": conv.field(
                "IgnoreOtherGroupMembersOnMoveToFormation"),
            "potential_dest": dest,
            "potential_combats": split_csv(conv.field("PotentialCombats")),
            "use_cameras": conv.field("UseCameras"),
            "groups": parse_groups(conv),
            "links": parse_links(conv),
            "formations": parse_formations(conv),
            "script": conv.script or "",
            "events": events,
            "on_can_play": can_play_flag(events),
            "has_on_end": any(e["name"].lower() == "onend" for e in events),
            "teleports": rtkdef.teleports(conv.script or ""),
            "plays": [m.group(1) for m in CONV_GET_RE.finditer(conv.script or "")],
            "audio": audio,
            "wav_key": wav_key,
            "trk_key": trk_key,
            "trx_key": trx_key,
            "track": track,
        }

    def _link_graph(self):
        by_chap = {}
        for rec in self.nodes:
            by_chap.setdefault(rec["chapter"], {}).setdefault(
                rec["name"].upper(), rec)
        for rec in self.nodes:
            rec["parents"] = []
        for rec in self.nodes:
            kids = []
            for dest in rec["potential_dest"]:
                hit = by_chap.get(rec["chapter"], {}).get(dest.upper())
                kids.append({
                    "name": dest,
                    "id": hit["id"] if hit else None,
                    "role": hit["role"] if hit else "",
                    "menu_text": hit["menu_text"] if hit else "",
                })
                if hit is not None:
                    hit["parents"].append({
                        "name": rec["name"],
                        "id": rec["id"],
                        "role": rec["role"],
                        "menu_text": rec["menu_text"],
                    })
            rec["children"] = kids

    def chapters(self):
        return sorted(self.chapter_keys)

    def scenes(self, chapter=None):
        rows = self.nodes
        if chapter not in (None, ""):
            rows = [n for n in rows if n["chapter"] == int(chapter)]
        return sorted({n["scene"] for n in rows if n["scene"]})

    def list(self, q="", chapter=None, scene="", role=""):
        q = (q or "").lower()
        rows = self.nodes
        if chapter not in (None, ""):
            rows = [n for n in rows if n["chapter"] == int(chapter)]
        if scene:
            rows = [n for n in rows if n["scene"] == scene]
        if role:
            rows = [n for n in rows if n["role"] == role]
        if q:
            rows = [n for n in rows if q in n["name"].lower()
                    or q in (n.get("menu_text") or "").lower()
                    or q in (n.get("journal_text") or "").lower()
                    or q in (n.get("scene") or "").lower()]
        return [{
            "id": n["id"], "chapter": n["chapter"], "scene": n["scene"],
            "name": n["name"], "role": n["role"],
            "menu_text": n["menu_text"],
            "on_can_play": n["on_can_play"],
            "has_audio": bool(n.get("wav_key")),
            "dests": len(n.get("potential_dest") or []),
        } for n in rows]

    def node(self, ident: str):
        rec = self.by_id.get(ident)
        if rec is None and ":" not in (ident or ""):
            rec = next((n for n in self.nodes if n["name"] == ident), None)
        if rec is None:
            raise KeyError(ident)
        out = dict(rec)
        out["field_keys"] = list(FIELDS)
        return out

    def save_node(self, ident, fields=None, groups=None, links=None,
                  formations=None, events=None, script=None) -> str:
        rec = self.node(ident)
        text = self._text(rec["key"])
        assembled = {}
        src = fields or {}
        for key in FIELDS:
            if key in src and src[key] is not None:
                assembled[key] = src[key]
            else:
                low = key[0].lower() + key[1:] if key else key
                snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
                if src.get(snake) is not None:
                    assembled[key] = src[snake]
                elif src.get(low) is not None:
                    assembled[key] = src[low]
        if "potential_dest" in src and "PotentialDest" not in assembled:
            dest = src.get("potential_dest")
            if isinstance(dest, list):
                assembled["PotentialDest"] = ", ".join(dest)
        if events is not None:
            script = rebuild_script(rec["name"], events)
        aliases = {
            "MenuText": "menu_text",
            "JournalText": "journal_text",
            "DisableWhenPlayed": "disable_when_played",
            "AddToJournal": "add_to_journal",
            "EnterNavMode": "enter_nav_mode",
            "IgnoreFormations": "ignore_formations",
            "RunToFormations": "run_to_formations",
            "IgnoreOtherGroupMembersOnMoveToFormation": "ignore_other_on_move",
            "UseCameras": "use_cameras",
        }
        cur_fields = {}
        for key in FIELDS:
            alias = aliases.get(key)
            cur_fields[key] = rec.get(alias, "") if alias else rec.get(key, "")
        cur_fields["PotentialDest"] = ", ".join(rec.get("potential_dest") or [])
        cur_fields["PotentialCombats"] = ", ".join(
            rec.get("potential_combats") or [])
        cur_fields.update(assembled)
        lines = text.splitlines()
        start, end = _conv_span(lines, rec)
        indent = re.match(r"^(\s*)", lines[start]).group(1)
        block = format_block(
            rec["name"], cur_fields,
            groups if groups is not None else rec.get("groups"),
            links if links is not None else rec.get("links"),
            formations if formations is not None else rec.get("formations"),
            script if script is not None else rec.get("script"),
            indent)
        out = lines[:start] + block + lines[end + 1:]
        return "\n".join(out) + ("\n" if text.endswith("\n") else "")

    def add_node(self, chapter, scene, name, fields=None, parent=None) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("name required")
        key = self.chapter_keys.get(int(chapter))
        if not key:
            raise KeyError("chapter %s" % chapter)
        if any(n["chapter"] == int(chapter) and n["name"] == name
               for n in self.nodes):
            raise ValueError("%s already exists in chapter %s" % (name, chapter))
        text = self._text(key)
        src = dict(fields or {})
        assembled = {k: src.get(k, src.get(
            re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower(), "")) for k in FIELDS}
        if not assembled.get("EnterNavMode"):
            assembled["EnterNavMode"] = "1"
        if assembled.get("DisableWhenPlayed") in (None, ""):
            assembled["DisableWhenPlayed"] = "0"
        if assembled.get("AddToJournal") in (None, ""):
            assembled["AddToJournal"] = "0"
        for k in ("IgnoreFormations", "RunToFormations",
                  "IgnoreOtherGroupMembersOnMoveToFormation"):
            if assembled.get(k) in (None, ""):
                assembled[k] = "0"
        script = empty_script(name)
        lines = text.splitlines()
        start, end = rtkdef._block_span(lines, "SceneDef", scene)
        indent = re.match(r"^(\s*)", lines[start]).group(1) + "    "
        block = format_block(name, assembled, [], [], [], script, indent)
        text = "\n".join(lines[:end] + block + lines[end:]) + (
            "\n" if text.endswith("\n") else "")
        if parent:
            parent_rec = self.node(parent if ":" in str(parent)
                                   else node_id(chapter, parent))
            dests = list(parent_rec.get("potential_dest") or [])
            if name not in dests:
                dests.append(name)
            text = self._set_dest(text, parent_rec["name"], dests)
        return text

    def _set_dest(self, text, name, dests):
        return rtkdef.replace_field(
            text, "ConversationDef", name, "PotentialDest", ", ".join(dests))
