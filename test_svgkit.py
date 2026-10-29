"""Tests for svgkit. Run: python3 -m unittest test_svgkit.py"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

import svgkit
from svgkit import Box, Diagram

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "testdata")


def svg(body, w=400, h=200):
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" font-size="12">%s</svg>'
            % (w, h, body))


def rules(body):
    return [p.rule for p in svgkit.check_text(svg(body))]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = svgkit.main(list(argv))
    return code, out.getvalue()


class TextWidthTests(unittest.TestCase):
    # widths Chrome measured with getComputedTextLength for the house font at 12 px on macOS
    def test_matches_browser_for_ordinary_text(self):
        for s, bold, chrome in [("measured: 10 min", False, 99.7), ("measured: 10 min", True, 106.8),
                                ("Build server: one clock for every job in the run", False, 259.7),
                                ("Build server: one clock for every job in the run", True, 276.2)]:
            self.assertAlmostEqual(svgkit.text_width(s, 12, bold), chrome, delta=chrome * 0.01)

    def test_scales_with_size(self):
        self.assertAlmostEqual(svgkit.text_width("abc", 24), 2 * svgkit.text_width("abc", 12))

    def test_whitespace_collapses_like_svg(self):
        self.assertEqual(svgkit.text_width("  a   b  "), svgkit.text_width("a b"))

    def test_wide_characters_are_one_em(self):
        self.assertEqual(svgkit.text_width("中文", 12), 24)

    def test_unknown_characters_get_a_default(self):
        self.assertGreater(svgkit.text_width("ŵ"), 0)


class DiagramTests(unittest.TestCase):
    def test_header_has_house_style_and_accessibility(self):
        out = Diagram(760, 100, label="Tom & Jerry").svg()
        root = ET.fromstring(out)
        self.assertEqual(root.get("role"), "img")
        self.assertEqual(root.get("aria-label"), "Tom & Jerry")
        self.assertEqual(root.get("font-family"), svgkit.FONT_FAMILY)
        self.assertEqual(root.get("font-size"), "12")
        self.assertEqual(root.get("viewBox"), "0 0 760 100")
        self.assertIn('<marker id="a"', out)

    def test_label_is_required(self):
        with self.assertRaises(ValueError):
            Diagram(760)

    def test_height_follows_content(self):
        d = Diagram(760, label="x")
        d.rect(10, 10, 100, 100)
        self.assertEqual(ET.fromstring(d.svg()).get("viewBox"), "0 0 760 120")

    def test_text_is_escaped(self):
        d = Diagram(200, 50, label="x")
        d.text(10, 20, "a < b & c's")
        self.assertIn(">a &lt; b &amp; c's</text>", d.svg())
        ET.fromstring(d.svg())

    def test_text_lines(self):
        d = Diagram(200, 80, label="x")
        b = d.text(10, 20, "one\ntwo")
        self.assertIn('y="36"', d.svg())
        self.assertAlmostEqual(b.y2, 36 + svgkit.DESCENT * 12)

    def test_colours_by_kind_name(self):
        d = Diagram(200, 50, label="x")
        d.text(10, 20, "a", "state")
        d.note(10, 40, "b")
        out = d.svg()
        self.assertIn('fill="#0e7c86">a<', out)
        self.assertIn('fill="#6b7280">b<', out)

    def test_box_sized_to_text_fits_it(self):
        d = Diagram(400, label="x")
        b = d.box(10, 10, title="Image worker", subtitle=["resize and crop", "1 CPU, 1 GiB"], kind="app")
        self.assertGreaterEqual(b.w, svgkit.text_width("Image worker", bold=True) + 2 * svgkit.BOX_PAD_X)
        self.assertEqual(d.check(), [])
        self.assertIn('fill="#eef0fd" stroke="#4f46e5"', d.svg())

    def test_box_too_small_is_reported(self):
        d = Diagram(400, label="x")
        d.box(100, 10, 60, 40, title="Image worker")
        self.assertEqual([p.rule for p in d.check()], ["text-overflow"])

    def test_box_text_is_centred(self):
        d = Diagram(400, label="x")
        d.box(10, 10, 100, 30, title="topic")
        self.assertIn('<text x="60" y="29" text-anchor="middle" font-weight="700"', d.svg())

    def test_emphasis_colours_title_and_thickens_border(self):
        d = Diagram(400, label="x")
        d.box(10, 10, title="Metrics", kind="state", emphasis=True)
        out = d.svg()
        self.assertIn('stroke-width="1.5"', out)
        self.assertIn('font-weight="700" fill="#0e7c86">Metrics', out)

    def test_box_size_matches_box(self):
        d = Diagram(400, label="x")
        b = d.box(0, 0, title="Web server", subtitle="2 replicas")
        self.assertEqual((b.w, b.h), svgkit.box_size("Web server", "2 replicas"))

    def test_group_title_at_top_left(self):
        d = Diagram(400, label="x")
        d.group(10, 10, 300, 100, "Cloud account", dashed=True)
        out = d.svg()
        self.assertIn('rx="10"', out)
        self.assertIn('stroke-dasharray="5 4"', out)
        self.assertIn('<text x="24" y="30" font-weight="700"', out)


class ArrowTests(unittest.TestCase):
    def path(self, d):
        return [l for l in d.svg().splitlines() if "<path" in l and "marker id" not in l][-1]

    def test_side_by_side_boxes(self):
        d = Diagram(400, label="x")
        a, b = d.box(10, 10, 100, 40, "a"), d.box(200, 20, 100, 40, "b")
        d.arrow(a, b)
        self.assertIn('d="M110 35 H198"', self.path(d))
        d.arrow(b, a)
        self.assertIn('d="M200 35 H112"', self.path(d))

    def test_stacked_boxes(self):
        d = Diagram(400, label="x")
        a, b = d.box(10, 10, 100, 40, "a"), d.box(10, 100, 100, 40, "b")
        d.arrow(a, b)
        self.assertIn('d="M60 50 V98"', self.path(d))

    def test_offset_boxes_bend_once(self):
        d = Diagram(400, label="x")
        a, b = d.box(10, 10, 100, 40, "a"), d.box(200, 100, 100, 40, "b")
        d.arrow(a, b)
        self.assertIn('d="M110 30 H250 V98"', self.path(d))

    def test_point_to_box(self):
        d = Diagram(400, label="x")
        b = d.box(100, 100, 100, 40, "b")
        d.arrow((150, 10), b)
        self.assertIn('d="M150 10 V98"', self.path(d))

    def test_label_above_horizontal_and_beside_vertical(self):
        d = Diagram(400, label="x")
        d.arrow((10, 50), (110, 50), "reads")
        d.arrow((200, 10), (200, 110), "flush")
        out = d.svg()
        self.assertIn('<text x="60" y="42" text-anchor="middle" fill="#6b7280">reads', out)
        self.assertIn('<text x="208" y="64" fill="#6b7280">flush', out)

    def test_dashed_coloured_arrow_has_coloured_label(self):
        d = Diagram(400, label="x")
        d.arrow((10, 50), (110, 50), "queue depth", dashed=True, color="state")
        out = d.svg()
        self.assertIn('stroke="#0e7c86" stroke-dasharray="4 3"', out)
        self.assertIn('fill="#0e7c86">queue depth', out)

    def test_route_and_curve(self):
        d = Diagram(400, label="x")
        d.route([(10, 10), (10, 50), (100, 50)], dashed=True)
        self.assertIn('d="M10 10 V50 H100" stroke="#475569" stroke-dasharray="4 3" fill="none" marker-end', d.svg())
        d.curve((0, 0), (50, 0), (50, 50), (100, 50))
        self.assertIn('d="M0 0 C50 0 50 50 100 50"', self.path(d))


class TimelineTests(unittest.TestCase):
    def test_axis_mark_and_window(self):
        d = Diagram(760, label="x")
        t = d.timeline(140)
        t.mark(80, "start")
        t.window(330, 620, "measured")
        out = d.svg()
        self.assertIn('d="M60 140 H740" stroke="#475569" marker-end="url(#a)"', out)
        self.assertIn('>time</text>', out)
        self.assertIn('d="M80 50 V140" stroke="#1f2430" stroke-dasharray="3 3"', out)
        self.assertIn('<text x="80" y="44" text-anchor="middle" font-weight="700"', out)
        self.assertIn('<rect x="330" y="116" width="290" height="22" fill="#e8f5f6" stroke="#0e7c86"/>', out)
        self.assertEqual(d.check(), [])

    def test_colliding_mark_labels_are_staggered(self):
        d = Diagram(760, label="x")
        t = d.timeline(140)
        a = t.mark(130, "server ready")
        b = t.mark(190, "load starts")
        self.assertEqual(b.y, a.y - svgkit.LINE_HEIGHT)
        self.assertIn('d="M190 34 V140"', d.svg())
        self.assertEqual(d.check(), [])

    def test_explicit_label_y_is_left_alone(self):
        d = Diagram(760, label="x")
        t = d.timeline(140)
        t.mark(130, "server ready")
        t.mark(150, "first reply", label_y=44)
        self.assertEqual([p.rule for p in d.check()], ["text-overlap"])

    def test_domain_maps_to_axis(self):
        d = Diagram(760, label="x")
        t = d.timeline(140, x1=100, x2=700, domain=(0, 600))
        self.assertEqual(t.x(300), 400)


class AnalyzeTests(unittest.TestCase):
    def texts(self, body):
        return svgkit.analyze(ET.fromstring(svg(body))).texts

    def test_anchor(self):
        w = svgkit.text_width("abc")
        for anchor, x1 in (("start", 100), ("middle", 100 - w / 2), ("end", 100 - w)):
            t, = self.texts('<text x="100" y="50" text-anchor="%s">abc</text>' % anchor)
            self.assertAlmostEqual(t.box.x, x1)

    def test_inherits_font_and_anchor_and_translate(self):
        t, = self.texts('<g font-size="24" font-weight="bold" text-anchor="end" transform="translate(10 5)">'
                        '<text x="100" y="50">abc</text></g>')
        self.assertAlmostEqual(t.box.w, svgkit.text_width("abc", 24, True))
        self.assertAlmostEqual(t.box.x2, 110)
        self.assertAlmostEqual(t.box.y, 55 - svgkit.ASCENT * 24)

    def test_style_attribute(self):
        t, = self.texts('<text x="0" y="50" style="font-size: 20px; font-weight: 700">abc</text>')
        self.assertAlmostEqual(t.box.w, svgkit.text_width("abc", 20, True))

    def test_tspans_with_position_start_new_lines(self):
        ts = self.texts('<text x="10" y="20">one<tspan x="10" dy="16">two</tspan></text>')
        self.assertEqual([(t.s, t.box.y + svgkit.ASCENT * 12) for t in ts], [("one", 20), ("two", 36)])

    def test_inline_tspan_adds_to_the_line(self):
        t, = self.texts('<text x="10" y="20">one <tspan font-weight="700">two</tspan> three</text>')
        self.assertEqual(t.s, "one two three")
        space = svgkit.text_width("a a") - svgkit.text_width("aa")
        expect = (svgkit.text_width("one") + svgkit.text_width("two", bold=True) + svgkit.text_width("three")
                  + 2 * space)
        self.assertAlmostEqual(t.box.w, expect)

    def test_rotated_and_hidden_are_skipped(self):
        self.assertEqual(self.texts('<text transform="rotate(-90)" x="0" y="0">a</text>'
                                    '<g data-check="off"><text x="0" y="10">b</text></g>'
                                    '<defs><text x="0" y="10">c</text></defs>'), [])

    def test_path_outline(self):
        polys = svgkit._path_polylines("M10 10 H50 V30 h-10 v-5 L10 10 Z M0 0 l5 5")
        self.assertEqual(polys[0][:6], [(10, 10), (50, 10), (50, 30), (40, 30), (40, 25), (10, 10)])
        self.assertEqual(polys[1], [(0, 0), (5, 5)])

    def test_curve_is_sampled(self):
        poly, = svgkit._path_polylines("M0 0 C0 100 100 100 100 0")
        self.assertEqual(poly[-1], (100, 0))
        self.assertAlmostEqual(max(y for _, y in poly), 75)


class CheckTests(unittest.TestCase):
    def test_overlapping_text(self):
        self.assertEqual(rules('<text x="10" y="20">overlapping words</text><text x="40" y="24">here</text>'),
                         ["text-overlap"])

    def test_lines_16px_apart_do_not_overlap(self):
        self.assertEqual(rules('<text x="10" y="20">Qgjpy</text><text x="10" y="34">Qgjpy</text>'), [])

    def test_overflowing_box(self):
        ps = svgkit.check_text(svg('<rect x="180" y="10" width="40" height="30"/>'
                                   '<text x="200" y="30" text-anchor="middle">far too long a label</text>'))
        self.assertEqual([p.rule for p in ps], ["text-overflow"])
        self.assertIn("px past the", ps[0].message)

    def test_text_touching_box_edge(self):
        w = svgkit.text_width("label")
        ps = svgkit.check_text(svg('<rect x="10" y="10" width="%s" height="30"/>' % (w + 1)
                                   + '<text x="10.5" y="30">label</text>'))
        self.assertEqual([p.rule for p in ps], ["text-overflow"])
        self.assertIn("px from the left edge", ps[0].message)

    def test_text_in_smallest_box_of_nested_boxes(self):
        self.assertEqual(rules('<rect x="0" y="0" width="400" height="200"/>'
                               '<rect x="10" y="10" width="100" height="30"/>'
                               '<text x="20" y="30">fits</text>'), [])

    def test_text_crossing_a_box_it_is_not_in(self):
        self.assertEqual(rules('<rect x="100" y="10" width="100" height="30" fill="none" stroke="#000"/>'
                               '<text x="30" y="30">across the edge</text>'), ["text-on-box"])

    def test_invisible_rect_is_ignored(self):
        self.assertEqual(rules('<rect x="100" y="10" width="100" height="30" fill="none"/>'
                               '<text x="60" y="30">across the edge</text>'), [])

    def test_line_through_text(self):
        self.assertEqual(rules('<path d="M50 0 V100" stroke="#475569"/><text x="10" y="50">crossed text</text>'),
                         ["text-on-line"])

    def test_unstroked_and_faint_lines_are_ignored(self):
        self.assertEqual(rules('<path d="M50 0 V100"/><path d="M60 0 V100" stroke="#e6e8ef"/>'
                               '<path d="M70 0 V100" stroke="#000" stroke-opacity="0.1"/>'
                               '<text x="10" y="50">crossed text</text>'), [])

    def test_inherited_stroke_counts(self):
        self.assertEqual(rules('<g stroke="#000"><path d="M50 0 V100"/></g><text x="10" y="50">crossed text</text>'),
                         ["text-on-line"])

    def test_line_ending_short_of_text(self):
        self.assertEqual(rules('<path d="M50 0 V38" stroke="#000"/><text x="10" y="50">nearby text</text>'), [])

    def test_text_past_viewbox(self):
        self.assertEqual(rules('<text x="390" y="50">past the edge</text>'), ["outside"])
        self.assertEqual(rules('<text x="10" y="5">above the top</text>'), ["outside"])

    def test_tolerance(self):
        w = svgkit.text_width("ab")
        body = '<text x="10" y="20">ab</text><text x="%s" y="20">cd</text>' % (10 + w - 0.5)
        self.assertEqual(rules(body), [])
        self.assertEqual([p.rule for p in svgkit.check_text(svg(body), tolerance=0)], ["text-overlap"])

    def test_data_check_off(self):
        self.assertEqual(rules('<text x="10" y="20">overlapping words</text>'
                               '<text data-check="off" x="40" y="24">here</text>'), [])

    def test_invalid_xml_and_not_svg(self):
        self.assertEqual([p.rule for p in svgkit.check_text("<svg><text></svg>")], ["xml"])
        self.assertEqual([p.rule for p in svgkit.check_text("<html/>")], ["xml"])


class FixtureTests(unittest.TestCase):
    def test_known_overlap(self):
        ps = svgkit.check_file(os.path.join(DATA, "overlap.svg"))
        self.assertEqual([p.rule for p in ps], ["text-overlap"])
        self.assertIn('"load starts" at (100, 40) overlaps "first reply" at (140, 40)', ps[0].message)

    def test_clean(self):
        self.assertEqual(svgkit.check_file(os.path.join(DATA, "clean.svg")), [])

    def test_invalid(self):
        self.assertEqual([p.rule for p in svgkit.check_file(os.path.join(DATA, "invalid.svg"))], ["xml"])

    def test_examples_are_clean_and_current(self):
        code, out = run("build", "--stale", os.path.join(HERE, "examples"))
        self.assertEqual(code, 0, out)
        code, out = run("check", os.path.join(HERE, "examples"))
        self.assertEqual(code, 0, out)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_check_exit_codes_and_report(self):
        code, out = run("check", os.path.join(DATA, "clean.svg"))
        self.assertEqual(code, 0)
        self.assertIn("checked 1 SVG file: no problems", out)
        code, out = run("check", DATA)
        self.assertEqual(code, 1)
        self.assertIn("overlap.svg: 1 problem\n  text-overlap", out)
        self.assertIn("checked 3 SVG files: 2 problems in 2 files", out)
        code, out = run("check", os.path.join(self.dir, "missing"))
        self.assertEqual(code, 2)

    def test_build_writes_beside_source_then_reports_unchanged(self):
        self.write("docs/chart.py", "from svgkit import Diagram\nd = Diagram(200, label='chart')\n"
                                "d.text(10, 20, 'hello')\nd.save()\n")
        code, out = run("build", self.dir)
        self.assertEqual(code, 0, out)
        self.assertIn("wrote", out)
        with open(os.path.join(self.dir, "docs", "chart.svg")) as f:
            self.assertIn(">hello</text>", f.read())
        code, out = run("build", self.dir)
        self.assertIn("unchanged", out)

    def test_build_stale(self):
        src = self.write("a.py", "import svgkit\nsvgkit.Diagram(200, label='a').save()\n")
        self.assertEqual(run("build", "--stale", self.dir)[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "a.svg")))
        run("build", self.dir)
        self.assertEqual(run("build", "--stale", self.dir)[0], 0)
        self.write("a.py", open(src).read().replace("200", "300"))
        code, out = run("build", "--stale", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("a.svg: out of date", out)

    def test_build_one_source_can_write_several(self):
        self.write("t.py", "from svgkit import Diagram\nfor n in ('s1', 's2'):\n"
                           "    Diagram(200, label=n).save(n + '.svg')\n")
        self.assertEqual(run("build", self.dir)[0], 0)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "s1.svg")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "s2.svg")))

    def test_build_reports_problems_and_failures(self):
        self.write("bad.py", "from svgkit import Diagram\nd = Diagram(200, label='b')\n"
                             "d.text(10, 20, 'overlapping words'); d.text(40, 24, 'here')\nd.save()\n")
        self.write("broken.py", "import svgkit\nraise RuntimeError('boom')\n")
        code, out = run("build", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("text-overlap", out)
        self.assertIn("broken.py: failed", out)
        self.assertIn("RuntimeError: boom", out)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "bad.svg")))

    def test_sources_skip_helpers_and_non_diagrams(self):
        self.write("_style.py", "import svgkit\n")
        self.write("other.py", "print('not a diagram')\n")
        self.write("d.py", "import svgkit\n")
        self.write(".hidden/e.py", "import svgkit\n")
        found = [os.path.basename(p) for p in svgkit.find_sources([self.dir])]
        self.assertEqual(found, ["d.py"])

    def test_source_can_import_helper_beside_it(self):
        self.write("_style.py", "WIDTH = 321\n")
        self.write("d.py", "import svgkit, _style\nsvgkit.Diagram(_style.WIDTH, label='d').save()\n")
        self.assertEqual(run("build", self.dir)[0], 0)
        with open(os.path.join(self.dir, "d.svg")) as f:
            self.assertIn('viewBox="0 0 321', f.read())

    def test_measure(self):
        code, out = run("measure", "measured: 10 min")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("99.8 "))

    def test_overlay_marks_boxes(self):
        with open(os.path.join(DATA, "overlap.svg")) as f:
            text = f.read()
        out = svgkit.overlay(text, svgkit.check_text(text))
        self.assertEqual(out.count('stroke="#dc2626"'), 2)
        self.assertEqual(out.count('stroke="#94a3b8"'), 2)
        # the overlay is left out of the checks, so it adds no problems of its own
        self.assertEqual([p.message for p in svgkit.check_text(out)], [p.message for p in svgkit.check_text(text)])


if __name__ == "__main__":
    unittest.main()
