# DOORS CSV → Static HTML generator (v4)
# 5‑level hierarchy + inline JS + robust filter/theme + tooltips
#
# What changed
# • Levels are now dynamic and driven by `hierarchy.yaml: levels:`.
#   Example: ["User Requirement", "System Requirement", "Subsystem", "Module", "Submodule"].
# • Navigation and level pages are generated for *all* levels in that list, in order.
# • Filenames for level pages are slugged (spaces → underscores, lowercased), e.g.
#   levels/system_requirement.html.
# • Keeps hover tooltips for requirement links, test roll‑ups, link editor, and inline JS.
# • CSV schemas unchanged (no ModulePath column; links in Incoming/Outgoing).
#
# Usage
#   pip install pyyaml
#   python generate_site.py --exports ./exports --out ./site --project-name "Your Project"

from __future__ import annotations
import argparse, csv, html, re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set
import yaml  # pip install pyyaml

# ─────────────────────────── Data model ───────────────────────────
@dataclass
class ModuleInfo:
    name: str
    abbrev: str
    level: str                # e.g., "User Requirement", "System Requirement", ...
    requirements_module: str
    tests_module: str
    parent_abbrev: Optional[str] = None

@dataclass
class Requirement:
    external_id: str
    abbrev: str
    sd: str
    counter: str
    heading: str
    text: str
    incoming: List[str] = field(default_factory=list)
    outgoing: List[str] = field(default_factory=list)

@dataclass
class TestCase:
    external_id: str
    abbrev: str
    counter: str
    text: str
    result: str = "Not Run"
    additional: str = ""

@dataclass
class Project:
    project_name: str
    levels: List[str]
    modules: Dict[str, ModuleInfo]
    requirements: Dict[str, Requirement]
    tests: Dict[str, TestCase]
    req_children: Dict[str, List[str]] = field(default_factory=dict)
    req_tests: Dict[str, List[str]] = field(default_factory=dict)

    def build_graph(self) -> None:
        self.req_children = {rid: [] for rid in self.requirements}
        self.req_tests = {rid: [] for rid in self.requirements}
        for rid, req in self.requirements.items():
            for tgt in req.outgoing:
                if is_test_id(tgt):
                    self.req_tests[rid].append(tgt)
                elif tgt in self.requirements:
                    self.req_children[rid].append(tgt)

    def descendants(self, rid: str) -> Set[str]:
        seen: Set[str] = set()
        stack = list(self.req_children.get(rid, []))
        while stack:
            cur = stack.pop()
            if cur in seen: continue
            seen.add(cur)
            stack.extend(self.req_children.get(cur, []))
        return seen

    def tests_rollup(self, rid: str) -> Tuple[str, Dict[str, int], List[str]]:
        ids: List[str] = []
        ids.extend(self.req_tests.get(rid, []))
        for child in self.descendants(rid):
            ids.extend(self.req_tests.get(child, []))
        counts: Dict[str, int] = {}
        for tid in ids:
            tc = self.tests.get(tid)
            res = (tc.result if tc else "Missing").strip() or "Not Run"
            counts[res] = counts.get(res, 0) + 1
        label = summarize_counts(counts, len(ids))
        return label, counts, ids

# ─────────────────────────── Helpers ───────────────────────────
def parse_external_id(eid: str):
    parts = eid.strip().split("-")
    if len(parts) < 3:
        raise ValueError(f"Invalid ExternalID: {eid}")
    return parts[0], parts[1], "-".join(parts[2:])

def is_test_id(eid: str) -> bool:
    try:
        _, sd, _ = parse_external_id(eid)
        return sd == "AT"
    except Exception:
        return False

def summarize_counts(counts: Dict[str, int], total: int) -> str:
    if total == 0: return "No Tests"
    if counts.get("Fail",0) > 0: return "Any Fail"
    if counts.get("Partial",0) > 0: return "Partial"
    if counts.get("Not Run",0) > 0: return "Has Not Run"
    if counts.get("Pass",0) == total: return "All Pass"
    return "Mixed"

def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")

