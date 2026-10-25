from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

S = 4
W = 320
OUT = "/tmp/rabbit_faces"
def sc(v): return int(round(v * S))

def circle(d, cx, cy, r, fill=None, outline=None, width=0):
    d.ellipse([sc(cx-r), sc(cy-r), sc(cx+r), sc(cy+r)], fill=fill,
              outline=outline, width=sc(width) if width else 0)

def rrect(d, box, radius, fill=None, outline=None, width=0):
    d.rounded_rectangle([sc(box[0]), sc(box[1]), sc(box[2]), sc(box[3])], radius=sc(radius),
                        fill=fill, outline=outline, width=sc(width) if width else 0)

PAL = {
    "A": dict(badge="#FBEEDB", face="#FFFDF7", ring="#DDB88D", ring2=(255,255,255,120),
              line="#8A6552", cheek=(246,166,180,120), ear="#FFFDF7", inner="#F6C3CC",
              nose="#E28598", eye="#3B2B26", style="cream"),
    "B": dict(badge="#EAF6FD", face="#FFFFFF", ring=None, ring2=None,
              line="#8A6552", cheek=(246,170,184,95), ear="#FFFFFF", inner="#F4C0CB",
              nose="#E28598", eye="#3B2B26", style="sky"),
    "C": dict(badge="#FFFFFF", face="#FFFFFF", ring="#58443A", ring2="#58443A",
              line="#58443A", cheek=(250,205,214,140), ear="#FFFFFF", inner="#FBD3DA",
              nose="#58443A", eye="#58443A", style="line"),
    "D": dict(badge="#FFE6EB", face="#FFF9F4", ring="#F0A9BB", ring2=(255,255,255,150),
              line="#8A6552", cheek=(245,145,166,150), ear="#FFF9F4", inner="#F3A9BA",
              nose="#E07A90", eye="#3B2B26", style="chibi"),
}

def ear_layer(side, st):
    p = PAL[st]
    size = 240
    layer = Image.new("RGBA", (size*S, size*S), (0,0,0,0))
    d = ImageDraw.Draw(layer)
    w, h = (33, 104) if st != "D" else (30, 92)
    cx, cy = 120, 120
    box = (cx-w/2, cy-h/2, cx+w/2, cy+h/2)
    lw = 4.6 if st == "C" else 0
    rrect(d, box, w/2, fill=p["ear"], outline=(p["line"] if st == "C" else None), width=lw)
    iw, ih = w-13, h-36
    ix, iy = cx-iw/2, cy-ih/2-5
    rrect(d, (ix, iy, ix+iw, iy+ih), iw/2, fill=p["inner"],
          outline=(p["line"] if st == "C" else None), width=(2.8 if st == "C" else 0))
    return layer.rotate(-11*side, resample=Image.BICUBIC, center=(sc(cx), sc(154)))

def ring(img, st):
    p = PAL[st]
    d = ImageDraw.Draw(img)
    r = 127
    if st == "B":
        steps = 180
        for i in range(steps):
            a0 = 360*i/steps
            a1 = 360*(i+1)/steps + 0.8
            t = i/(steps-1)
            col = (int(76+(45-76)*t), int(190+(128-190)*t), int(226+(224-226)*t), 255)
            d.arc([sc(160-r), sc(166-r), sc(160+r), sc(166+r)], a0, a1, fill=col, width=sc(7))
        d.arc([sc(160-r-4.5), sc(166-r-4.5), sc(160+r+4.5), sc(166+r+4.5)], 0, 360,
              fill=(47,125,225,55), width=sc(1.6))
    else:
        w = 5 if st == "C" else 7
        d.arc([sc(160-r), sc(166-r), sc(160+r), sc(166+r)], 0, 360, fill=p["ring"], width=sc(w))
        if p["ring2"]:
            d.arc([sc(160-r-5), sc(166-r-5), sc(160+r+5), sc(166+r+5)], 0, 360,
                  fill=p["ring2"], width=sc(1.6))

