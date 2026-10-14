// 웹 관리자용 미니 서버.
// 구글 로그인(ID 토큰)으로 관리자인지 확인한 뒤, GitHub 저장소에 대신 저장한다.
// 모드 파일은 store 릴리스에, 목록은 store.json에, 사이트 내용은 site.conf / season.json에 둔다.

const CONF_KEYS = ["TOPBAR", "TOPBAR_UNTIL", "SITE_TITLE", "MOOD", "OWNER", "COMMUNITY", "LOADER_URL", "SERVER_NAME", "SERVER_ADDRESS", "MC_VERSION", "LOADER",
  "NOTICE", "NOTION_URL", "DISCORD_URL"];
const URL_KEYS = new Set(["NOTION_URL", "DISCORD_URL", "LOADER_URL"]);
const MAX_UPLOAD = 100 * 1024 * 1024;
const WORKFLOW = "build.yml";

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
      "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Filename, X-Meta",
      "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
      "Access-Control-Max-Age": "86400",
      "Vary": "Origin",
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    try {
      const user = await verifyGoogle(req, env);
      const out = await route(req, env, user);
      return Response.json(out, { headers: { ...cors, "Cache-Control": "no-store" } });
    } catch (e) {
      const status = e.status || 500;
      const message = e.status ? e.message : "서버에서 문제가 생겼어요. 잠시 뒤 다시 해 주세요";
      if (!e.status) console.error(e);
      return Response.json({ message }, { status, headers: cors });
    }
  },
};

async function route(req, env, user) {
  const { pathname } = new URL(req.url);
  const gh = github(env);
  const key = `${req.method} ${pathname}`;
  switch (key) {
    case "GET /me": return { email: user.email, name: user.name || "" };
    case "GET /state": return state(gh);
    case "POST /upload": return upload(req, gh);
    case "POST /delete": return removeMod(await req.json(), gh);
    case "POST /restore": return restoreMod(await req.json(), gh);
    case "POST /installer": return uploadExtra(req, gh, "installer");
    case "POST /installer-remove": return removeExtra(gh, "installer");
    case "POST /configs": return uploadExtra(req, gh, "configs");
    case "POST /configs-remove": return removeExtra(gh, "configs");
    case "GET /content": return getContent(gh);
    case "PUT /content": return saveContent(await req.json(), gh);
    case "POST /publish": return publish(gh);
    case "GET /publish": return lastRun(gh);
  }
  throw new HttpError(404, "없는 기능이에요");
}

/* ---------------- 구글 로그인 확인 ---------------- */

let jwks = null, jwksAt = 0;
const b64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
const json64 = s => JSON.parse(new TextDecoder().decode(b64u(s)));

async function verifyGoogle(req, env) {
  const m = /^Bearer (.+)$/.exec(req.headers.get("Authorization") || "");
  if (!m) throw new HttpError(401, "로그인이 필요해요");
  const [h, p, sig] = m[1].split(".");
  if (!sig) throw new HttpError(401, "로그인 정보가 이상해요. 다시 로그인해 주세요");
  const header = json64(h), claims = json64(p);
  if (!jwks || Date.now() - jwksAt > 3600e3) {
    jwks = (await (await fetch("https://www.googleapis.com/oauth2/v3/certs")).json()).keys;
    jwksAt = Date.now();
  }
  const jwk = jwks.find(k => k.kid === header.kid);
  if (!jwk || header.alg !== "RS256") throw new HttpError(401, "로그인이 만료됐어요. 다시 로그인해 주세요");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64u(sig), new TextEncoder().encode(`${h}.${p}`));
  const now = Date.now() / 1000;
  if (!ok || !["accounts.google.com", "https://accounts.google.com"].includes(claims.iss)
      || claims.aud !== env.GOOGLE_CLIENT_ID || claims.exp < now - 30) {
    throw new HttpError(401, "로그인이 만료됐어요. 다시 로그인해 주세요");
  }
  const admins = String(env.ADMIN_EMAIL || "").toLowerCase().split(",").map(s => s.trim()).filter(Boolean);
  if (!claims.email_verified || !admins.includes(String(claims.email).toLowerCase())) {
    throw new HttpError(403, "관리자로 등록된 계정이 아니에요");
  }
  return claims;
}

