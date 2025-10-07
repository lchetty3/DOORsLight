# --- file: generate_site.py
"""
DOORS CSV → Static HTML generator (v2, no ModulePath)

Reads hierarchy.yaml + per-module CSVs (requirements.csv, tests.csv) and generates a
static site with:
  • index.html (level selector)
  • level pages (System / Subsystem / Component)
  • per-requirement detail pages (incoming/outgoing links + consolidated test status)
  • per-module link editor pages (editable OutgoingLinks with CSV export)

Usage:
    python generate_site.py --exports ./exports --out ./site --project-name "ProjX"
"""
from __future__ import annotations
import argparse, csv, html, os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Set

import yaml  # pip install pyyaml

@dataclass
class ModuleInfo:
    name: str
    abbrev: str
    level: str
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

def parse_external_id(eid: str):
    parts = eid.strip().split("-")
    if len(parts) < 3: raise ValueError(f"Invalid ExternalID: {eid}")
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

def load_hierarchy(path: Path) -> Dict[str, ModuleInfo]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    modules: Dict[str, ModuleInfo] = {}
    for m in data.get("modules", []):
        mi = ModuleInfo(
            name=m["name"],
            abbrev=m["abbrev"],
            level=m["level"],
            requirements_module=m["requirements_module"],
            tests_module=m["tests_module"],
            parent_abbrev=m.get("parent_abbrev"),
        )
        modules[mi.abbrev] = mi
    return modules

def read_csv_rows(csv_path: Path):
    rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = { (k or "").strip(): (v or "").strip() for k, v in row.items() }
            rows.append(cleaned)
    return rows

def discover_module_files(exports_root: Path):
    req_files, test_files = [], []
    for p in exports_root.rglob("*.csv"):
        if p.name.lower() == "requirements.csv": req_files.append(p)
        elif p.name.lower() == "tests.csv": test_files.append(p)
    return sorted(req_files), sorted(test_files)

def load_project(exports_root: Path, hierarchy_path: Path, project_name: str) -> Project:
    modules = load_hierarchy(hierarchy_path)
    req_files, test_files = discover_module_files(exports_root)
    requirements, tests = {}, {}

    for rf in req_files:
        for row in read_csv_rows(rf):
            eid = row.get("ExternalID","")
            if not eid: continue
            mod, sd, counter = parse_external_id(eid)
            incoming = [t.strip() for t in row.get("IncomingLinks","").split(";") if t.strip()]
            outgoing = [t.strip() for t in row.get("OutgoingLinks","").split(";") if t.strip()]
            requirements[eid] = Requirement(
                external_id=eid, abbrev=mod, sd=sd, counter=counter,
                heading=row.get("Heading",""), text=row.get("ObjectText",""),
                incoming=incoming, outgoing=outgoing
            )

    for tf in test_files:
        for row in read_csv_rows(tf):
            eid = row.get("ExternalID","")
            if not eid: continue
            mod, sd, counter = parse_external_id(eid)
            if sd != "AT": continue
            tests[eid] = TestCase(
                external_id=eid, abbrev=mod, counter=counter,
                text=row.get("ObjectText",""),
                result=row.get("TestResult","Not Run"),
                additional=row.get("Additional Information","")
            )

    proj = Project(project_name=project_name, modules=modules, requirements=requirements, tests=tests)
    proj.build_graph()
    return proj

def write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def escape(s: str) -> str: return html.escape(s, quote=True)
def truncate(s: str, n:int=200) -> str: s=s.strip(); return (s[:n]+"…") if len(s)>n else s

def badge(label: str) -> str:
    cls = {
        "All Pass":"badge pass","Any Fail":"badge fail","Has Not Run":"badge warn",
        "Partial":"badge warn","No Tests":"badge mute","Mixed":"badge info",
    }.get(label,"badge info")
    return f'<span class="{cls}">{escape(label)}</span>'

def requirement_url(eid: str) -> str: return f"requirements/{eid.replace('/','_')}.html"
def module_edit_url(mod: str) -> str: return f"edit/edit-{mod}.html"
def level_url(level: str) -> str: return f"levels/{level.lower()}.html"

def layout(title: str, body: str, project_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(project_name)} · {escape(title)}</title>
  <link rel="stylesheet" href="style.css" />
  <script defer src="app.js"></script>
