# Documentation Maintenance Guide

This directory contains the source for the [Apache Solr Orbit documentation site](https://apache.github.io/solr-orbit/),
built with [Jekyll](https://jekyllrb.com/) and a small theme maintained in this directory.

The front matter below (`nav_order`, `parent`, `grand_parent`, `has_children`) looks like
[just-the-docs](https://just-the-docs.com/), but that gem is **not** installed: navigation is rendered by
`_includes/nav.html` in this repository. The differences matter when adding pages — see
[Navigation constraints](#navigation-constraints).

## Prerequisites

- **Ruby 3.3+** — The system Ruby on macOS is often too old. Use [rbenv](https://github.com/rbenv/rbenv) or [RVM](https://rvm.io/):
  ```
  rbenv install 3.3.0
  rbenv local 3.3.0   # sets .ruby-version in docs/
  ```
- **Bundler** — comes with modern Ruby: `gem install bundler`

## First-time Setup

```bash
cd docs
bundle install
```

This installs Jekyll into the local bundle. There is no theme gem; `Gemfile` contains only `jekyll`.

## Local Development

Start a live-reload development server:

```bash
cd docs
bundle exec jekyll serve
```

The site will be available at `http://localhost:4000/`. Jekyll watches for file changes and rebuilds automatically.

To verify the build before pushing:

```bash
bundle exec jekyll build
```

The generated site is written to `docs/_site/` (git-ignored).

### Sass deprecation warnings

You will see many warnings like:

```
DEPRECATION WARNING [import]: Sass @import rules are deprecated and will be removed in Dart Sass 3.0.0.
```

These come from Sass's deprecation of `@import` and are **harmless** — the CSS compiles correctly.

## Navigation constraints

`_includes/nav.html` builds the sidebar, and four of its properties are easy to fall foul of:

- **Exactly three levels render.** A root page (no `parent`), its children (`parent: <root title>`), and
  their grandchildren (`parent: <child title>` *and* `grand_parent: <root title>`). A fourth level is
  silently not rendered.
- **`nav_order` is mandatory.** A page without one is absent from the sidebar *and* from `search.json`.
  It is not a default-to-the-end — it is invisible.
- **`parent` and `grand_parent` match by exact page `title`, not by path.** Page titles must therefore be
  unique across the whole site; two pages sharing a title would collect each other's children.
- **`has_children` is documentary.** The template expands a node when matching children exist, so the
  property is for human readers, not for Jekyll.

## Adding or Editing Pages

Each page is a Markdown file with a YAML front matter block. The minimal required front matter is:

```yaml
---
title: My Page Title
nav_order: 10
---
```

For pages nested under a section, add `parent` and optionally `grand_parent`:

```yaml
---
title: Running a Workload
parent: Working with Workloads
grand_parent: User Guide
nav_order: 9
---
```

To create a section that has child pages, add `has_children: true` to its `index.md`.

Navigation order is controlled by `nav_order` — lower numbers appear first in the sidebar.

### Internal links

Jekyll generates `.html` files (not directory-style pretty URLs), so internal cross-page links must use the `.html` extension:

```markdown
See [Available Configs](available-configs.html) for details.
See [Telemetry Devices](../../reference/telemetry.html) for full documentation.
```

Do **not** use `.md` extensions in links — they resolve to the source file, not the built page.

### Important: Jinja2 / Liquid Escaping

Jekyll processes Liquid template tags (`{{ }}` and `{% %}`) in all Markdown files, including
inside fenced code blocks. When documenting workload files that use Jinja2 syntax, wrap the
code block with `{% raw %}` and `{% endraw %}`:

````
{% raw %}
```json
{ "bulk_size": {{ bulk_size | default(500) }} }
```
{% endraw %}
````

## Site Structure

```
docs/
├── _config.yml                  ← Site title, theme, nav settings
├── Gemfile                      ← Ruby gem dependencies
├── index.md                     ← Home page
├── quickstart.md
├── faq.md
├── about.md                     ← License, attribution, trademarks
├── _includes/
│   └── footer_custom.html       ← ASF copyright footer (applied to every page)
├── user-guide/
├── reference/
├── cluster-config/
└── converter/
```

## Publishing

The documentation is published to **GitHub Pages** by the ASF's own tooling, configured in
[`.asf.yaml`](../.asf.yaml) at the repository root:

```yaml
github:
  ghp_branch: main
  ghp_path: /docs
```

**Trigger**: every push to the `main` branch. Infrastructure builds the Jekyll site from `docs/` and
deploys it; there is no GitHub Actions workflow involved.

`.github/workflows/docs-lint.yml` runs on pull requests and checks the Markdown, but it does not publish.

The live site URL is: **https://apache.github.io/solr-orbit/**

No manual deployment step is needed — merge to `main` and the site updates within a few minutes.