/* ---------------- GitHub ---------------- */

function github(env) {
  const base = `https://api.github.com/repos/${env.REPO}`;
  const headers = {
    "Authorization": `Bearer ${env.GITHUB_TOKEN}`, "User-Agent": "mod-site-admin",
    "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
  };
  async function call(path, init = {}) {
    const url = path.startsWith("https://") ? path : base + path;
    const r = await fetch(url, { ...init, headers: { ...headers, ...(init.headers || {}) } });
    if (r.status === 204) return null;
    const body = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
    if (!r.ok) {
      const e = new Error(`GitHub ${r.status} ${path}: ${JSON.stringify(body).slice(0, 300)}`);
      e.gh = r.status; throw e;
    }
    return body;
  }
  return {
    repo: env.REPO,
    call,
    async file(path) {
      const f = await call(`/contents/${path}?ref=main`);
      const bytes = b64u(f.content.replace(/\n/g, ""));
      return { text: new TextDecoder().decode(bytes), sha: f.sha };
    },
    async put(path, text, sha, message) {
      const bytes = new TextEncoder().encode(text);
      let bin = ""; for (const b of bytes) bin += String.fromCharCode(b);
      return call(`/contents/${path}`, { method: "PUT", body: JSON.stringify({ message, content: btoa(bin), sha, branch: "main" }) });
    },
    async store() {
      try { return await call(`/releases/tags/store`); }
      catch (e) {
        if (e.gh !== 404) throw e;
        return call(`/releases`, { method: "POST", body: JSON.stringify({
          tag_name: "store", name: "모드 보관함", prerelease: true, make_latest: "false",
          body: "관리자 화면에서 올린 모드 원본 파일이에요. 직접 지우지 마세요." }) });
      }
    },
    async assets(release) {
      const all = [];
      for (let page = 1; ; page++) {
        const list = await call(`/releases/${release.id}/assets?per_page=100&page=${page}`);
        all.push(...list);
        if (list.length < 100) return all;
      }
    },
  };
}

async function readStore(gh) {
  const f = await gh.file("store.json");
  return { data: JSON.parse(f.text), sha: f.sha };
}

/* ---------------- 상태 ---------------- */

async function state(gh) {
  const [{ data }, run] = await Promise.all([readStore(gh), lastRun(gh)]);
  let contentChanged = true;
  if (run.sha) {
    const cmp = await gh.call(`/compare/${run.sha}...main`);
    contentChanged = (cmp.files || []).some(f => ["site.conf", "season.json"].includes(f.filename));
  }
  return { mods: data.mods, installer: data.installer || null, configs: data.configs || null, content_changed: contentChanged, publish: run };
}

async function lastRun(gh) {
  const r = await gh.call(`/actions/workflows/${WORKFLOW}/runs?per_page=10`);
  const runs = r.workflow_runs || [];
  const latest = runs[0];
  const success = runs.find(x => x.conclusion === "success");
  return {
    running: !!latest && latest.status !== "completed",
    ok: latest ? (latest.status === "completed" ? latest.conclusion === "success" : null) : null,
    url: latest?.html_url || null,
    at: latest?.created_at || null,
    sha: success?.head_sha || null,
  };
}

/* ---------------- 모드 ---------------- */

// GitHub는 올린 파일 이름에서 특수문자를 점(.)으로 바꾼다. 같은 파일인지 비교할 때 이 규칙을 따른다.
const ghName = n => n.replace(/[^A-Za-z0-9._+-]/g, ".").replace(/\.{2,}/g, ".").replace(/^\.+|\.(?=\.[^.]+$)/g, "").replace(/\.+(\.[A-Za-z0-9]+)$/, "$1");
const sameAsset = (a, name) => a.name === name || a.name === ghName(name);

const one = (v, n = 200) => String(v ?? "").replace(/\s+/g, " ").trim().slice(0, n);

