"""Boxes sized to their text, a group, and arrows that find the facing sides."""
from svgkit import Diagram, box_size

d = Diagram(760, label="Example pipeline")
d.group(172, 10, 578, 230, "Cloud account")

src = d.box(10, 60, title="Uploads", subtitle="images, CSV", kind="kafka")
w = max(box_size("Web server", "2 replicas")[0], box_size("Metrics", "one row a second")[0])
web = d.box(190, 60, w, title="Web server", subtitle="2 replicas")
queue = d.box(380, 50, title="Job queue", subtitle="3 partitions", kind="topic")
worker = d.box(580, 44, title="Image worker", subtitle=["resize and crop", "1 CPU, 1 GiB"], kind="app",
               emphasis=True)
metrics = d.box(380, 160, title="Metrics", subtitle="one row a second", kind="state")

d.arrow(src, web, "posts")
d.arrow(web, queue, "enqueue")
d.arrow(queue, worker, "take")
d.arrow(metrics, queue, "queue depth", dashed=True, color="state")
d.arrow(metrics, worker, "CPU, memory", dashed=True, color="state")
d.note(10, 270, "Boxes without a width or height are sized to their text.")
d.save()