# ─────────────────────────── Loading ───────────────────────────
def load_hierarchy(path: Path) -> Tuple[List[str], Dict[str, ModuleInfo]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    levels: List[str] = data.get("levels") or []
    modules: Dict[str, ModuleInfo] = {}
    for m in data.get("modules", []):
        mi = ModuleInfo(
            name=m["name"], abbrev=m["abbrev"], level=m["level"],
            requirements_module=m["requirements_module"], tests_module=m["tests_module"],
            parent_abbrev=m.get("parent_abbrev"),
        )
        modules[mi.abbrev] = mi
    # If levels list isn't provided, derive order from modules (stable sort by appearance)
    if not levels:
        seen = []
        for mi in modules.values():
            if mi.level not in seen:
                seen.append(mi.level)
        levels = seen
    return levels, modules

def read_csv_rows(csv_path: Path):
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows

def discover_module_files(exports_root: Path):
    req_files, test_files = [], []
    for p in exports_root.rglob("*.csv"):
        if p.name.lower() == "requirements.csv": req_files.append(p)
        elif p.name.lower() == "tests.csv": test_files.append(p)
    return sorted(req_files), sorted(test_files)

def load_project(exports_root: Path, hierarchy_path: Path, project_name: str) -> Project:
    levels, modules = load_hierarchy(hierarchy_path)
    req_files, test_files = discover_module_files(exports_root)
    requirements: Dict[str, Requirement] = {}
    tests: Dict[str, TestCase] = {}

    for rf in req_files:
        for row in read_csv_rows(rf):
            eid = row.get("ExternalID", "")
            if not eid: continue
            mod, sd, counter = parse_external_id(eid)
            incoming = [t.strip() for t in (row.get("IncomingLinks", "") or "").split(";") if t.strip()]
            outgoing = [t.strip() for t in (row.get("OutgoingLinks", "") or "").split(";") if t.strip()]
            requirements[eid] = Requirement(
                external_id=eid, abbrev=mod, sd=sd, counter=counter,
                heading=row.get("Heading", ""), text=row.get("ObjectText", ""),
                incoming=incoming, outgoing=outgoing,
            )

    for tf in test_files:
        for row in read_csv_rows(tf):
            eid = row.get("ExternalID", "")
            if not eid: continue
            mod, sd, counter = parse_external_id(eid)
            if sd != "AT": continue
            tests[eid] = TestCase(
                external_id=eid, abbrev=mod, counter=counter,
                text=row.get("ObjectText", ""), result=row.get("TestResult", "Not Run"),
                additional=row.get("Additional Information", ""),
            )

    proj = Project(project_name=project_name, levels=levels, modules=modules, requirements=requirements, tests=tests)
    proj.build_graph()
    return proj

# ─────────────────────────── Rendering utils ───────────────────────────
def write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def escape(s: str) -> str: return html.escape(s, quote=True)

def truncate(s: str, n:int=320) -> str:
    s=(s or '').strip().replace('\r',' ').replace('\n',' ')
    return (s[:n]+"…") if len(s)>n else s

def make_tip(req: Optional[Requirement]) -> str:
    if not req: return ""
    combo = (req.heading or "").strip()
    if req.text:
        combo = (combo+" — "+req.text) if combo else req.text
    return escape(truncate(combo, 400))

def badge(label: str) -> str:
    cls = {
        "All Pass":"badge pass","Any Fail":"badge fail","Has Not Run":"badge warn",
        "Partial":"badge warn","No Tests":"badge mute","Mixed":"badge info",
    }.get(label,"badge info")
    return f'<span class="{cls}">{escape(label)}</span>'

def requirement_url(eid: str) -> str: return f"requirements/{eid.replace('/', '_')}.html"

def module_edit_url(mod: str) -> str: return f"edit/edit-{mod}.html"

def level_url(level: str) -> str: return f"levels/{slug(level)}.html"

# Inline JS (no external script), inserted at end of <body>
DEFAULT_INLINE_JS = r"""
(function(){
  // Theme
  var root = document.documentElement; var btn = document.getElementById('themeToggle');
  try{ var saved = localStorage.getItem('doors-theme'); if(saved){ root.setAttribute('data-theme', saved); } }catch(e){}
  if(btn){ btn.addEventListener('click', function(){ var cur=root.getAttribute('data-theme')||'dark'; var next=(cur==='dark')?'light':'dark'; root.setAttribute('data-theme', next); try{localStorage.setItem('doors-theme', next);}catch(e){} }); }
  // Filter (token‑AND across all tables in same section)
  window.filterTable = function(input){ var el=input||document.getElementById('tblFilter'); if(!el) return; var q=(el.value||'').toLowerCase().replace(/\s+/g,' ').replace(/^\s+|\s+$/g,''); var tokens=q?q.split(' '):[]; var scope=el.closest? (el.closest('section')||document):document; var tables=scope.querySelectorAll? scope.querySelectorAll('table.table'):[]; for(var i=0;i<tables.length;i++){ var tb=tables[i].tBodies && tables[i].tBodies[0]; if(!tb) continue; for(var r=0;r<tb.rows.length;r++){ var tr=tb.rows[r]; var text=(tr.innerText||tr.textContent||'').toLowerCase(); var show=true; for(var t=0;t<tokens.length;t++){ if(text.indexOf(tokens[t])===-1){ show=false; break; } } tr.style.display = show? '' : 'none'; } } };
  // CSV export
  window.downloadEditedCSV = function(tableId, filename){ var table=document.getElementById(tableId); if(!table) return; var tb=table.tBodies&&table.tBodies[0]; if(!tb) return; var headers=['ExternalID','Heading','ObjectText','IncomingLinks','OutgoingLinks']; var csv=[headers.join(',')]; for(var i=0;i<tb.rows.length;i++){ var cells=tb.rows[i].cells; var vals=[]; for(var j=0;j<5;j++){ var s=cells[j]? (cells[j].innerText||cells[j].textContent||'') : ''; if(/[",\n]/.test(s)){ s='"'+s.replace(/"/g,'""')+'"'; } vals.push(s); } csv.push(vals.join(',')); } var blob=new Blob([csv.join('\n')],{type:'text/csv;charset=utf-8;'}); var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=filename||'requirements.csv'; document.body.appendChild(a); a.click(); a.remove(); };
  // Auto-bind filters
  function bind(){ var inputs=document.querySelectorAll? document.querySelectorAll('input#tblFilter'):[]; for(var i=0;i<inputs.length;i++){ (function(inp){ inp.addEventListener('input', function(){ window.filterTable(inp); }); })(inputs[i]); } }
  if(document.readyState==='loading'){ document.addEventListener('DOMContentLoaded', bind);} else { bind(); }
})();
"""

# Shared layout (builds nav from project.levels)
def layout(title: str, body: str, project_name: str, levels: List[str], depth: int = 0) -> str:
    p = "../"*depth if depth>0 else ""
    nav_levels = "".join(f"<a href='{p}{level_url(l)}'>{escape(l)}</a>" for l in levels)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{escape(project_name)} · {escape(title)}</title>
  <link rel=\"stylesheet\" href=\"{p}style.css\" />
</head>
<body>
<header class=\"site-header\">
  <div class=\"brand\">{escape(project_name)}</div>
  <nav class=\"nav\">
    <a href=\"{p}index.html\">Home</a>
    {nav_levels}
    <a href=\"{p}edit/index.html\">Edit Links</a>
    <button class=\"btn ghost\" id=\"themeToggle\" title=\"Toggle theme\">◐</button>
  </nav>
</header>
<main class=\"container\">
{body}
</main>
<footer class=\"site-footer\">Generated by DOORS CSV → HTML generator</footer>
<script>{escape(DEFAULT_INLINE_JS)}</script>
</body>
</html>
"""

# ─────────────────────────── Pages ───────────────────────────

def render_index(proj: Project, out_root: Path) -> None:
    depth=0
    cards=[f"<a class='card' href='{level_url(l)}'><h3>{escape(l)}</h3><p>Browse {escape(l.lower())} items and rollups.</p></a>" for l in proj.levels]
    mods = "".join(f"<li><strong>{escape(m.abbrev)}</strong> — {escape(m.name)} ({escape(m.level)}) · <a href='{module_edit_url(m.abbrev)}'>edit links</a></li>" for m in proj.modules.values())
    body=f"""
    <h1>Project overview</h1>
    <div class='cards'>{''.join(cards)}</div>
    <section><h2>Modules</h2><ul>{mods}</ul></section>
    """
    write_text(out_root/"index.html", layout("Overview", body, proj.project_name, proj.levels, depth))


def group_requirements_by_level(proj: Project) -> Dict[str, List[Requirement]]:
    level_map: Dict[str, List[Requirement]] = {l: [] for l in proj.levels}
    for req in proj.requirements.values():
        m = proj.modules.get(req.abbrev)
        if not m: continue
        level_map.setdefault(m.level, []).append(req)
    for lvl, lst in level_map.items():
        lst.sort(key=lambda r:(r.abbrev, r.sd, int(r.counter) if r.counter.isdigit() else r.counter))
    return level_map


def render_level_pages(proj: Project, out_root: Path) -> None:
    depth=1; p="../"
    grouped = group_requirements_by_level(proj)
    for lvl in proj.levels:
        reqs = grouped.get(lvl, [])
        rows=[]
        for r in reqs:
            label,_,_=proj.tests_rollup(r.external_id)
            def link_html(eid: str) -> str:
                rr = proj.requirements.get(eid)
                tip = make_tip(rr)
                return f"<a href='{p}{requirement_url(eid)}' title='{tip}'>{escape(eid)}</a>" if rr else escape(eid)
            inc = " ".join(link_html(e) for e in r.incoming if e in proj.requirements)
            outs_req=[e for e in r.outgoing if e in proj.requirements]
            outs_tst=[e for e in r.outgoing if is_test_id(e)]
            outs_html = (f"<div><strong>Req:</strong> "+", ".join(link_html(e) for e in outs_req)+"</div>" if outs_req else "") \
                        + (f"<div><strong>Tests:</strong> "+", ".join(escape(e) for e in outs_tst)+"</div>" if outs_tst else "")
            rows.append(
                f"<tr><td><a href='{p}{requirement_url(r.external_id)}'>{escape(r.external_id)}</a></td>"
                f"<td>{escape(r.heading)}</td><td>{escape(truncate(r.text,180))}</td>"
                f"<td>{inc}</td><td>{outs_html}</td><td>{badge(label)}</td></tr>"
            )
        body=f"""
        <h1>{escape(lvl)}</h1>
        <input id='tblFilter' placeholder='Filter by ID or text…' oninput='filterTable(this)' />
        <div class='table-wrap'>
          <table id='reqTable' class='table'>
            <thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th><th>Incoming</th><th>Outgoing</th><th>Tests</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
        write_text(out_root/level_url(lvl), layout(lvl, body, proj.project_name, proj.levels, depth))


def render_requirement_pages(proj: Project, out_root: Path) -> None:
    depth=1; p="../"
    for r in proj.requirements.values():
        inc_rows=[]
        for eid in r.incoming:
            rr = proj.requirements.get(eid)
            if rr:
                tip = make_tip(rr)
                inc_rows.append(
                    f"<tr><td><a href='{p}{requirement_url(rr.external_id)}' title='{tip}'>{escape(rr.external_id)}</a></td>"
                    f"<td>{escape(rr.heading)}</td><td>{escape(truncate(rr.text,200))}</td></tr>"
                )
            else:
                inc_rows.append(f"<tr class='warn'><td>{escape(eid)}</td><td colspan='2'>Broken link</td></tr>")
        out_rows=[]
        for eid in r.outgoing:
            if is_test_id(eid):
                continue
            rr = proj.requirements.get(eid)
            if rr:
                tip = make_tip(rr)
                out_rows.append(
                    f"<tr><td><a href='{p}{requirement_url(rr.external_id)}' title='{tip}'>{escape(rr.external_id)}</a></td>"
                    f"<td>{escape(rr.heading)}</td><td>{escape(truncate(rr.text,200))}</td></tr>"
                )
            else:
                out_rows.append(f"<tr class='warn'><td>{escape(eid)}</td><td colspan='2'>Broken link</td></tr>")
        test_rows=[]
        for tid in [e for e in r.outgoing if is_test_id(e)]:
            t=proj.tests.get(tid)
            if t:
                test_rows.append(
                    f"<tr><td>{escape(t.external_id)}</td><td>{badge(t.result)}</td><td>{escape(truncate(t.text,160))}</td><td>{escape(truncate(t.additional,160))}</td></tr>"
                )
            else:
                test_rows.append(f"<tr class='warn'><td>{escape(tid)}</td><td colspan='3'>Missing test</td></tr>")
        label, counts, all_tids = proj.tests_rollup(r.external_id)
        counts_html = " ".join(f"<span class='chip'>{escape(k)}: {v}</span>" for k,v in counts.items()) or "<span class='chip'>No tests</span>"
        all_tests_html = ", ".join(escape(tid) for tid in sorted(set(all_tids))) or "—"
        body=f"""
        <h1>{escape(r.external_id)} — {escape(r.heading)}</h1>
        <p class='muted'>{escape(r.text)}</p>
        <section><h2>Consolidated tests {badge(label)}</h2><div class='counts'>{counts_html}</div><div class='muted small'>All associated tests: {all_tests_html}</div></section>
        <div class='grid'>
          <section>
            <h3>Incoming (higher-level)</h3>
            <div class='table-wrap'><table class='table'><thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th></tr></thead><tbody>{''.join(inc_rows) or '<tr><td colspan=3>None</td></tr>'}</tbody></table></div>
          </section>
          <section>
            <h3>Outgoing (lower-level)</h3>
            <div class='table-wrap'><table class='table'><thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th></tr></thead><tbody>{''.join(out_rows) or '<tr><td colspan=3>None</td></tr>'}</tbody></table></div>
          </section>
        </div>
        <section>
          <h3>Direct tests linked to this requirement</h3>
          <div class='table-wrap'><table class='table'><thead><tr><th>TestID</th><th>Result</th><th>Procedure</th><th>Notes</th></tr></thead><tbody>{''.join(test_rows) or '<tr><td colspan=4>None</td></tr>'}</tbody></table></div>
        </section>
        """
        write_text(out_root/requirement_url(r.external_id), layout(r.external_id, body, proj.project_name, proj.levels, depth))


def render_edit_pages(proj: Project, out_root: Path) -> None:
    depth=1
    cards=[]; by_mod: Dict[str, List[Requirement]] = {}
    for r in proj.requirements.values(): by_mod.setdefault(r.abbrev, []).append(r)
    for mod, lst in by_mod.items():
        lst.sort(key=lambda r:(r.sd, int(r.counter) if r.counter.isdigit() else r.counter))
        cards.append(f"<a class='card' href='../{module_edit_url(mod)}'><h3>{escape(mod)}</h3><p>{len(lst)} requirements</p></a>")
    body = "<h1>Edit links</h1><p>Inline-edit the <code>OutgoingLinks</code> column, then click <em>Download CSV</em> to export an updated module CSV for DOORS re-import.</p><div class='cards'>"+"".join(cards)+"</div>"
    write_text(out_root/"edit"/"index.html", layout("Edit links", body, proj.project_name, proj.levels, depth))

    for mod, reqs in by_mod.items():
        rows=[]
        for r in reqs:
            rows.append(
                f"<tr><td>{escape(r.external_id)}</td><td>{escape(r.heading)}</td><td class='wrap'>{escape(r.text)}</td>"
                f"<td class='code'>{escape(';'.join(r.incoming))}</td>"
                f"<td class='code' contenteditable='true' data-initial='{escape(';'.join(r.outgoing))}'>{escape(';'.join(r.outgoing))}</td></tr>"
            )
        body=f"""
        <h1>Edit {escape(mod)} links</h1>
        <div class='toolbar'>
          <button class='btn' onclick=\"downloadEditedCSV('reqTable','requirements.csv')\">Download CSV</button>
          <input id='tblFilter' placeholder='Filter…' oninput='filterTable(this)' />
        </div>
        <div class='table-wrap'>
          <table id='reqTable' class='table'><thead><tr><th>ExternalID</th><th>Heading</th><th>ObjectText</th><th>IncomingLinks</th><th>OutgoingLinks (editable)</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
        </div>
        <p class='muted small'>Only the <strong>OutgoingLinks</strong> column is exported as edited; other columns are preserved as shown.</p>
        """
        write_text(out_root/module_edit_url(mod), layout(f"Edit {mod}", body, proj.project_name, proj.levels, depth))

# ─────────────────────────── Assets ───────────────────────────

def write_assets(out_root: Path) -> None:
    write_text(out_root/"style.css", DEFAULT_CSS)

DEFAULT_CSS = """:root{--bg:#0b0c10;--surface:#121317;--muted:#9aa0a6;--text:#e5e7eb;--border:#222638;--accent:#60a5fa;--pass:#22c55e;--fail:#ef4444;--warn:#f59e0b;--info:#38bdf8;--shadow:0 6px 18px rgba(0,0,0,.25)}
@media (prefers-color-scheme: light){:root{--bg:#f7f8fb;--surface:#fff;--muted:#5f6774;--text:#111827;--border:#e5e7eb;--shadow:0 6px 18px rgba(0,0,0,.08)}}
:root[data-theme=light]{--bg:#f7f8fb;--surface:#fff;--muted:#5f6774;--text:#111827;--border:#e5e7eb;--shadow:0 6px 18px rgba(0,0,0,.08)}
:root[data-theme=dark]{--bg:#0b0c10;--surface:#121317;--muted:#9aa0a6;--text:#e5e7eb;--border:#222638}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;line-height:1.45}
.container{max-width:1200px;margin:24px auto;padding:0 16px}
.site-header,.site-footer{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--surface);border-bottom:1px solid var(--border)}
.site-footer{border-top:1px solid var(--border);border-bottom:none;opacity:.85;margin-top:24px}.brand{font-weight:700;letter-spacing:.2px}
.nav a{color:var(--text);opacity:.9;text-decoration:none;margin-right:12px}.nav a:hover{opacity:1}
.btn{border:1px solid var(--border);background:transparent;color:var(--text);padding:6px 10px;border-radius:10px;cursor:pointer}.btn:hover{border-color:var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;margin:16px 0}
.card{display:block;background:var(--surface);padding:16px;border-radius:14px;border:1px solid var(--border);text-decoration:none;color:var(--text);box-shadow:var(--shadow);transition:transform .08s ease}.card:hover{transform:translateY(-2px)}
.table-wrap{background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);overflow:auto;max-width:100%}
.table{width:100%;border-collapse:separate;border-spacing:0;min-width:800px}
.table thead th{position:sticky;top:0;background:var(--surface);border-bottom:1px solid var(--border);padding:12px;font-weight:600}
.table td{border-bottom:1px solid var(--border);padding:10px 12px;vertical-align:top}.table tbody tr:nth-child(even){background:rgba(128,128,128,.04)}.table tbody tr:hover{background:rgba(96,165,250,.06)}
input#tblFilter{width:100%;padding:12px;border-radius:12px;border:1px solid var(--border);background:var(--surface);color:var(--text);margin:8px 0;outline:none}input#tblFilter:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(96,165,250,.3)}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid var(--border)}.badge.pass{background:linear-gradient(180deg,rgba(34,197,94,.18),rgba(34,197,94,.10));border-color:rgba(34,197,94,.4)}.badge.fail{background:linear-gradient(180deg,rgba(239,68,68,.18),rgba(239,68,68,.10));border-color:rgba(239,68,68,.4)}.badge.warn{background:linear-gradient(180deg,rgba(245,158,11,.18),rgba(245,158,11,.10));border-color:rgba(245,158,11,.4)}.badge.mute{background:linear-gradient(180deg,rgba(156,163,175,.18),rgba(156,163,175,.10));border-color:rgba(156,163,175,.4)}.badge.info{background:linear-gradient(180deg,rgba(56,189,248,.18),rgba(56,189,248,.10));border-color:rgba(56,189,248,.4)}
.muted{color:var(--muted)}.small{font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.editable td[contenteditable]{outline:1px dashed var(--border);border-radius:6px;background:rgba(96,165,250,.06)}.code{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}.wrap{white-space:pre-wrap}.warn{background:linear-gradient(180deg,rgba(245,158,11,.14),rgba(245,158,11,.08))}
.chip{display:inline-block;padding:2px 8px;border-radius:10px;background:rgba(128,128,128,.15);border:1px solid var(--border);margin-right:6px}
.toolbar{display:flex;gap:8px;align-items:center;margin:8px 0}
@media (max-width: 900px){ .grid{grid-template-columns:1fr} }
@media print{body{background:#fff;color:#000}.site-header,.site-footer,.toolbar,.nav{display:none!important}.card,.table-wrap{box-shadow:none}}
"""

# ─────────────────────────── Entry point ───────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Generate a static HTML site from DOORS CSVs (v4)")
    ap.add_argument("--exports", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project-name", type=str, default="DOORS Project")
    args = ap.parse_args()

    hier = args.exports/"hierarchy.yaml"
    if not hier.exists():
        raise SystemExit(f"Missing hierarchy.yaml at {hier}")

    proj = load_project(args.exports, hier, args.project_name)

    write_assets(args.out)
    render_index(proj, args.out)
    render_level_pages(proj, args.out)
    render_requirement_pages(proj, args.out)
    render_edit_pages(proj, args.out)

    print(f"Site generated at: {args.out}")

if __name__ == "__main__":
    main()