async function upload(req, gh) {
  const name = decodeURIComponent(req.headers.get("X-Filename") || "").split(/[\\/]/).pop().trim();
  if (!/\.jar$/i.test(name) || name.startsWith(".")) throw new HttpError(400, ".jar 파일만 올릴 수 있어요");
  const size = +req.headers.get("Content-Length");
  if (!size) throw new HttpError(400, "빈 파일이에요");
  if (size > MAX_UPLOAD) throw new HttpError(413, "웹에서는 100MB가 넘는 파일을 올릴 수 없어요");
  let meta = {};
  try { meta = JSON.parse(decodeURIComponent(req.headers.get("X-Meta") || "{}")); } catch {}
  const id = one(meta.id, 80) || name.replace(/[-_ ]?v?\d[\w.+-]*\.jar$/i, "").toLowerCase();

  const rel = await gh.store();
  const assets = await gh.assets(rel);
  const { data, sha } = await readStore(gh);
  // 같은 이름 파일이 보관함에 있으면 먼저 지운다 (GitHub는 이름이 겹치면 못 올림)
  const same = assets.find(a => sameAsset(a, name));
  if (same) await gh.call(`/releases/assets/${same.id}`, { method: "DELETE" });

  // 받은 파일을 그대로 흘려보낸다 (GitHub는 길이가 정해진 업로드만 받는다)
  const { readable, writable } = new FixedLengthStream(size);
  req.body.pipeTo(writable);
  const up = await gh.call(`https://uploads.github.com/repos/${gh.repo}/releases/${rel.id}/assets?name=${encodeURIComponent(name)}`, {
    method: "POST", body: readable, headers: { "Content-Type": "application/java-archive" },
  });

  const replaced = data.mods.filter(m => m.id === id || m.file === up.name || (same && m.file === same.name));
  const entry = {
    file: up.name, id, name: one(meta.name, 80) || name.replace(/\.jar$/i, ""), version: one(meta.version, 60),
    desc: one(meta.desc, 300), env: ["client", "server"].includes(meta.env) ? meta.env : "", size: up.size,
  };
  data.mods = data.mods.filter(m => !replaced.includes(m)).concat(entry)
    .sort((a, b) => (a.env === "server") - (b.env === "server") || a.name.localeCompare(b.name));
  await gh.put("store.json", JSON.stringify(data, null, 2) + "\n", sha, `모드 ${replaced.length ? "교체" : "추가"}: ${entry.name}`);
  const sameFile = replaced.some(m => m.file === up.name);
  return { result: replaced.length ? (sameFile ? "same" : "replace") : "add", file: up.name,
           name: entry.name, version: entry.version, from: replaced[0]?.version ?? null };
}

async function removeMod(body, gh) {
  const { data, sha } = await readStore(gh);
  const entry = data.mods.find(m => m.file === body.file);
  if (!entry) throw new HttpError(404, "이미 없는 모드예요");
  data.mods = data.mods.filter(m => m !== entry);
  await gh.put("store.json", JSON.stringify(data, null, 2) + "\n", sha, `모드 삭제: ${entry.name}`);
  return { entry };   // 되돌리기용. 파일은 '올리기' 전까지 보관함에 남아 있다.
}

async function restoreMod(body, gh) {
  const entry = body.entry || {};
  const assets = await gh.assets(await gh.store());
  if (!assets.some(a => a.name === entry.file)) throw new HttpError(404, "보관함에서 파일을 찾지 못했어요");
  const { data, sha } = await readStore(gh);
  if (data.mods.some(m => m.id === entry.id)) throw new HttpError(409, "같은 모드가 이미 있어요");
  data.mods.push(entry);
  await gh.put("store.json", JSON.stringify(data, null, 2) + "\n", sha, `모드 되돌리기: ${entry.name}`);
  return { ok: true };
}

/* ---------------- 로더 설치 프로그램 ---------------- */
// '처음 왔어요' 2단계의 받기 버튼이 가리키는 파일. 모드와 같은 보관함(store)에 둔다.

const SLOTS = {
  installer: { ext: /\.(jar|exe|msi|zip)$/i, kinds: ".jar, .exe, .msi, .zip", label: "설치 프로그램" },
  configs: { ext: /\.zip$/i, kinds: ".zip", label: "설정 파일" },
};

