"""Browser tests: the width estimates against Chrome's own text measurement, and PNG rendering.

Run: python3 -m unittest test_browser
Needs Chrome or Chromium (see svgkit.find_chrome). Without one every test is skipped.
"""
import html
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

import svgkit

chrome = None
work = None

SAMPLES = [
    "Input: requests at a steady rate for 15 minutes. Repeat: 3 runs. Then the results are compared.",
    "Build server: one clock for every job in the run",
    "load starts", "server ready", "measured: 10 min", "Rates: 500 requests a second on the API.",
    "queue depth, CPU, memory", "1 CPU, 1 GiB", "Ln … L2 → 10–20 ms ≤ 1 s",
]


def setUpModule():
    global chrome, work
    chrome = svgkit.find_chrome()
    if not chrome:
        raise unittest.SkipTest("Chrome is not available")
    work = tempfile.mkdtemp()


def tearDownModule():
    if work:
        shutil.rmtree(work, ignore_errors=True)


def measure_in_chrome(samples):
    """{(text, bold): width} as Chrome lays the text out in the house font at 12 px."""
    page = os.path.join(work, "measure.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write("""<!doctype html><meta charset=utf-8>
<svg id=s xmlns="http://www.w3.org/2000/svg" font-family="%s" font-size="12"></svg><pre id=out></pre>
<script>
const samples = %s, s = document.getElementById('s'), res = [];
for (const t of samples) for (const w of ['400', '700']) {
  const e = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  e.setAttribute('font-weight', w); e.textContent = t; s.appendChild(e);
  res.push([t, w === '700', e.getComputedTextLength()]); s.removeChild(e);
}
document.getElementById('out').textContent = JSON.stringify(res);
</script>""" % (html.escape(svgkit.FONT_FAMILY), json.dumps(samples)))
    out = subprocess.run([chrome, "--headless", "--disable-gpu", "--no-first-run",
                          "--user-data-dir=" + os.path.join(work, "profile"), "--dump-dom", "file://" + page],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60).stdout.decode("utf-8")
    data = json.loads(html.unescape(re.search(r'<pre id="out">(.*?)</pre>', out, re.S).group(1)))
    return {(t, b): w for t, b, w in data}


class WidthTests(unittest.TestCase):
    def test_estimates_within_two_percent_of_chrome(self):
        for (text, bold), real in measure_in_chrome(SAMPLES).items():
            with self.subTest(text=text, bold=bold):
                self.assertAlmostEqual(svgkit.text_width(text, 12, bold), real, delta=max(real * 0.02, 1))


class RenderTests(unittest.TestCase):
    def test_png_has_the_viewbox_size_at_twice_the_scale(self):
        png = os.path.join(work, "clean.png")
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "clean.svg")) as f:
            svgkit.render_png(f.read(), png, chrome)
        with open(png, "rb") as f:
            head = f.read(24)
        self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", head[16:24]), (800, 240))


if __name__ == "__main__":
    unittest.main()
