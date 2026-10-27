#!/usr/bin/env python3
"""Ежедневный запуск на сервере (cron 06:50 UTC).

1. Выбирает пост дня: queue/ДАТА.json (инструмент дня) либо draft.json (новость от облачного агента).
2. Присылает превью владельцу в личку (бот).
3. Если config.publish_channel = true, в 10:05 по Лиссабону сам публикует пост в канал
   (отдельный фоновый процесс). Отмена: добавить дату в hold.json (список "dates").
Секретов в репозитории нет: токен бота лежит только на сервере.
"""
import argparse
import datetime
import html
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

ROOT = Path(__file__).resolve().parent
RAW = "https://raw.githubusercontent.com/seraphwingless/listai-drafts/main/"
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else None


def lisbon_now():
    try:
        return datetime.datetime.now(ZoneInfo("Europe/Lisbon"))
    except Exception:
        # запасной расчёт: Лиссабон = UTC, летом (с последнего вс. марта до последнего вс. октября, 01:00 UTC) UTC+1
        u = datetime.datetime.now(datetime.timezone.utc)
        def last_sun(y, m):
            d = datetime.date(y, m, 31)
            while d.weekday() != 6:
                d -= datetime.timedelta(days=1)
            return datetime.datetime(y, m, d.day, 1, tzinfo=datetime.timezone.utc)
        summer = last_sun(u.year, 3) <= u < last_sun(u.year, 10)
        return u.astimezone(datetime.timezone(datetime.timedelta(hours=1 if summer else 0)))


SLOTS = {"news": "09:00", "tool": "15:00"}


def slot_time(cfg, kind):
    return (cfg.get("slots") or {}).get(kind) or SLOTS[kind]


def msk_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).date().isoformat()


def send(args, chat, *extra):
    cmd = [sys.executable, str(ROOT / "telegram_post.py"), "--chat", str(chat),
           "--token-file", args.token_file, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip(), flush=True)
    return r.returncode == 0


def load_config():
    try:
        return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {"publish_channel": False}


def pick_item(today, kind):
    if kind == "tool":
        q = ROOT / "queue" / f"{today}.json"
        if not q.exists():
            return None
        d = json.loads(q.read_text(encoding="utf-8"))
        d["kind"] = "tool"
        return d
    return news_item(today)


def news_item(today):
    try:
        d = json.loads((ROOT / "draft.json").read_text(encoding="utf-8"))
    except Exception as e:
        print("draft.json не читается:", e)
        return None
    if d.get("date") != today:
        print(f"черновик за {d.get('date')}, а сегодня {today}")
        return None
    d["kind"] = "news"
    d["source"] = "draft"
    return d


def item_image(item, today):
    img = ROOT / item["image_file"] if item.get("image_file") else None
    if img and img.exists():
        return img
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    img = out / f"{today}.jpg"
    r = subprocess.run([sys.executable, str(ROOT / "make_post_pic.py"), "--type", item.get("image_type", "news"),
                        "--title", item["image_title"], "--out", str(img)], capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip())
    return img if r.returncode == 0 and img.exists() else None


def button_args(item):
    return ["--button", f"{item.get('button_text', 'Открыть в каталоге')}|{item.get('button_url', 'https://listai.pro/katalog/')}"]


def url_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=20, context=CTX).status == 200
    except Exception:
        return False


def held(today, kind=None):
    try:
        with urllib.request.urlopen(RAW + "hold.json", timeout=20, context=CTX) as r:
            data = json.load(r)
        return today in data.get("dates", []) or f"{today}:{kind}" in data.get("dates", [])
    except Exception:
        return False