async function uploadExtra(req, gh, slot) {
  const S = SLOTS[slot];
  const name = decodeURIComponent(req.headers.get("X-Filename") || "").split(/[\\/]/).pop().trim();
  if (!S.ext.test(name) || name.startsWith(".")) throw new HttpError(400, `${S.kinds} 파일만 올릴 수 있어요`);
  const size = +req.headers.get("Content-Length");
  if (!size) throw new HttpError(400, "빈 파일이에요");
  if (size > MAX_UPLOAD) throw new HttpError(413, "웹에서는 100MB가 넘는 파일을 올릴 수 없어요");
  const rel = await gh.store();
  const assets = await gh.assets(rel);
  const { data, sha } = await readStore(gh);
  if (data.mods.some(m => m.file === name || m.file === ghName(name))) throw new HttpError(409, "모드 파일과 이름이 같아요. 파일 이름을 바꿔서 올려 주세요");
  const same = assets.find(a => sameAsset(a, name));
  if (same) await gh.call(`/releases/assets/${same.id}`, { method: "DELETE" });
  const { readable, writable } = new FixedLengthStream(size);
  req.body.pipeTo(writable);
  const up = await gh.call(`https://uploads.github.com/repos/${gh.repo}/releases/${rel.id}/assets?name=${encodeURIComponent(name)}`, {
    method: "POST", body: readable, headers: { "Content-Type": "application/octet-stream" },
  });
  const prev = data[slot];
  data[slot] = { file: up.name, name, size: up.size };
  await gh.put("store.json", JSON.stringify(data, null, 2) + "\n", sha, `${S.label}: ${name}`);
  if (prev && prev.file !== up.name) {
    const old = assets.find(a => a.name === prev.file);
    if (old) await gh.call(`/releases/assets/${old.id}`, { method: "DELETE" }).catch(() => {});
  }
  return { [slot]: data[slot] };
}

async function removeExtra(gh, slot) {
  const { data, sha } = await readStore(gh);
  if (!data[slot]) return { [slot]: null };
  delete data[slot];
  await gh.put("store.json", JSON.stringify(data, null, 2) + "\n", sha, `${SLOTS[slot].label} 내림`);
  return { [slot]: null };   // 파일은 '올리기' 때 정리된다
}

/* ---------------- 사이트 내용 ---------------- */

