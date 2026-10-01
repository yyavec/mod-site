#!/usr/bin/env python3
"""mods/ 폴더의 .jar 파일로 site/index.html, site/mods.zip, site/icons/ 를 만든다.

직전 빌드의 site/manifest.json 과 비교해서 추가·업데이트·삭제된 모드를 사이트에 보여준다.
MODS_DIR, OUT_DIR, CONF_FILE 환경 변수로 경로를 바꿀 수 있다 (미리보기용).
"""
import hashlib
import html
import json
import os
import re
import shlex
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
MODS = Path(os.environ.get("MODS_DIR", ROOT / "mods"))
OUT = Path(os.environ.get("OUT_DIR", ROOT / "site"))
ICON_MAX = 256 * 1024


def load_conf():
    conf = {}
    for line in Path(os.environ.get("CONF_FILE", ROOT / "site.conf")).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parts = shlex.split(value)
        conf[key.strip()] = parts[0] if parts else ""
    return conf


def toml_str(text, key):
    """mods.toml 에서 key = "..." 또는 key = '''...''' 값을 읽는다."""
    m = re.search(rf"^\s*{key}\s*=\s*('''|\"\"\")(.*?)\1", text, re.M | re.S)
    if m:
        return m.group(2).strip()
    m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', text, re.M)
    return m.group(1) if m else None


def read_meta(jar: Path):
    """jar 안의 모드 정보(Fabric/Quilt/Forge/NeoForge)를 읽는다."""
    meta = {"id": None, "name": None, "version": None, "desc": "", "env": "", "icon": None}
    try:
        with zipfile.ZipFile(jar) as z:
            names = set(z.namelist())
            icon_path = None
            if "fabric.mod.json" in names:
                d = json.loads(z.read("fabric.mod.json").decode("utf-8", "ignore"), strict=False)
                meta.update(id=d.get("id"), name=d.get("name"), version=d.get("version"),
                            desc=d.get("description") or "", env=d.get("environment") or "")
                icon_path = d.get("icon")
            elif "quilt.mod.json" in names:
                d = json.loads(z.read("quilt.mod.json").decode("utf-8", "ignore"), strict=False)
                ql = d.get("quilt_loader", {})
                md = ql.get("metadata", {})
                meta.update(id=ql.get("id"), name=md.get("name"), version=ql.get("version"),
                            desc=md.get("description") or "", env=(d.get("minecraft") or {}).get("environment") or "")
                icon_path = md.get("icon")
            else:
                for toml in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                    if toml in names:
                        t = z.read(toml).decode("utf-8", "ignore")
                        meta.update(id=toml_str(t, "modId"), name=toml_str(t, "displayName"),
                                    version=toml_str(t, "version"), desc=toml_str(t, "description") or "")
                        logo = toml_str(t, "logoFile")
                        icon_path = logo and (logo if logo in names else None)
                        break
            if isinstance(icon_path, dict):  # {"16": "...", "128": "..."} → 가장 큰 것
                icon_path = icon_path[max(icon_path, key=lambda k: int(k) if k.isdigit() else 0)]
            if isinstance(icon_path, str) and icon_path in names:
                info = z.getinfo(icon_path)
                if info.file_size <= ICON_MAX and icon_path.lower().endswith(".png"):
                    meta["icon"] = z.read(icon_path)
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, ValueError):
        pass
    if meta["version"] and "${" in meta["version"]:
        meta["version"] = None
    meta["name"] = meta["name"] or jar.stem
    meta["version"] = meta["version"] or ""
    meta["id"] = meta["id"] or re.sub(r"[-_ ]?v?\d[\w.+-]*$", "", jar.stem).lower() or jar.stem.lower()
    meta["desc"] = " ".join(str(meta["desc"]).split())
    meta["env"] = meta["env"] if meta["env"] in ("client", "server") else ""
    return meta


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def slug(s):
    return re.sub(r"[^a-z0-9_.-]", "_", s.lower())[:64] or "mod"


def fmt_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.year}년 {d.month}월 {d.day}일 {d.hour:02d}:{d.minute:02d}"