def publish(args, today, item, img):
    state = Path(args.state)
    kind = item["kind"]
    done = state / f"{today}.{kind}.published"
    if done.exists():
        print("уже опубликовано")
        return
    cfg = load_config()
    hh, mm = map(int, slot_time(cfg, kind).split(":"))
    now = lisbon_now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if args.publish_at:
        h2, m2 = map(int, args.publish_at.split(":")); target = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
    wait = (target - now).total_seconds()
    if wait < -4 * 3600:
        send(args, cfg["dm_chat"], "--text", f"Пост ({kind}) за {today} пропущен: время слота {target:%H:%M} по Лиссабону давно прошло.")
        return
    if wait > 0:
        print(f"ждём до {target:%H:%M} по Лиссабону ({int(wait)} с)", flush=True)
        time.sleep(wait)
    if held(today, kind):
        send(args, cfg["dm_chat"], "--text", f"Публикация ({kind}) за {today} отменена (hold.json).")
        return
    if item.get("requires_url") and not url_ok(item["requires_url"]):
        send(args, cfg["dm_chat"], "--text", f"Пост про инструмент за {today} не вышел: карточка {html.escape(item['requires_url'])} не опубликована.")
        return
    channel = args.channel or cfg.get("channel")
    ok = send(args, channel, "--photo", str(img), "--text", item["post_html"], *button_args(item))
    if ok:
        done.touch()
        send(args, cfg["dm_chat"], "--text", f"Опубликовано в канале ({kind}, {today}).")
    else:
        send(args, cfg["dm_chat"], "--text", f"Не удалось опубликовать пост за {today}, смотрите лог на сервере.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--chat", help="чат для превью (по умолчанию из config.json)")
    ap.add_argument("--channel", help="куда публиковать (по умолчанию из config.json)")
    ap.add_argument("--publish-at", help="HH:MM по Лиссабону (для теста или разового запуска)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--worker", action="store_true", help="внутренний режим: ждать и публиковать")
    ap.add_argument("--kind", choices=["news", "tool"], help="только этот тип поста")
    ap.add_argument("--date")
    a = ap.parse_args()

    cfg = load_config()
    dm = a.chat or cfg.get("dm_chat")
    state = Path(a.state)
    state.mkdir(parents=True, exist_ok=True)
    today = a.date or msk_today()
    kinds = [a.kind] if a.kind else ["news", "tool"]

    for kind in kinds:
        item = pick_item(today, kind)
        if item and item.get("status") == "skip":
            item_ready = False
        else:
            item_ready = bool(item)
        if a.worker:
            img = item_image(item, today) if item_ready else None
            if item_ready and img:
                publish(a, today, item, img)
            continue

        prepared = state / f"{today}.{kind}.prepared"
        if prepared.exists():
            print(f"{kind}: уже подготовлено")
            continue
        if not item_ready:
            if kind == "news":
                note = html.escape((item or {}).get("note") or "подходящего поста нет")
                if send(a, dm, "--text", f"Новости сегодня ({today}) не будет: {note}"):
                    prepared.touch()
            else:
                prepared.touch()  # инструмента дня в очереди нет: молча
            continue
        img = item_image(item, today)
        if not img:
            send(a, dm, "--text", f"Не удалось получить картинку ({kind}), смотрите лог на сервере.")
            continue
        when = slot_time(cfg, kind) if not a.publish_at else a.publish_at
        if not a.no_preview:
            label = "НОВОСТЬ" if kind == "news" else "ИНСТРУМЕНТ ДНЯ"
            if not send(a, dm, "--photo", str(img), "--text", item["post_html"], *button_args(item)):
                continue
            facts = "\n".join("• " + html.escape(x) for x in item.get("facts", []))
            tail = (f"\n\nВыйдет в канал сегодня в {when} по Лиссабону автоматически." if cfg.get("publish_channel")
                    else "\n\nАвтопубликация в канал выключена.")
            send(a, dm, "--text", f"{label}: что за пост (только для вас):\n" + (facts or "нет данных") + tail)
        prepared.touch()
        if cfg.get("publish_channel"):
            cmd = [sys.executable, str(ROOT / "daily.py"), "--worker", "--kind", kind, "--token-file", a.token_file,
                   "--state", a.state, "--date", today]
            if a.channel:
                cmd += ["--channel", a.channel]
            if a.publish_at:
                cmd += ["--publish-at", a.publish_at]
            log = open(state / f"{today}.{kind}.worker.log", "a")
            subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log, start_new_session=True, close_fds=True)
            print(f"{kind}: фоновая публикация запущена", flush=True)


if __name__ == "__main__":
    main()