// site.conf 한 줄 값 읽기: "..." / '...' / '\'' 이어붙이기만 지원 (우리가 쓰는 형식)
function confValue(raw) {
  let out = "", i = 0; raw = raw.trim();
  while (i < raw.length) {
    const c = raw[i];
    if (c === '"') { i++; while (i < raw.length && raw[i] !== '"') { if (raw[i] === "\\" && i + 1 < raw.length) i++; out += raw[i++]; } i++; }
    else if (c === "'") { i++; while (i < raw.length && raw[i] !== "'") out += raw[i++]; i++; }
    else if (c === "\\" && i + 1 < raw.length) { out += raw[i + 1]; i += 2; }
    else if (/\s/.test(c) || c === "#") break;
    else out += raw[i++];
  }
  return out;
}
const quote = v => /^[^\\"$`']*$/.test(v) ? `"${v}"` : `'${v.replace(/'/g, `'\\''`)}'`;

async function getContent(gh) {
  const [conf, season] = await Promise.all([gh.file("site.conf"), gh.file("season.json")]);
  const vals = {};
  for (const line of conf.text.split("\n")) {
    const m = /^\s*([A-Z_]+)\s*=(.*)$/.exec(line);
    if (m && CONF_KEYS.includes(m[1])) vals[m[1]] = confValue(m[2]);
  }
  for (const k of CONF_KEYS) vals[k] ??= "";
  return { conf: vals, season: JSON.parse(season.text) };
}

function checkUrl(v, what) {
  v = one(v, 500);
  if (v && !/^https:\/\/[^\s"'<>]+$/.test(v)) throw new HttpError(400, `${what}는 https:// 로 시작하는 주소여야 해요`);
  return v;
}

async function saveContent(data, gh) {
  const cin = data.conf || {}, vals = {};
  for (const k of CONF_KEYS) vals[k] = URL_KEYS.has(k) ? checkUrl(cin[k], k === "LOADER_URL" ? "설치 프로그램 링크" : "노션·디스코드 주소") : one(cin[k]);
  if (!["", "nightfall"].includes(vals.MOOD)) vals.MOOD = "";
  if (vals.TOPBAR_UNTIL && !/^\d{4}-\d{2}-\d{2}$/.test(vals.TOPBAR_UNTIL)) throw new HttpError(400, "띠 표시 기한은 2026-10-03 같은 날짜로 넣어 주세요");
  if (!vals.SITE_TITLE) throw new HttpError(400, "사이트 제목은 비워둘 수 없어요");
  const sin = data.season || {};
  const candidates = (sin.candidates || []).map((c, n) => {
    const i = n + 1, name = one(c.name, 60);
    if (!name) throw new HttpError(400, `${i}번 후보의 이름이 비어 있어요`);
    return {
      name, pack: one(c.pack, 80), stars: Math.max(0, Math.min(5, parseInt(c.stars) || 0)), weeks: one(c.weeks, 20),
      tags: (c.tags || []).map(t => one(t, 30)).filter(Boolean).slice(0, 4),
      videos: (c.videos || []).filter(v => one(v)).map(v => checkUrl(v, `${i}번 후보의 영상 주소`)).slice(0, 5),
      ...(c.winner ? { winner: true } : {}),
      ...(/^(assets\/[\w.-]+|https:\/\/\S+)$/.test(c.image || "") ? { image: c.image } : {}),
    };
  });
  // 당선은 한 명만
  candidates.forEach((c, n) => { if (c.winner && candidates.findIndex(x => x.winner) !== n) delete c.winner; });
  const season = { show: sin.show !== false, title: one(sin.title, 60), badge: one(sin.badge, 20), period: one(sin.period, 60),
                   intro: one(sin.intro, 300), button: one(sin.button, 30), candidates,
                   sub: sin.sub ? { show: sin.sub.show !== false, title: one(sin.sub.title, 40), address: one(sin.sub.address, 120), version: one(sin.sub.version, 20),
                         desc: one(sin.sub.desc, 400), mods: (sin.sub.mods || []).slice(0, 30).map(m => ({ name: one(m.name, 60), desc: one(m.desc, 80) })).filter(m => m.name) } : undefined,
                   past: (sin.past || []).slice(0, 20).map(p => ({ title: one(p.title, 30), name: one(p.name, 60), pack: one(p.pack, 60) })).filter(p => p.name) };

  const [conf, seasonFile] = await Promise.all([gh.file("site.conf"), gh.file("season.json")]);
  const lines = conf.text.replace(/\n$/, "").split("\n"), seen = new Set();
  lines.forEach((line, n) => {
    const m = /^\s*([A-Z_]+)\s*=/.exec(line);
    if (m && m[1] in vals) { lines[n] = `${m[1]}=${quote(vals[m[1]])}`; seen.add(m[1]); }
  });
  let at = lines.findIndex(l => l.startsWith("# GitHub")); if (at < 0) at = lines.length;
  for (const k of CONF_KEYS) if (!seen.has(k)) lines.splice(at++, 0, `${k}=${quote(vals[k])}`);
  const confText = lines.join("\n") + "\n", seasonText = JSON.stringify(season, null, 2) + "\n";
  if (confText !== conf.text) await gh.put("site.conf", confText, conf.sha, "사이트 내용 수정");
  if (seasonText !== seasonFile.text) await gh.put("season.json", seasonText, seasonFile.sha, "투표 후보 수정");
  return getContent(gh);
}

/* ---------------- 올리기 ---------------- */

async function publish(gh) {
  const cur = await lastRun(gh);
  if (cur.running) return cur;
  // 목록에서 빠진 모드 파일은 이제 정리한다 (되돌리기는 올리기 전까지만 가능)
  const { data } = await readStore(gh);
  const keep = new Set(data.mods.map(m => m.file));
  for (const k of Object.keys(SLOTS)) if (data[k]) keep.add(data[k].file);
  const rel = await gh.store();
  for (const a of await gh.assets(rel)) {
    if (!keep.has(a.name)) await gh.call(`/releases/assets/${a.id}`, { method: "DELETE" });
  }
  await gh.call(`/actions/workflows/${WORKFLOW}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main" }) });
  return { ...cur, running: true, ok: null };
}