def badge(st):
    p = PAL[st]
    img = Image.new("RGBA", (W*S, W*S), (0,0,0,0))
    sh = Image.new("RGBA", img.size, (0,0,0,0))
    ImageDraw.Draw(sh).ellipse([sc(36), sc(52), sc(284), sc(300)], fill=(95,62,42,50))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(sc(10))))

    base = Image.new("RGBA", img.size, (0,0,0,0))
    ImageDraw.Draw(base).ellipse([sc(33), sc(39), sc(287), sc(293)], fill=p["badge"])
    img = Image.alpha_composite(img, base)
    ring(img, st)

    head_box = (73, 118, 247, 284) if st != "D" else (70, 113, 250, 288)
    for side in (-1, 1):
        layer = ear_layer(side, st)
        dx = 160 + side*31 - 120
        dy = 5
        canvas = Image.new("RGBA", img.size, (0,0,0,0))
        canvas.paste(layer, (sc(dx), sc(dy)), layer)
        img = Image.alpha_composite(img, canvas)

    head = Image.new("RGBA", img.size, (0,0,0,0))
    hd = ImageDraw.Draw(head)
    hd.ellipse([sc(head_box[0]), sc(head_box[1]), sc(head_box[2]), sc(head_box[3])], fill=p["face"])
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse([sc(head_box[0]), sc(head_box[1]), sc(head_box[2]), sc(head_box[3])], fill=255)
    shade = Image.new("RGBA", img.size, (0,0,0,0))
    ImageDraw.Draw(shade).ellipse([sc(head_box[0]+12), sc(head_box[1]+62), sc(head_box[2]-12), sc(head_box[3]+18)],
                                  fill=(234,198,168,70))
    shade = shade.filter(ImageFilter.GaussianBlur(sc(11)))
    hi = Image.new("RGBA", img.size, (0,0,0,0))
    ImageDraw.Draw(hi).ellipse([sc(head_box[0]+26), sc(head_box[1]+16), sc(head_box[0]+112), sc(head_box[1]+92)],
                               fill=(255,255,255,105))
    hi = hi.filter(ImageFilter.GaussianBlur(sc(12)))
    overlay = Image.alpha_composite(shade, hi)
    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
    head = Image.alpha_composite(head, overlay)
    if st in ("A", "C", "D"):
        hd2 = ImageDraw.Draw(head)
        hd2.ellipse([sc(head_box[0]), sc(head_box[1]), sc(head_box[2]), sc(head_box[3])],
                    outline=("#E3C6AC" if st == "A" else p["line"]),
                    width=sc(4.4 if st == "C" else 1.5))
    img = Image.alpha_composite(img, head)

    d = ImageDraw.Draw(img)
    eye_y = 193 if st != "D" else 192
    for cx in (99, 221):
        d.ellipse([sc(cx-16), sc(224-13), sc(cx+16), sc(224+13)], fill=p["cheek"])
    if st == "B":
        for cx in (128, 192):
            d.arc([sc(cx-13), sc(eye_y-12), sc(cx+13), sc(eye_y+13)], 200, 340,
                  fill=p["eye"], width=sc(4.4))
    else:
        r_eye = 10.5 if st != "D" else 11.5
        for cx in (128, 192):
            circle(d, cx, eye_y, r_eye, fill=p["eye"])
            circle(d, cx-3.6, eye_y-3.4, 3.3, fill=(255,255,255,240))
            if st == "D":
                circle(d, cx+3.2, eye_y+3.2, 1.9, fill=(255,255,255,180))

    ny = 212 if st != "D" else 211
    d.polygon([(sc(154), sc(ny)), (sc(166), sc(ny)), (sc(160), sc(ny+7))], fill=p["nose"])
    if st == "D":
        d.ellipse([sc(155), sc(ny+10), sc(165), sc(ny+19)], outline=p["nose"], width=sc(3))
        d.ellipse([sc(159), sc(ny+13), sc(163), sc(ny+17)], fill=(242,140,158,255))
    else:
        d.line([sc(160), sc(ny+6), sc(160), sc(ny+10)], fill=p["line"], width=sc(3))
        d.arc([sc(147), sc(ny+7), sc(160), sc(ny+20)], 15, 165, fill=p["line"], width=sc(3.2))
        d.arc([sc(160), sc(ny+7), sc(173), sc(ny+20)], 15, 165, fill=p["line"], width=sc(3.2))
    if st == "A":
        for yy, dx in ((ny-1, 0), (ny+7, 2), (ny+15, 5)):
            d.line([sc(90+dx), sc(yy), sc(112+dx), sc(yy-3)], fill=(196,156,128,105), width=sc(1.6))
            d.line([sc(230-dx), sc(yy), sc(208-dx), sc(yy-3)], fill=(196,156,128,105), width=sc(1.6))
    return img

LABELS = {"A":"① 奶油软萌", "B":"② 蓝色圆环 · 弯弯眼", "C":"③ 细线手绘", "D":"④ 粉腮呆萌"}
for st in "ABCD":
    im = badge(st).resize((W, W), Image.LANCZOS)
    bg = Image.new("RGBA", (W, W), (246,244,239,255)); bg.alpha_composite(im)
    bg.convert("RGB").save(f"{OUT}/style_{st}.png")

sheet = Image.new("RGBA", (W*2+30, W*2+64), (246,244,239,255))
font = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 19)
sd = ImageDraw.Draw(sheet)
for i, st in enumerate("ABCD"):
    x = 10 + (W+10)*(i % 2)
    y = 10 + (W+22)*(i // 2)
    im = badge(st).resize((W, W), Image.LANCZOS)
    sheet.alpha_composite(im, (x, y))
    sd.text((x+6, y+W+2), LABELS[st], font=font, fill=(75,62,53,255))
sheet.convert("RGB").save(f"{OUT}/styles_sheet.png")
print("ok")
