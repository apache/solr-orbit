# Documentation Maintenance Guide

This directory contains the source for the [Apache Solr Benchmark documentation site](https://janhoy.github.io/solr-benchmark/),
built with [Jekyll](https://jekyllrb.com/) and the [just-the-docs](https://just-the-docs.com/) theme.

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

This installs Jekyll 4.4.1 and the just-the-docs 0.12.0 gem into the local bundle.

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

These come from the just-the-docs theme gem's own SCSS files and are **harmless** — the CSS compiles correctly. They are a known issue upstream and can be ignored until just-the-docs migrates its SCSS from `@import` to `@use`.

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
├── glossary.md
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

The documentation is published automatically to **GitHub Pages** via the GitHub Actions workflow
at `.github/workflows/docs.yml`.

**Trigger**: every push to the `main` branch.

**Steps in the workflow**:
1. Check out the repository.
2. Install Ruby 3.3 and run `bundle install` (gems are cached between runs).
3. `actions/configure-pages` injects the correct `baseurl` for GitHub Pages.
4. `bundle exec jekyll build` generates the static site.
5. The `docs/_site/` directory is uploaded as a Pages artifact and deployed.

The live site URL is: **https://janhoy.github.io/solr-benchmark/**

No manual deployment step is needed — merge to `main` and the site updates within a few minutes.
