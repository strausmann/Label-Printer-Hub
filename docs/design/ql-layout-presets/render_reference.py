"""Reference renderer for the QL 62 mm across-width "compact" preset (#258).

Throwaway spike output kept as the visual and numeric reference for the implementation.
Needs Pillow, qrcode and brother_ql; fonts (SIL OFL) in ./fonts: IBM Plex Mono Bold and
Atkinson Hyperlegible Next (variable). Not product code.
"""
import sys, qrcode, logging
from PIL import Image, ImageDraw, ImageFont
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster
from brother_ql.backends.helpers import send
from brother_ql.devicedependent import label_type_specs
W = label_type_specs['62']['dots_printable'][0]          # 696 across the tape
PX = 300/25.4
M = 0                                        # 0.5 mm margin along the feed
QR_SIDE = round(W*0.32)                                  # fixed QR share of the width
q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, version=3)
q.add_data("https://example.invalid/hardware/19"); q.make(fit=False)
n = q.modules_count; box = QR_SIDE // (n+8)              # whole pixels per module, 4-module quiet zone each side
qimg = q.make_image(fill_color="black", back_color="white").get_image().convert("L").resize((n*box, n*box), Image.NEAREST)
side = (n+8)*box
F = "fonts"
mono = lambda s: ImageFont.truetype(F+"/ibmplexmono/IBMPlexMono-Bold.ttf", s)
sans = lambda s, w=700: (lambda f: (f.set_variation_by_axes([w]), f)[1])(ImageFont.truetype(F+"/atkinsonhyperlegiblenext/AtkinsonHyperlegibleNext[wght].ttf", s))
tx = side + round(1.5*PX); tw = W - tx - round(1*PX)
lines = [("ST00019", mono(54)), ("DOCKER1", sans(44,700)), ("Dell OptiPlex 3070 Micro", sans(30,400)), ("S/N 72104Z2", mono(30))]
def fit(t,f):
    while f.getlength(t) > tw and f.size > 20:
        f = f.font_variant(size=f.size-2)
    return f
lines = [(t, fit(t,f)) for t,f in lines]
heights = [f.getbbox(t)[3]-f.getbbox("H")[1] + round(0.9*PX) for t,f in lines]
H = max((n+4)*box, sum(heights)) + 2*M   # 2-module quiet zone along the feed
img = Image.new("L", (W, H), 255); d = ImageDraw.Draw(img)
img.paste(qimg, (4*box, (H - n*box)//2))
y = M + (H-2*M-sum(heights))//2
for (t,f),h in zip(lines,heights):
    d.text((tx, y - f.getbbox("H")[1]), t, font=f, fill=0); y += h
img = img.point(lambda v: 0 if v < 115 else 255, "1")     # deliberate threshold (~55 % ink)
img.save("ql62-across-compact.png")
print("image", img.size, "≈ %.1f mm long, QR %.1f mm" % (H/PX, side/PX))
logging.getLogger("brother_ql").setLevel(logging.WARNING)
label_type_specs["62"]["feed_margin"] = 0
qlr = BrotherQLRaster("QL-820NWB"); convert(qlr, [img], "62", cut=True, red=False, rotate="0")
if len(sys.argv) > 2 and sys.argv[1] == "--send":  # usage: --send tcp://<printer-host>:9100
    print(send(qlr.data, sys.argv[2], backend_identifier="network", blocking=True).get("outcome"))
