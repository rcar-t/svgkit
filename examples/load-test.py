"""A load-test timeline: steady load, a warm-up, then the measured window."""
from svgkit import Diagram

d = Diagram(760, label="Load test timeline")
d.note(10, 22, "Input: requests at a steady rate for 15 minutes. Repeat: 3 runs. Then the results are compared.")
d.route([(190, 112), (190, 62), (620, 62), (620, 112)], color="kafka", head=False, fill="kafka", width=2)
d.text(405, 90, "steady request rate", "kafka", "middle")

t = d.timeline(140, mark_top=66)
t.mark(80, "start")
t.mark(140, "server ready")
t.mark(190, "load starts")              # would hit "server ready", so it moves up a row
t.window(190, 330, "warm-up 5 min", kind="quiet")
t.window(330, 620, "measured: 10 min")
t.mark(620, "load stops")
d.note(630, 100, "drain, then compare")
d.note(60, 176, "Rates: 500 requests a second on the API, 20 a second on uploads.")
d.save()
