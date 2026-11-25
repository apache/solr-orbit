# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""The built site is self-contained and actually wired up.

These assertions are cheap and catch the class of mistake that only shows up in
a browser: a renamed data file, a script that is not referenced, a vendored
library that did not ship.
"""

import json
import re
import shutil
import subprocess
import urllib.request

import pytest

from solrorbit.tools.reportr import builder, serve
from solrorbit.tools.reportr import config as config_module


@pytest.fixture
def site(storage, tmp_path):
    config = config_module.load(None, overrides={
        "storage.path": str(storage), "site.out": str(tmp_path / "site")})
    builder.build(config)
    return tmp_path / "site"


class TestSelfContained:
    def test_nothing_is_loaded_from_a_third_party(self, site):
        """No CDN for the charting library, no webfont, no analytics.

        Checks what the browser would actually *fetch* -- script, stylesheet and
        image sources -- rather than any mention of a URL, since an SVG's xmlns
        and the licence header are text, not requests.
        """
        html = (site / "index.html").read_text()
        loaded = re.findall(r'(?:src|href)="([^"#]+)"', html)
        external = [u for u in loaded if u.startswith(("http://", "https://"))]
        # A plain <a href> to the project is a link the reader may click, not a load.
        fetched = [u for u in external if not re.search(r'<a [^>]*href="' + re.escape(u), html)]
        assert fetched == [], f"the page would fetch {fetched} from elsewhere"

    def test_echarts_is_vendored_and_whole(self, site):
        vendored = site / "vendor" / "echarts.min.js"
        assert vendored.stat().st_size > 500_000, "looks truncated"
        assert "echarts" in vendored.read_text(errors="ignore")[:4000].lower()

    def test_echarts_carries_its_apache_licence(self, site):
        head = (site / "vendor" / "echarts.min.js").read_text(errors="ignore")[:1500]
        assert "Apache" in head and "License" in head

    def test_the_html_references_the_assets_it_ships(self, site):
        html = (site / "index.html").read_text()
        for asset in ("style.css", "app.js", "vendor/echarts.min.js"):
            assert asset in html, f"{asset} is shipped but never referenced"
            assert (site / asset).exists()


class TestWiring:
    def test_every_element_the_script_looks_up_exists(self, site):
        html = (site / "index.html").read_text()
        app = (site / "app.js").read_text()
        for element_id in sorted(set(re.findall(r'el\("([a-z-]+)"\)', app))):
            assert f'id="{element_id}"' in html, f'app.js reads #{element_id}, which the page lacks'

    def test_the_catalogue_points_at_files_that_exist(self, site):
        index = json.loads((site / "data" / "index.json").read_text())
        for workload in index["workloads"]:
            assert (site / workload["file"]).exists()

    def test_every_plotted_run_has_a_report_to_open(self, site):
        # Click-through fetches reports/<run-id>.json; a missing one is a dead click.
        payload = json.loads((site / "data" / "nyc_taxis.json").read_text())
        run_ids = {p["run_id"] for s in payload["series"] for p in s["points"]}
        for run_id in run_ids:
            assert (site / "reports" / f"{run_id}.json").exists(), f"{run_id} has no report"

    def test_every_point_names_a_line_the_payload_defines(self, site):
        payload = json.loads((site / "data" / "nyc_taxis.json").read_text())
        defined = set(payload["lines"])
        for entry in payload["series"]:
            for point in entry["points"]:
                assert point["line"] in defined


class TestServing:
    def test_serves_the_site_over_http(self, site):
        with serve.background_server(site) as port:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/index.html", timeout=10) as response:
                assert response.status == 200
                assert b"Apache Solr Benchmarks" in response.read()
            with urllib.request.urlopen(f"{base}/data/index.json", timeout=10) as response:
                assert json.loads(response.read())["workloads"]

    def test_serves_the_data_and_reports_a_click_needs(self, site):
        payload = json.loads((site / "data" / "nyc_taxis.json").read_text())
        run_id = payload["series"][0]["points"][0]["run_id"]
        with serve.background_server(site) as port:
            url = f"http://127.0.0.1:{port}/reports/{run_id}.json"
            with urllib.request.urlopen(url, timeout=10) as response:
                assert "launchr" in json.loads(response.read())


class TestReadability:
    """The chart must be legible without hovering, and say how to drive it."""

    def test_the_solr_version_is_on_the_axis_not_on_every_point(self, site):
        # Every line crossing a date ran the same release, so labelling points
        # repeated the version once per series and once per task.
        app = (site / "app.js").read_text()
        assert "versionTicks" in app, "the version belongs to a tick on the x-axis"
        assert "customValues" in app, "ticks must land on releases, not on round dates"
        assert "hideOverlap" in app, "labels must thin out rather than overlap"

    def test_version_labels_stand_upright(self, site):
        # Laid flat, a version string is wider than the gap between releases.
        app = (site / "app.js").read_text()
        assert "rotate: -90" in app

    def test_both_x_axes_zoom_together(self, site):
        # A version tick that drifts off its date is worse than no tick at all.
        app = (site / "app.js").read_text()
        assert "xAxisIndex: [0, 1]" in app

    def test_charts_offer_a_box_zoom_and_a_reset(self, site):
        # The site is static and cannot re-slice server-side, so zoom is how a
        # reader narrows in.
        app = (site / "app.js").read_text()
        assert "toolbox" in app and "dataZoom" in app and "restore" in app

    def test_box_zoom_is_armed_without_reaching_for_the_toolbox(self, site):
        app = (site / "app.js").read_text()
        assert "dataZoomSelectActive: true" in app, "box zoom must be on from the start"

    def test_plain_scrolling_belongs_to_the_page(self, site):
        # ECharts' inside-zoom swallows the wheel whenever the pointer is over a
        # chart, so a page of charts could not be scrolled past. Box zoom and the
        # slider cover zooming between them.
        app = (site / "app.js").read_text()
        assert 'type: "inside"' not in app, "an inside dataZoom takes the page's wheel"
        assert 'type: "slider"' in app

    def test_each_panel_toggles_its_own_lines(self, site):
        # Lines are the panel's own business, switched in its legend rather than
        # from a control panel somewhere above.
        app = (site / "app.js").read_text()
        assert "legend:" in app and "selected" in app

    def test_sections_fold_from_their_own_heading(self, site):
        # Panels are not a list of tasks, so they do not belong in a chip row
        # that grows a line for every one of them.
        app = (site / "app.js").read_text()
        assert "toggleSection" in app
        assert "reportr.collapsed." in app, "a folded section should stay folded"

    def test_every_section_is_linkable_not_just_featured_ones(self, site):
        # "Look at the query charts for nyc_taxis" is a link someone sends.
        app = (site / "app.js").read_text()
        assert "sectionAnchorId" in app and "sectionSlug" in app

    def test_a_shared_chart_lists_every_task_of_its_kind(self, site):
        # Opening with a subset is a default, not a ceiling: a reader comparing
        # one query against another should not have to leave the chart.
        app = (site / "app.js").read_text()
        assert "unitsFor(metric, tasksFor(metric, ofKind))" in app, \
            "the chart should carry every task of its kind"
        assert "open: new Set(open)" in app, "and merely open with some of them"

    def test_queries_pushed_for_throughput_are_charted_on_it(self, site):
        # A query held at a fixed request rate says nothing through its
        # throughput; one pushed as hard as it goes says everything.
        app = (site / "app.js").read_text()
        assert "measureOf" in app and "task_measures" in app

    def test_annotations_are_drawn_where_they_belong(self, site):
        app = (site / "app.js").read_text()
        assert "annotationMarkLine" in app
        assert "annotationTooltip" in app, "a marker nobody can read explains nothing"

    def test_the_chips_are_tasks_the_run_measured(self, site):
        # Not panels, not metrics: a chip is a thing the benchmark did.
        app = (site / "app.js").read_text()
        assert "buildTaskChips" in app
        assert "state.data.tasks" in app

    def test_any_chip_gives_its_task_a_chart_of_its_own(self, site):
        # A chip that meant "own chart" for the tasks a workload featured and
        # "another line" for everything else was one gesture with two outcomes.
        app = (site / "app.js").read_text()
        assert "ofKind.filter((task) => state.tasks.has(task))" in app
        assert "isFeatured" not in app, "featuring decides what starts on, not what is possible"

    def test_a_shared_chart_does_not_redraw_a_line_that_has_its_own_chart(self, site):
        app = (site / "app.js").read_text()
        assert "state.defaults.has(task) && !state.tasks.has(task)" in app

    def test_a_bookmarked_chart_switches_itself_on(self, site):
        # The chips are the reader's own selection and a bookmark carries none
        # of it, so a link to a task's chart has to produce that chart rather
        # than land on a section that was never built.
        app = (site / "app.js").read_text()
        assert "ensureCharted" in app

    def test_a_bookmarked_chart_unfolds_the_section_holding_it(self, site):
        # Landing on a collapsed heading is the same disappointment as landing
        # on nothing.
        app = (site / "app.js").read_text()
        assert "revealSection" in app

    def test_a_point_is_not_assumed_to_be_a_release(self, site):
        # A run can be a nightly or somebody's build from source, and calling
        # either one by a bare version number would be a lie.
        app = (site / "app.js").read_text()
        assert "pointLabel" in app
        assert "buildNoun" in app, "the page should not say 'release' of a snapshot"
        assert '"Release over release"' not in app

    def test_a_panel_does_not_name_its_tasks_twice(self, site):
        # The legend names them; the subtitle used to as well.
        app = (site / "app.js").read_text()
        assert 'group.map((s) => s.task).join(", ")' not in app

    def test_toolbox_hints_do_not_sit_under_the_pointer(self, site):
        # ECharts' built-in titles render beneath the cursor, hiding the button.
        app = (site / "app.js").read_text()
        assert "showTitle: false" in app
        assert "TOOL_TITLES" in app, "the toolbox needs readable labels of its own"

    def test_the_page_explains_how_to_drive_the_charts(self, site):
        html = (site / "index.html").read_text()
        assert 'id="howto"' in html
        for behaviour in ("Hover", "Click", "Drag a box", "Drag the slider", "Reset",
                          "Show or hide one line", "Fold a section", "link to one"):
            assert behaviour in html, f"the how-to panel does not mention {behaviour}"

    def test_a_singled_out_task_sits_inside_its_kind(self, site):
        # "range" is one of the queries, not a peer of "Query": a top-level
        # section for it read as though it were a third kind of work.
        app = (site / "app.js").read_text()
        assert "subHead" in app
        assert '["query", "lifecycle", "indexing"]' in app, "queries lead, indexing keeps"

    def test_the_legend_does_not_share_a_line_with_the_zoom_buttons(self, site):
        # A workload with seven query tasks ran its legend straight through the
        # toolbox; reserving a fixed strip only moves the collision to the next
        # workload with longer task names.
        app = (site / "app.js").read_text()
        assert 'type: "scroll", top: 26, left: 0, right: 0' in app


class TestNothingReportDerivedIsMarkup:
    """Report text is data, and the site must render it as text.

    Reports are written by whoever ran the benchmark, and hints and release
    notes come from other repositories; for a publicly served site an
    unescaped value is stored XSS. These run the real helpers out of app.js
    under node, which is the only way to check the escaping rather than its
    spelling.
    """

    HOSTILE = "<img src=x onerror=alert(document.domain)>"

    @staticmethod
    def _helpers(app_js: str) -> str:
        names = ["const HTML_ESCAPES", "function esc(", "function safeUrl(",
                 "function markup(", "function code(", "function section("]
        out = []
        for name in names:
            start = app_js.index(name)
            end = app_js.index("\n}", start) + 2 if name.startswith("function") \
                else app_js.index("\n", start)
            out.append(app_js[start:end])
        return "\n".join(out)

    def _run(self, site, script: str) -> str:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed")
        app_js = (site / "app.js").read_text(encoding="utf-8")
        source = self._helpers(app_js) + "\n" + script
        result = subprocess.run([node, "-e", source], capture_output=True, text=True,
                                timeout=60, check=False)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_a_hostile_value_is_escaped_everywhere_it_is_rendered(self, site):
        out = self._run(site, f"""
          const hostile = {self.HOSTILE!r};
          console.log(JSON.stringify([
            esc(hostile),
            section("Cluster config", [["Name", hostile]]),
            section("X", [[hostile, "v"]]),
            code(hostile).html,
          ]));
        """)
        for rendered in json.loads(out):
            assert "<img" not in rendered

    def test_a_benign_value_is_unchanged(self, site):
        out = self._run(site, """
          console.log(JSON.stringify([esc("nyc_taxis p90"), esc("a & b"), code("SOLR_HEAP=4g").html]));
        """)
        plain, amp, marked = json.loads(out)
        assert plain == "nyc_taxis p90"
        assert amp == "a &amp; b"
        assert marked == "<code>SOLR_HEAP=4g</code>"

    def test_a_release_note_link_is_http_only(self, site):
        out = self._run(site, """
          console.log(JSON.stringify([safeUrl("javascript:alert(1)"), safeUrl("https://example.org/x")]));
        """)
        blocked, allowed = json.loads(out)
        assert blocked is None
        assert allowed == "https://example.org/x"