</head>
<body>
<header class="site-header">
  <div class="brand">{escape(project_name)}</div>
  <nav>
    <a href="index.html">Home</a>
    <a href="{level_url('System')}">System</a>
    <a href="{level_url('Subsystem')}">Subsystem</a>
    <a href="{level_url('Component')}">Component</a>
    <a href="edit/index.html">Edit Links</a>
  </nav>
</header>
<main class="container">
{body}
</main>
<footer class="site-footer">Generated by DOORS CSV → HTML generator</footer>
</body>
</html>
"""

def render_index(proj, out_root: Path):
    cards = []
    for lvl in ("System","Subsystem","Component"):
        cards.append(f"<a class='card' href='{level_url(lvl)}'><h3>{escape(lvl)} view</h3><p>Browse {escape(lvl.lower())} requirements and rollups.</p></a>")
    mods = "".join(f"<li><strong>{escape(m.abbrev)}</strong> — {escape(m.name)} ({escape(m.level)}) · <a href='{module_edit_url(m.abbrev)}'>edit links</a></li>" for m in proj.modules.values())
    body = f"""
    <h1>Project overview</h1>
    <div class='cards'>{{cards}}</div>
    <section><h2>Modules</h2><ul>{mods}</ul></section>
    """.replace("{cards}","".join(cards))
    write_text(out_root/"index.html", layout("Overview", body, proj.project_name))

def group_requirements_by_level(proj):
    level_map = {"System":[], "Subsystem":[], "Component":[]}
    for r in proj.requirements.values():
        m = proj.modules.get(r.abbrev)
        if not m: continue
        level_map.setdefault(m.level, []).append(r)
    for lvl in level_map:
        level_map[lvl].sort(key=lambda r: (r.abbrev, r.sd, int(r.counter) if r.counter.isdigit() else r.counter))
    return level_map

def render_level_pages(proj, out_root: Path):
    grouped = group_requirements_by_level(proj)
    for lvl, reqs in grouped.items():
        rows = []
        for r in reqs:
            label, _, _ = proj.tests_rollup(r.external_id)
            inc = " ".join(f"<a href='{requirement_url(e)}'>{escape(e)}</a>" for e in r.incoming if e in proj.requirements)
            outs_req = [e for e in r.outgoing if e in proj.requirements]
            outs_tst = [e for e in r.outgoing if is_test_id(e)]
            outs_html = ""
            if outs_req: outs_html += "<div><strong>Req:</strong> " + ", ".join(f"<a href='{requirement_url(e)}'>{escape(e)}</a>" for e in outs_req) + "</div>"
            if outs_tst: outs_html += "<div><strong>Tests:</strong> " + ", ".join(escape(e) for e in outs_tst) + "</div>"
            rows.append(f"<tr><td><a href='{requirement_url(r.external_id)}'>{escape(r.external_id)}</a></td><td>{escape(r.heading)}</td><td>{escape(truncate(r.text,180))}</td><td>{inc}</td><td>{outs_html}</td><td>{badge(label)}</td></tr>")
        body = f"""
        <h1>{escape(lvl)} view</h1>
        <input id='tblFilter' placeholder='Filter by ID or text…' oninput='filterTable()' />
        <table id='reqTable' class='table'>
          <thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th><th>Incoming</th><th>Outgoing</th><th>Tests</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
        """
        write_text(out_root/level_url(lvl), layout(f"{lvl} view", body, proj.project_name))

def render_requirement_pages(proj, out_root: Path):
    for r in proj.requirements.values():
        inc_rows, out_rows, test_rows = [], [], []
        for eid in r.incoming:
            rr = proj.requirements.get(eid)
            if rr: inc_rows.append(f"<tr><td><a href='{requirement_url(rr.external_id)}'>{escape(rr.external_id)}</a></td><td>{escape(rr.heading)}</td><td>{escape(truncate(rr.text,200))}</td></tr>")
            else: inc_rows.append(f"<tr class='warn'><td>{escape(eid)}</td><td colspan='2'>Broken link</td></tr>")
        for eid in r.outgoing:
            if is_test_id(eid): continue
            rr = proj.requirements.get(eid)
            if rr: out_rows.append(f"<tr><td><a href='{requirement_url(rr.external_id)}'>{escape(rr.external_id)}</a></td><td>{escape(rr.heading)}</td><td>{escape(truncate(rr.text,200))}</td></tr>")
            else: out_rows.append(f"<tr class='warn'><td>{escape(eid)}</td><td colspan='2'>Broken link</td></tr>")
        direct_tests = [e for e in r.outgoing if is_test_id(e)]
        for tid in direct_tests:
            t = proj.tests.get(tid)
            if t: test_rows.append(f"<tr><td>{escape(t.external_id)}</td><td>{badge(t.result)}</td><td>{escape(truncate(t.text,160))}</td><td>{escape(truncate(t.additional,160))}</td></tr>")
            else: test_rows.append(f"<tr class='warn'><td>{escape(tid)}</td><td colspan='3'>Missing test</td></tr>")
        label, counts, all_tids = proj.tests_rollup(r.external_id)
        counts_html = " ".join(f"<span class='chip'>{escape(k)}: {v}</span>" for k,v in counts.items()) or "<span class='chip'>No tests</span>"
        all_tests_html = ", ".join(escape(tid) for tid in sorted(set(all_tids))) or "—"
        body = f"""
        <h1>{escape(r.external_id)} — {escape(r.heading)}</h1>
        <p class='muted'>{escape(r.text)}</p>
        <section><h2>Consolidated tests {badge(label)}</h2><div class='counts'>{counts_html}</div><div class='muted small'>All associated tests: {all_tests_html}</div></section>
        <div class='grid'>
          <section><h3>Incoming (higher-level)</h3><table class='table'><thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th></tr></thead><tbody>{"".join(inc_rows) or "<tr><td colspan=3>None</td></tr>"}</tbody></table></section>
          <section><h3>Outgoing (lower-level)</h3><table class='table'><thead><tr><th>ExternalID</th><th>Heading</th><th>Text</th></tr></thead><tbody>{"".join(out_rows) or "<tr><td colspan=3>None</td></tr>"}</tbody></table></section>
        </div>
        <section><h3>Direct tests linked to this requirement</h3><table class='table'><thead><tr><th>TestID</th><th>Result</th><th>Procedure</th><th>Notes</th></tr></thead><tbody>{"".join(test_rows) or "<tr><td colspan=4>None</td></tr>"}</tbody></table></section>
        """
        write_text(out_root/requirement_url(r.external_id), layout(r.external_id, body, proj.project_name))

def render_edit_pages(proj, out_root: Path):
    cards, by_mod = [], {}
    for r in proj.requirements.values():
        by_mod.setdefault(r.abbrev, []).append(r)
    for mod, lst in by_mod.items():
        lst.sort(key=lambda r: (r.sd, int(r.counter) if r.counter.isdigit() else r.counter))
        cards.append(f"<a class='card' href='{module_edit_url(mod)}'><h3>{escape(mod)}</h3><p>{len(lst)} requirements</p></a>")
    body = "<h1>Edit links</h1><p>Inline-edit the <code>OutgoingLinks</code> column, then click <em>Download CSV</em> to export an updated module CSV for DOORS re-import.</p><div class='cards'>" + "".join(cards) + "</div>"
    write_text(out_root/"edit"/"index.html", layout("Edit links", body, proj.project_name))

    for mod, reqs in by_mod.items():
        rows = []
        for r in reqs:
            rows.append(f"<tr><td>{escape(r.external_id)}</td><td>{escape(r.heading)}</td><td class='wrap'>{escape(r.text)}</td><td class='code'>{escape(';'.join(r.incoming))}</td><td class='code' contenteditable='true' data-initial='{escape(';'.join(r.outgoing))}'>{escape(';'.join(r.outgoing))}</td></tr>")
        body = f"""
        <h1>Edit {escape(mod)} links</h1>
        <div class='toolbar'><button onclick="downloadEditedCSV('reqTable','requirements.csv')">Download CSV</button>
        <input id='tblFilter' placeholder='Filter…' oninput='filterTable()' /></div>
        <table id='reqTable' class='table editable'><thead><tr><th>ExternalID</th><th>Heading</th><th>ObjectText</th><th>IncomingLinks</th><th>OutgoingLinks (editable)</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
        <p class='muted small'>Only the <strong>OutgoingLinks</strong> column is exported as edited; other columns are preserved as shown.</p>
        """
        write_text(out_root/module_edit_url(mod), layout(f"Edit {mod}", body, proj.project_name))

def write_assets(out_root: Path):
    write_text(out_root/"style.css", DEFAULT_CSS)
    write_text(out_root/"app.js", DEFAULT_JS)

DEFAULT_CSS = """:root{--bg:#0b0c10;--card:#121317;--text:#e5e7eb;--muted:#9aa0a6;--accent:#60a5fa;--pass:#22c55e;--fail:#ef4444;--warn:#f59e0b;--info:#38bdf8;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,Noto Sans,sans-serif;}
.container{max-width:1200px;margin:24px auto;padding:0 16px}
.site-header,.site-footer{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:12px 16px;background:#0e1016;border-bottom:1px solid #1f2330}
.site-footer{border-top:1px solid #1f2330;border-bottom:none;opacity:.7}
.site-header a{color:var(--text);opacity:.9;text-decoration:none;margin-right:12px}
.brand{font-weight:700}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin:16px 0}
.card{display:block;background:var(--card);padding:16px;border-radius:14px;border:1px solid #232634;text-decoration:none;color:var(--text)}
.card:hover{border-color:#2f3445}
.table{width:100%;border-collapse:collapse;margin:12px 0;background:var(--card);border-radius:12px;overflow:hidden}
.table th,.table td{border-bottom:1px solid #1f2330;padding:10px 12px;vertical-align:top}
.table thead th{background:#161823;font-weight:600}
.table tr:hover{background:#121420}
input#tblFilter{width:100%;padding:10px 12px;border-radius:10px;border:1px solid #2a2f40;background:#0e1016;color:var(--text);margin:8px 0}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid #2a2f40}
.badge.pass{background:rgba(34,197,94,.15);border-color:rgba(34,197,94,.4)}
.badge.fail{background:rgba(239,68,68,.15);border-color:rgba(239,68,68,.4)}
.badge.warn{background:rgba(245,158,11,.15);border-color:rgba(245,158,11,.4)}
.badge.mute{background:rgba(156,163,175,.15);border-color:rgba(156,163,175,.4)}
.badge.info{background:rgba(56,189,248,.15);border-color:rgba(56,189,248,.4)}
.muted{color:var(--muted)}.small{font-size:12px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.editable td[contenteditable]{outline:1px dashed #2a2f40;border-radius:6px}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace}
.wrap{white-space:pre-wrap}
.warn{background:rgba(245,158,11,.08)}
"""
DEFAULT_JS = """function filterTable(){
  const q=(document.getElementById('tblFilter')||{}).value?.toLowerCase()||'';
  const rows=[...document.querySelectorAll('#reqTable tbody tr')];
  rows.forEach(r=>{const t=r.innerText.toLowerCase(); r.style.display = t.includes(q)?'':'';});
}
function downloadEditedCSV(tableId, filename){
  const table=document.getElementById(tableId);
  const rows=[...table.querySelectorAll('tbody tr')];
  const headers=['ExternalID','Heading','ObjectText','IncomingLinks','OutgoingLinks'];
  const csv=[headers.join(',')];
  rows.forEach(tr=>{
    const tds=[...tr.children];
    const vals=[0,1,2,3,4].map(i=>escapeCsv(tds[i].innerText.trim()));
    csv.push(vals.join(','));
  });
  const blob=new Blob([csv.join('\\n')],{type:'text/csv;charset=utf-8;'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=filename; document.body.appendChild(a); a.click(); a.remove();
}
function escapeCsv(s){ if(s.includes(',')||s.includes('\"')||s.includes('\\n')){return '\"'+s.replaceAll('\"','\"\"')+'\"';} return s;}
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--project-name", type=str, default="DOORS Project")
    args = ap.parse_args()

    proj = load_project(args.exports, args.exports/"hierarchy.yaml", args.project_name)
    args.out.mkdir(parents=True, exist_ok=True)
    write_assets(args.out)
    render_index(proj, args.out)
    render_level_pages(proj, args.out)
    render_requirement_pages(proj, args.out)
    render_edit_pages(proj, args.out)
    print(f"Site generated at: {args.out}")

if __name__ == "__main__":
    main()