ENV_TAG = {
    "client": '<span class="tag" title="게임하는 컴퓨터에서만 쓰는 모드예요">클라이언트</span>',
    "server": '<span class="tag tag-muted" title="서버에만 설치하는 모드라 받을 필요가 없어요">서버 전용 · 받지 않음</span>',
}


def scan(folder=MODS):
    """폴더의 jar 들을 읽어 모드 목록을 만든다 (서버 전용은 뒤로)."""
    mods = []
    for jar in sorted(Path(folder).glob("*.jar"), key=lambda p: p.name.lower()):
        m = read_meta(jar)
        m["file"], m["size"] = jar.name, jar.stat().st_size
        mods.append(m)
    mods.sort(key=lambda m: (m["env"] == "server", m["name"].lower()))
    return mods


def diff(old_mods, mods):
    """이전 목록과 비교해 추가·업데이트·삭제를 돌려준다."""
    old = {m["id"]: m for m in old_mods}
    new = {m["id"]: m for m in mods}
    changes = []
    for i, m in new.items():
        if i not in old:
            changes.append({"kind": "add", "name": m["name"], "to": m["version"]})
        elif old[i]["version"] != m["version"] or old[i]["file"] != m["file"]:
            changes.append({"kind": "up", "name": m["name"], "from": old[i]["version"], "to": m["version"]})
    for i, m in old.items():
        if i not in new:
            changes.append({"kind": "del", "name": m["name"], "from": m["version"]})
    order = {"add": 0, "up": 1, "del": 2}
    changes.sort(key=lambda c: (order[c["kind"]], c["name"].lower()))
    return changes


SEASON = ROOT / "season.json"


def store_installer():
    """store.json에 등록된 로더 설치 프로그램 (없으면 None)."""
    try:
        return json.loads((ROOT / "store.json").read_text(encoding="utf-8")).get("installer")
    except (OSError, json.JSONDecodeError):
        return None


def content_id():
    """사이트 내용(site.conf, season.json)의 지문. 바뀌었는지 비교할 때 쓴다."""
    h = hashlib.sha1()
    for f in (Path(os.environ.get("CONF_FILE", ROOT / "site.conf")), SEASON):
        h.update(f.read_bytes() if f.exists() else b"")
    return h.hexdigest()[:10]


