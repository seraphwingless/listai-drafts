#!/usr/bin/env python3
"""Генератор картинок для постов listai.pro: фон + плашка + заголовок Roboto + логотип.

Примеры:
  python3 make_post_pic.py --type news --title "Claude научился работать с таблицами"
  python3 make_post_pic.py --type list --title "5 нейросетей для озвучки текста"
  python3 make_post_pic.py --type tool --title "Suno" --subtitle "Музыка по описанию" --service-logo suno.png
  python3 make_post_pic.py --type header          # шапка профиля X (1500x500)
  python3 make_post_pic.py --type avatar          # аватарка 512x512
  python3 make_post_pic.py --batch posts.json     # пачка постов
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
BG_DIR = ROOT / "backgrounds" if (ROOT / "backgrounds").exists() else ROOT.parent / "listai post pics"
OUT_DIR = ROOT / "out"
STATE = ROOT / ".state.json"

W, H = 1600, 900
MARGIN_X = 96
CYAN = (53, 182, 211)
BADGE_TEXT = (6, 36, 45)
WHITE = (255, 255, 255)

# тип поста -> (префикс файлов фона, текст на плашке)
TYPES = {
    "news": ("news", "НОВОСТЬ"),
    "tool": ("tool", "ИНСТРУМЕНТ"),
    "list": ("podborka", "ПОДБОРКА"),
    "howto": ("practice", "ПРАКТИКА"),
    "poll": ("survey", "ОПРОС"),
}

# куда класть логотип сервиса в карточках инструмента: файл -> (центр x, центр y, сторона)
# координаты в исходном размере фона 1672x941; значения приблизительные
LOGO_SLOTS = {
    "tool 1": (1260, 410, 430),
    "tool 2": (1310, 380, 340),
    "tool 3": (1145, 505, 290),
    "tool 4": (1445, 420, 330),
}


def load_font(size, weight=700):
    font = ImageFont.truetype(str(ASSETS / "Roboto-VF.ttf"), size)
    values = []
    for axis in font.get_variation_axes():
        name = axis["name"]
        name = name.decode() if isinstance(name, bytes) else name
        values.append(weight if name.lower().startswith("weight") else 100)
    font.set_variation_by_axes(values)
    return font


def pick_background(kind, index=None):
    prefix = TYPES[kind][0]
    files = sorted(p for p in BG_DIR.glob("*.jp*g") if p.stem.startswith(prefix))
    if not files:
        sys.exit(f"Нет фонов для типа '{kind}' в {BG_DIR}")
    if index is not None:
        return files[(index - 1) % len(files)]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    nxt = (state.get(kind, -1) + 1) % len(files)
    state[kind] = nxt
    STATE.write_text(json.dumps(state))
    return files[nxt]


def cover_resize(img, w, h):
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def left_shade(img, strength=0.55, reach=0.65):
    w, h = img.size
    grad = Image.linear_gradient("L").rotate(90).resize((w, h))
    grad = grad.transpose(Image.FLIP_LEFT_RIGHT)  # 255 слева -> 0 справа
    mask = grad.point(lambda v: int(strength * 255 * max(0.0, 1 - (255 - v) / (255 * reach))))
    img.paste(Image.new("RGB", (w, h), (0, 0, 0)), mask=mask)
    return img


def wrap(text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_title(text, max_w, max_lines=3, start=118, end=60):
    for size in range(start, end - 1, -4):
        font = load_font(size, 700)
        lines = wrap(text, font, max_w)
        if len(lines) <= max_lines and all(font.getlength(l) <= max_w for l in lines):
            return font, lines
    font = load_font(end, 700)
    return font, wrap(text, font, max_w)[:max_lines]


def spaced_text(draw, xy, text, font, fill, spacing=3):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + spacing
    return x


def paste_logo(img, x, y, height):
    logo = Image.open(ASSETS / "logo.png").convert("RGBA")
    w = round(logo.width * height / logo.height)
    logo = logo.resize((w, height), Image.LANCZOS)
    img.paste(logo, (x, y), logo)
    return w


def draw_service_logo(img, path, slot, bg_size):
    cx, cy, side = slot
    k = img.width / bg_size[0]
    cx, cy, side = cx * k, cy * k, side * k
    card = Image.new("RGBA", (round(side), round(side)), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle((0, 0, card.width - 1, card.height - 1),
                                           radius=round(side * 0.18), fill=(255, 255, 255, 235))
    logo = Image.open(path).convert("RGBA")
    inner = round(side * 0.68)
    scale = min(inner / logo.width, inner / logo.height)
    logo = logo.resize((round(logo.width * scale), round(logo.height * scale)), Image.LANCZOS)
    card.paste(logo, ((card.width - logo.width) // 2, (card.height - logo.height) // 2), logo)
    img.paste(card, (round(cx - side / 2), round(cy - side / 2)), card)


def make_post(kind, title, subtitle=None, bg_index=None, service_logo=None, out=None, png=False):
    bg_path = pick_background(kind, bg_index)
    bg = Image.open(bg_path).convert("RGB")
    bg_size = bg.size
    img = cover_resize(bg, W, H)
    img = left_shade(img)

    if service_logo and kind == "tool" and bg_path.stem in LOGO_SLOTS:
        draw_service_logo(img, service_logo, LOGO_SLOTS[bg_path.stem], bg_size)

    paste_logo(img, MARGIN_X, 56, 52)

    max_w = 800 if kind != "tool" else 760
    font, lines = fit_title(title, max_w)
    badge_font = load_font(26, 700)
    sub_font = load_font(38, 400)

    badge_h, gap = 54, 34
    line_h = round(font.size * 1.12)
    sub_lines = wrap(subtitle, sub_font, max_w) if subtitle else []
    block_h = badge_h + gap + line_h * len(lines) + (24 + 50 * len(sub_lines) if sub_lines else 0)
    y0 = max(150, (H - block_h) // 2 + 20)

    badge_text = TYPES[kind][1]
    tmp = ImageDraw.Draw(img)
    text_w = sum(badge_font.getlength(c) + 3 for c in badge_text)
    badge_w = round(text_w + 48)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    y = y0 + badge_h + gap
    for line in lines:
        sd.text((MARGIN_X + 3, y + 5), line, font=font, fill=(0, 0, 0, 200))
        y += line_h
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    img = Image.alpha_composite(img.convert("RGBA"), shadow).convert("RGB")

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((MARGIN_X, y0, MARGIN_X + badge_w, y0 + badge_h), radius=badge_h // 2, fill=CYAN)
    spaced_text(d, (MARGIN_X + 24, y0 + (badge_h - badge_font.size) // 2 - 3), badge_text,
                badge_font, BADGE_TEXT)

    y = y0 + badge_h + gap
    for line in lines:
        d.text((MARGIN_X, y), line, font=font, fill=WHITE)
        y += line_h
    if sub_lines:
        y += 8
        for line in sub_lines:
            d.text((MARGIN_X, y), line, font=sub_font, fill=(215, 235, 240))
            y += 50

    foot = load_font(34, 500)
    d.ellipse((MARGIN_X, H - 92, MARGIN_X + 14, H - 78), fill=CYAN)
    d.text((MARGIN_X + 28, H - 105), "listai.pro", font=foot, fill=(235, 245, 248))

    return save(img, out, kind, title, png)


def make_header(out=None, tagline="Каталог нейросетей и AI-инструментов"):
    bg = Image.open(BG_DIR / "cover 1.jpeg").convert("RGB")
    img = cover_resize(bg, 1500, 844)
    top = 150
    img = img.crop((0, top, 1500, top + 500))
    img = left_shade(img, 0.5, 0.6)
    paste_logo(img, 80, 95, 90)
    d = ImageDraw.Draw(img)
    d.text((80, 215), tagline, font=load_font(44, 500), fill=WHITE)
    d.text((80, 282), "listai.pro", font=load_font(34, 500), fill=CYAN)
    return save(img, out, "header", "header", True)


def make_avatar(out=None):
    bg = Image.open(BG_DIR / "cover 1.jpeg").convert("RGB")
    img = cover_resize(bg, 512, 512).filter(ImageFilter.GaussianBlur(14))
    img = Image.eval(img, lambda v: int(v * 0.45))
    logo = Image.open(ASSETS / "logo.png").convert("RGBA")
    icon = logo.crop((0, 0, int(logo.width * 0.27), logo.height))
    scale = 300 / icon.height * 0.9
    icon = icon.resize((round(icon.width * scale), round(icon.height * scale)), Image.LANCZOS)
    img.paste(icon, ((512 - icon.width) // 2, (512 - icon.height) // 2), icon)
    return save(img, out, "avatar", "avatar", True)


TRANSLIT = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюя",
    ["a","b","v","g","d","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","c","ch","sh","sch","","y","","e","yu","ya"]))


def slugify(text):
    out = "".join(TRANSLIT.get(c, c) for c in text.lower())
    out = "".join(c if (c.isascii() and c.isalnum()) else "-" for c in out)
    return "-".join(x for x in out.split("-") if x)[:40]


def save(img, out, kind, title, png):
    OUT_DIR.mkdir(exist_ok=True)
    slug = slugify(title) or kind
    path = Path(out) if out else OUT_DIR / f"{kind}-{slug}.{'png' if png else 'jpg'}"
    if path.suffix.lower() == ".png":
        img.save(path)
    else:
        img.save(path, quality=94, subsampling=0)
    print(path)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--type", choices=[*TYPES, "header", "avatar"])
    ap.add_argument("--title")
    ap.add_argument("--subtitle")
    ap.add_argument("--bg", type=int, help="номер фона внутри типа (1, 2, 3...); без него по кругу")
    ap.add_argument("--service-logo", help="файл логотипа сервиса (для type=tool)")
    ap.add_argument("--out")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--batch", help="JSON-файл: список {type,title,subtitle,bg,service_logo,out}")
    a = ap.parse_args()

    if a.batch:
        for item in json.loads(Path(a.batch).read_text()):
            make_post(item["type"], item["title"], item.get("subtitle"), item.get("bg"),
                      item.get("service_logo"), item.get("out"), item.get("png", False))
        return
    if a.type == "header":
        make_header(a.out)
    elif a.type == "avatar":
        make_avatar(a.out)
    elif a.type and a.title:
        make_post(a.type, a.title, a.subtitle, a.bg, a.service_logo, a.out, a.png)
    else:
        ap.error("нужно --type и --title (или --batch)")


if __name__ == "__main__":
    main()
