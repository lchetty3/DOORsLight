# DOORS CSV → HTML demo bundle (v2, no ModulePath)

This bundle contains the example exports and the static-site generator script.

## Quick start
1. Install PyYAML: `pip install pyyaml`
2. Generate the site:
   ```bash
   python src/generate_site.py --exports ./exports --out ./site --project-name "Demo Project"
   ```
3. Open `site/index.html`

## Layout
- `exports/` — CSV/YAML according to the agreed v2 schema (no ModulePath).
- `src/generate_site.py` — static HTML generator with rollups + link editor.