def load_season():
    try:
        return json.loads(SEASON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def season_html(e):
    """season.json(투표 후보)을 HTML로 만든다. 숨김이거나 후보가 없으면 None.

    당선(winner) 후보가 있으면 그 카드를 크게 보여 주고, 나머지는 '투표 기록'으로 작고 흐리게 남긴다.
    """
    d = load_season()
    if not d or d.get("show") is False:
        return None
    cands = d.get("candidates", [])
    star = '<svg class="i st{on}"><use href="#i-star"/></svg>'

    def stars_of(c):
        n = max(0, min(5, int(c.get("stars", 0))))
        return n, "".join(star.format(on=" on" if i < n else "") for i in range(5))

    def vids_of(c):
        return "".join(f'<a class="vlink" href="{e(v)}" target="_blank" rel="noopener">영상 {i}</a>'
                       for i, v in enumerate(c.get("videos", []), 1))

    def tags_of(c):
        return "".join(f'<span class="tag">{e(t)}</span>' for t in c.get("tags", []))

    win = next((c for c in cands if c.get("winner")), None)
    if win:
        n, st = stars_of(win)
        no = cands.index(win) + 1
        img = str(win.get("image") or "")
        bg = f'<div class="win-bg" style="background-image:url(\'{e(img)}\')" aria-hidden="true"></div>' if re.match(r"^(assets/[\w.-]+|https://\S+)$", img) else ""
        body = (f'<div class="win-card{" has-bg" if bg else ""}">{bg}<div class="win-art"><svg class="px trophy" viewBox="0 0 10 9" shape-rendering="crispEdges" aria-hidden="true"><rect x="2" y="0" width="6" height="1" fill="#F2B636"/><rect x="0" y="1" width="3" height="1" fill="#F2B636"/><rect x="3" y="1" width="1" height="1" fill="#FFE58A"/><rect x="4" y="1" width="6" height="1" fill="#F2B636"/><rect x="0" y="2" width="1" height="1" fill="#F2B636"/><rect x="2" y="2" width="1" height="1" fill="#F2B636"/><rect x="3" y="2" width="1" height="1" fill="#FFE58A"/><rect x="4" y="2" width="4" height="1" fill="#F2B636"/><rect x="9" y="2" width="1" height="1" fill="#F2B636"/><rect x="1" y="3" width="8" height="1" fill="#F2B636"/><rect x="2" y="4" width="6" height="1" fill="#F2B636"/><rect x="3" y="5" width="4" height="1" fill="#F2B636"/><rect x="4" y="6" width="2" height="1" fill="#F2B636"/><rect x="3" y="7" width="4" height="1" fill="#F2B636"/><rect x="2" y="8" width="6" height="1" fill="#8B5A2B"/></svg></div><div class="win-main">'
                f'<div class="win-top"><span class="win-badge">투표 1위 · {no}번 후보</span></div>'
                f'<div class="win-n">{e(win.get("name", ""))}</div><div class="cand-p">{e(win.get("pack", ""))}</div>'
                f'<div class="cand-meta"><span class="stars" role="img" aria-label="추천도 5점 중 {n}점">{st}</span>'
                f'<span class="weeks num">{e(win.get("weeks", ""))}</span>{tags_of(win)}</div>'
                f'<div class="cand-v">{vids_of(win)}</div></div></div>')
        rows = []
        for i, c in enumerate(cands, 1):
            n, st = stars_of(c)
            w = c is win
            first = (c.get("videos") or [None])[0]
            link = f'<a class="hist-v" href="{e(first)}" target="_blank" rel="noopener" aria-label="{e(c.get("name", ""))} 영상">영상</a>' if first else ""
            rows.append(f'<li class="hist{" is-win" if w else ""}"><span class="hist-no num">{i}</span>'
                        f'<span class="hist-n">{e(c.get("name", ""))}<small>{e(c.get("pack", ""))}</small></span>'
                        f'{"<span class=hist-tag>당선</span>" if w else ""}'
                        f'<span class="stars" role="img" aria-label="추천도 5점 중 {n}점">{st}</span>{link}</li>')
        body += (f'<details class="history" open><summary>투표 기록 <span class="num">후보 {len(cands)}개</span></summary>'
                 f'<ol class="hist-list">{"".join(rows)}</ol></details>')
    else:
        cards = []
        for c in cands:
            n, st = stars_of(c)
            cards.append(
                f'<li class="cand"><div class="cand-main"><div class="cand-n">{e(c.get("name", ""))}</div>'
                f'<div class="cand-p">{e(c.get("pack", ""))}</div></div>'
                f'<div class="cand-meta"><span class="stars" role="img" aria-label="추천도 5점 중 {n}점">{st}</span>'
                f'<span class="weeks num">{e(c.get("weeks", ""))}</span>{tags_of(c)}</div>'
                f'<div class="cand-v">{vids_of(c)}</div></li>')
        body = f'<ol class="cands">{"".join(cards)}</ol>'
    return {"title": d.get("title", ""), "period": d.get("period", ""), "intro": d.get("intro", ""),
            "badge": d.get("badge", ""), "button": d.get("button") or "노션에서 자세히 보기",
            "body": body, "voting": not win,
            "now": (win.get("pack") or win.get("name") or "") if win else ""}

def main():
    conf = load_conf()
    OUT.mkdir(parents=True, exist_ok=True)
    mods = scan(MODS)
    client_mods = [m for m in mods if m["env"] != "server"]

    # zip: 서버 전용 모드는 빼고 묶는다
    zip_path = OUT / "mods.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for m in client_mods:
            z.write(MODS / m["file"], m["file"])

    # 아이콘
    icons = OUT / "icons"
    shutil.rmtree(icons, ignore_errors=True)
    icons.mkdir()
    for m in mods:
        if m["icon"]:
            p = icons / f"{slug(m['id'])}.png"
            p.write_bytes(m["icon"])
            m["icon_url"] = f"icons/{p.name}"

    # 직전 빌드와 비교
    build_id = hashlib.sha1("\n".join(f"{m['file']}:{m['size']}" for m in mods).encode()).hexdigest()[:10]
    man_path = OUT / "manifest.json"
    prev = {}
    try:
        prev = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if prev.get("build") == build_id:
        updated, changes = prev["updated"], prev.get("changes", [])
    else:
        updated = datetime.now().isoformat(timespec="minutes")
        changes = diff(prev["mods"], mods) if prev.get("mods") else []
    man_path.write_text(json.dumps({
        "build": build_id, "content": content_id(), "updated": updated, "changes": changes,
        "installer": store_installer(),
        "mods": [{"id": m["id"], "name": m["name"], "version": m["version"], "file": m["file"]} for m in mods],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    e = html.escape

    # 모드 목록
    rows = []
    for m in mods:
        icon = (f'<img src="{e(m["icon_url"])}" alt="" loading="lazy" width="32" height="32">'
                if m.get("icon_url") else f'<span class="ph" aria-hidden="true">{e(m["name"][:1].upper())}</span>')
        search = f'{m["name"]} {m["id"]} {m["file"]} {m["desc"]}'.lower()
        rows.append(
            f'<li class="mod{" is-server" if m["env"] == "server" else ""}" data-q="{e(search)}">'
            f'<span class="ic">{icon}</span>'
            f'<span class="mi"><span class="mn">{e(m["name"])}{ENV_TAG.get(m["env"], "")}</span>'
            f'<span class="md" title="{e(m["desc"])}">{e(m["desc"]) or e(m["file"])}</span></span>'
            f'<span class="mv num" title="{e(m["file"])}">{e(m["version"]) or "—"}</span>'
            f'<span class="ms num">{fmt_size(m["size"])}</span>'
            "</li>"
        )

    # 변경 내역
    sym = {"add": ("추가", "+"), "up": ("업데이트", "↑"), "del": ("삭제", "−")}
    ch = []
    for c in changes:
        label, s = sym[c["kind"]]
        if c["kind"] == "up":
            ver = f'<span class="num">{e(c["from"] or "?")}</span><span class="arrow" aria-hidden="true">→</span><span class="num">{e(c["to"] or "?")}</span>'
        else:
            ver = f'<span class="num">{e(c.get("to") or c.get("from") or "")}</span>'
        ch.append(f'<li class="ch ch-{c["kind"]}"><span class="ck"><span aria-hidden="true">{s}</span>{label}</span>'
                  f'<span class="cn">{e(c["name"])}</span><span class="cv">{ver}</span></li>')

    chips = []
    if conf.get("MC_VERSION"):
        chips.append(f'<span class="chip">마인크래프트 {e(conf["MC_VERSION"])}</span>')
    if conf.get("LOADER"):
        chips.append(f'<span class="chip">{e(conf["LOADER"])}</span>')

    server_n = len(mods) - len(client_mods)
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    rep = {
        "SERVER_NAME": e(conf.get("SERVER_NAME") or "마크 서버"),
        "SITE_TITLE": e(conf.get("SITE_TITLE") or conf.get("SERVER_NAME") or "마크 서버"),
        "SERVER_ADDRESS": e(conf.get("SERVER_ADDRESS", "")),
        "ADDRESS_HIDDEN": "" if conf.get("SERVER_ADDRESS") else "hidden",
        "CHIPS": "".join(chips),
        "CHIPS_HIDDEN": "" if chips else "hidden",
        "NOTICE": e(conf.get("NOTICE", "")),
        "NOTICE_HIDDEN": "" if conf.get("NOTICE") else "hidden",
        "LOADER": e(conf.get("LOADER") or "모드 로더"),
        "COUNT": str(len(client_mods)),
        "TOTAL": str(len(mods)),
        "SERVER_ONLY_NOTE": f" · 서버 전용 {server_n}개 제외" if server_n else "",
        "ZIP_SIZE": fmt_size(zip_path.stat().st_size),
        "ZIP_URL": e(os.environ.get("ZIP_URL", "mods.zip")),
        "DISABLED": "" if client_mods else 'aria-disabled="true" tabindex="-1"',
        "ROWS": "".join(rows),
        "LIST_HIDDEN": "" if mods else "hidden",
        "LIST_EMPTY_HIDDEN": "hidden" if mods else "",
        "CHANGES": "".join(ch),
        "CHANGES_HIDDEN": "" if ch else "hidden",
        "UPDATED": fmt_date(updated),
        "UPDATED_ISO": updated,
        "BUILD": build_id,
        "COMMUNITY": e(conf.get("COMMUNITY") or "서버 모드"),
        "NOTION_URL": e(conf.get("NOTION_URL", "")),
        "NOTION_HIDDEN": "" if conf.get("NOTION_URL") else "hidden",
        "DISCORD_URL": e(conf.get("DISCORD_URL", "")),
        "DISCORD_HIDDEN": "" if conf.get("DISCORD_URL") else "hidden",
        "ADMIN_HIDDEN": "" if conf.get("ADMIN_API") else "hidden",
        "MOOD": conf.get("MOOD") if conf.get("MOOD") in ("nightfall",) else "",
    }
    season = season_html(e)
    rep.update({
        "SEASON_TITLE": e(season["title"]) if season else "",
        "SEASON_PERIOD": e(season["period"]) if season else "",
        "SEASON_INTRO": e(season["intro"]) if season else "",
        "SEASON_INTRO_HIDDEN": "" if season and season["intro"] else "hidden",
        "SEASON_BODY": season["body"] if season else "",
        "NOW_PLAYING": e(season["now"]) if season else "",
        "NOW_HIDDEN": "" if season and season["now"] else "hidden",
        "SEASON_NOTE": "별점은 운영자 추천도, 기간은 예정이에요." if season and season["voting"] else "",
        "SEASON_BADGE": e(season["badge"]) if season else "",
        "SEASON_BADGE_HIDDEN": "" if season and season["badge"] else "hidden",
        "SEASON_BUTTON": e(season["button"]) if season else "",
        "SEASON_HIDDEN": "" if season and season["body"] else "hidden",
    })

    # 처음 왔어요 안내: 로더·버전·서버 주소에 맞춰 문장을 만든다
    loader = conf.get("LOADER", "")
    ver = conf.get("MC_VERSION", "")
    links = {
        "Fabric": ("Fabric 설치 파일 받기", "https://fabricmc.net/use/installer/"),
        "NeoForge": ("NeoForge 설치 파일 받기", "https://neoforged.net/"),
        "Forge": ("Forge 설치 파일 받기", "https://files.minecraftforge.net/"),
        "Quilt": ("Quilt 설치 파일 받기", "https://quiltmc.org/en/install/"),
    }
    ext = '<svg class="i"><use href="#i-ext"/></svg>'
    chosen = [links[loader]] if loader in links else [links[k] for k in ("Fabric", "NeoForge", "Forge")]
    loader_links = "".join(f'<a class="btn-ghost" href="{u}" target="_blank" rel="noopener">{e(t)}{ext}</a>' for t, u in chosen)
    inst = store_installer()
    if inst:  # 관리자가 올린 설치 프로그램이 있으면 그걸 크게, 공식 사이트는 작게
        repo = os.environ.get("GITHUB_REPOSITORY", "yyavec/mod-site")
        url = f"https://github.com/{repo}/releases/download/store/{quote(inst['file'])}"
        dl = '<svg class="i"><use href="#i-dl"/></svg>'
        loader_links = (f'<a class="inst-dl" href="{e(url)}">{dl}<span><b>{e(loader or "모드 로더")} 설치 프로그램 받기</b>'
                        f'<small>{e(inst.get("name") or inst["file"])} · {fmt_size(int(inst.get("size") or 0))}</small></span></a>'
                        + "".join(f'<a class="inst-alt" href="{u}" target="_blank" rel="noopener">공식 사이트{ext}</a>' for t, u in chosen[:1]))
    profile = {"Fabric": f"fabric-loader-{ver}", "Quilt": f"quilt-loader-{ver}", "NeoForge": "neoforge", "Forge": f"forge ({ver}-forge-…)"}.get(loader, "")
    notes = []
    if not loader:
        notes.append("어떤 로더를 쓰는지는 서버가 열리면 공지할게요. 공지된 것 하나만 설치하면 돼요.")
    if not ver:
        notes.append("마인크래프트 버전도 서버가 열리면 공지할게요.")
    addr = conf.get("SERVER_ADDRESS", "")
    addr_row = (f'<div class="path"><code>{e(addr)}</code><button class="btn-ghost" type="button" data-copy="{e(addr)}" '
                f'data-toast="서버 주소를 복사했어요"><svg class="i"><use href="#i-copy"/></svg>복사</button></div>'
                if addr else '<p class="gnote">서버 주소는 서버가 열리면 여기에 나와요.</p>')
    rep.update({
        "G_LOADER": e(loader or "모드 로더"),
        "G_VERSION": e(ver or "공지된 버전"),
        "G_LOADER_LINKS": loader_links,
        "G_VERSION_NOTE": "".join(f'<p class="gnote">{e(n)}</p>' for n in notes),
        "G_PROFILE": e(profile if loader and ver else f"{loader or '모드 로더'} {ver}".strip() or "모드 로더"),
        "G_ADDR_ROW": addr_row,
    })

    # 지난 시즌 (취소선 + 완결 도장)
    past = (load_season() or {}).get("past") or []
    ball = '<svg class="px" viewBox="0 0 8 8" shape-rendering="crispEdges" aria-hidden="true"><rect x="2" y="0" width="4" height="1" fill="#E3403A"/><rect x="1" y="1" width="6" height="1" fill="#E3403A"/><rect x="0" y="2" width="8" height="1" fill="#E3403A"/><rect x="0" y="3" width="3" height="1" fill="#222"/><rect x="3" y="3" width="2" height="1" fill="#fff"/><rect x="5" y="3" width="3" height="1" fill="#222"/><rect x="0" y="4" width="3" height="1" fill="#222"/><rect x="3" y="4" width="2" height="1" fill="#fff"/><rect x="5" y="4" width="3" height="1" fill="#222"/><rect x="0" y="5" width="8" height="1" fill="#F2F2F2"/><rect x="1" y="6" width="6" height="1" fill="#F2F2F2"/><rect x="2" y="7" width="4" height="1" fill="#DADADA"/></svg>'
    rep.update({
        "PAST_ROWS": "".join(
            f'<div class="past-row">{ball}<span class="past-k">{e(p.get("title", ""))}</span>'
            f'<span class="past-t">{e(p.get("name", ""))}<small>{e(p.get("pack", ""))}</small></span>'
            f'<span class="past-stamp">완</span></div>' for p in past),
        "PAST_HIDDEN": "" if past else "hidden",
        "OWNER": e(conf.get("OWNER", "")),
        "OWNER_HIDDEN": "" if conf.get("OWNER") else "hidden",
    })

    # 서브 서버 (바닐라 플러스)
    sub = (load_season() or {}).get("sub") or {}
    sub_html = ""
    if sub.get("show") is not False and (sub.get("title") or sub.get("mods")):
        addr = sub.get("address", "")
        addr_html = (f'<button class="sub-addr" type="button" data-copy="{e(addr)}" data-toast="서브 서버 주소를 복사했어요">'
                     f'<span>{e(addr)}</span><svg class="i"><use href="#i-copy"/></svg></button>' if addr
                     else '<span class="sub-soon">주소는 곧 공지할게요</span>')
        ver = f'<span class="sub-chip">마인크래프트 {e(sub["version"])}</span>' if sub.get("version") else ""
        mods = "".join(f'<li><b>{e(m.get("name", ""))}</b><span>{e(m.get("desc", ""))}</span></li>' for m in sub.get("mods", []) if m.get("name"))
        sub_html = (f'<section class="sub" aria-labelledby="subTitle"><div class="sub-sky" aria-hidden="true"><span class="sub-sun"><svg class="px" viewBox="0 0 9 9" shape-rendering="crispEdges" aria-hidden="true"><rect x="4" y="0" width="1" height="1" fill="#FFD24A"/><rect x="1" y="1" width="1" height="1" fill="#FFD24A"/><rect x="7" y="1" width="1" height="1" fill="#FFD24A"/><rect x="3" y="2" width="3" height="1" fill="#FFD24A"/><rect x="2" y="3" width="5" height="1" fill="#FFD24A"/><rect x="0" y="4" width="1" height="1" fill="#FFD24A"/><rect x="2" y="4" width="2" height="1" fill="#FFD24A"/><rect x="4" y="4" width="1" height="1" fill="#FFF1B0"/><rect x="5" y="4" width="2" height="1" fill="#FFD24A"/><rect x="8" y="4" width="1" height="1" fill="#FFD24A"/><rect x="2" y="5" width="5" height="1" fill="#FFD24A"/><rect x="3" y="6" width="3" height="1" fill="#FFD24A"/><rect x="1" y="7" width="1" height="1" fill="#FFD24A"/><rect x="7" y="7" width="1" height="1" fill="#FFD24A"/><rect x="4" y="8" width="1" height="1" fill="#FFD24A"/></svg></span></div>'
                    f'<div class="sub-in"><div class="sub-top"><span class="sub-ic"><svg class="px" viewBox="0 0 8 8" shape-rendering="crispEdges" aria-hidden="true"><rect x="3" y="0" width="2" height="1" fill="#6CC24A"/><rect x="2" y="1" width="4" height="1" fill="#6CC24A"/><rect x="1" y="2" width="2" height="1" fill="#6CC24A"/><rect x="3" y="2" width="1" height="1" fill="#4E9A31"/><rect x="4" y="2" width="3" height="1" fill="#6CC24A"/><rect x="2" y="3" width="1" height="1" fill="#6CC24A"/><rect x="3" y="3" width="1" height="1" fill="#4E9A31"/><rect x="4" y="3" width="2" height="1" fill="#6CC24A"/><rect x="3" y="4" width="1" height="1" fill="#8B5A2B"/><rect x="3" y="5" width="1" height="1" fill="#8B5A2B"/><rect x="0" y="6" width="2" height="1" fill="#4E9A31"/><rect x="2" y="6" width="1" height="1" fill="#3F7F27"/><rect x="3" y="6" width="2" height="1" fill="#4E9A31"/><rect x="5" y="6" width="1" height="1" fill="#3F7F27"/><rect x="6" y="6" width="2" height="1" fill="#4E9A31"/><rect x="0" y="7" width="1" height="1" fill="#8B5A2B"/><rect x="1" y="7" width="1" height="1" fill="#6E4520"/><rect x="2" y="7" width="2" height="1" fill="#8B5A2B"/><rect x="4" y="7" width="1" height="1" fill="#6E4520"/><rect x="5" y="7" width="2" height="1" fill="#8B5A2B"/><rect x="7" y="7" width="1" height="1" fill="#6E4520"/></svg></span>'
                    f'<div class="sub-tt"><span class="sub-k">서브 서버 · 같이 열려 있어요</span><h2 id="subTitle">{e(sub.get("title", ""))}</h2></div></div>'
                    f'<p class="sub-desc">{e(sub.get("desc", ""))}</p>'
                    f'<div class="sub-meta">{addr_html}{ver}</div>'
                    + (f'<div class="sub-mods-h">들어 있는 필수 모드</div><ul class="sub-mods">{mods}</ul>' if mods else "")
                    + '</div></section>')
    rep["SUB_SECTION"] = sub_html
    page = re.sub(r"\{\{(\w+)\}\}", lambda mt: rep.get(mt.group(1), mt.group(0)), tpl)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    if (ROOT / "assets").is_dir():  # 사이트에 쓰는 그림
        shutil.copytree(ROOT / "assets", OUT / "assets", dirs_exist_ok=True)

    # 웹 관리자 화면 (로그인은 관리 서버가 확인한다)
    admin_tpl = ROOT / "admin.html"
    if admin_tpl.exists():
        arep = {"ADMIN_API": e(conf.get("ADMIN_API", "")), "GOOGLE_CLIENT_ID": e(conf.get("GOOGLE_CLIENT_ID", "")),
                "SITE_TITLE": rep["SITE_TITLE"], "REPO": e(os.environ.get("GITHUB_REPOSITORY", ""))}
        apage = re.sub(r"\{\{(\w+)\}\}", lambda mt: arep.get(mt.group(1), mt.group(0)), admin_tpl.read_text(encoding="utf-8"))
        (OUT / "admin.html").write_text(apage, encoding="utf-8")
    extra = f", 서버 전용 {server_n}개는 zip에서 제외" if server_n else ""
    print(f"모드 {len(mods)}개{extra} → {OUT}/index.html, mods.zip ({fmt_size(zip_path.stat().st_size)})")
    if changes:
        print("바뀐 점: " + ", ".join(f"{sym[c['kind']][0]} {c['name']}" for c in changes))


if __name__ == "__main__":
    main()
