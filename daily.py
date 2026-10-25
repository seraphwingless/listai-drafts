#!/usr/bin/env python3
"""Ежедневный запуск на сервере: берёт draft.json (его пишет облачный агент), собирает картинку
и присылает черновик в личку владельцу. В канал НЕ публикует (пока включён режим «только бот»).

draft.json:
  {"date": "2026-10-27", "status": "ready" | "skip", "image_type": "news",
   "image_title": "...", "image_file": "images/2026-10-27.jpg", "post_html": "...", "button_url": "https://listai.pro/katalog/",
   "facts": ["утверждение — источник, дата", ...], "note": "почему пропуск (для status=skip)"}
"""
import argparse
import datetime
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def msk_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).date().isoformat()


def send(args, *extra):
    cmd = [sys.executable, str(ROOT / "telegram_post.py"), "--chat", args.chat,
           "--token-file", args.token_file, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip())
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--chat", required=True, help="куда присылать черновик (id личного чата)")
    a = ap.parse_args()

    state = Path(a.state)
    state.mkdir(parents=True, exist_ok=True)
    today = msk_today()
    done = state / f"{today}.done"
    if done.exists():
        print("сегодня уже отправлено")
        return

    try:
        d = json.loads((ROOT / "draft.json").read_text(encoding="utf-8"))
    except Exception as e:
        print("draft.json не читается:", e)
        return
    if d.get("date") != today:
        print(f"черновик за {d.get('date')}, а сегодня {today}: ждём")
        return

    if d.get("status") != "ready":
        note = html.escape(d.get("note") or "подходящей новости нет")
        if send(a, "--text", f"Сегодня ({today}) поста не будет: {note}"):
            done.touch()
        return

    # картинку обычно собирает и коммитит облачный агент (image_file); если её нет, собираем сами (нужен Pillow)
    img = ROOT / d["image_file"] if d.get("image_file") else None
    if not (img and img.exists()):
        out = ROOT / "out"
        out.mkdir(exist_ok=True)
        img = out / f"{today}.jpg"
        r = subprocess.run([sys.executable, str(ROOT / "make_post_pic.py"), "--type", d.get("image_type", "news"),
                            "--title", d["image_title"], "--out", str(img)], capture_output=True, text=True)
        print(r.stdout.strip(), r.stderr.strip())
        if r.returncode != 0:
            send(a, "--text", "Не удалось получить картинку, смотрите лог на сервере.")
            return
    ok = send(a, "--photo", str(img), "--text", d["post_html"],
              "--button", f"Открыть в каталоге|{d.get('button_url', 'https://listai.pro/katalog/')}")
    if ok:
        facts = "\n".join("• " + html.escape(x) for x in d.get("facts", []))
        send(a, "--text", "Проверка фактов (только для вас):\n" + (facts or "нет данных"))
        done.touch()


if __name__ == "__main__":
    main()
