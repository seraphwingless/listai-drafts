#!/usr/bin/env python3
"""Публикация поста (картинка + подпись + кнопка) через Telegram Bot API.

Токен бота берётся из переменной окружения TG_BOT_TOKEN или из файла ~/.listai_bot_token
(права 600). Токен нигде не печатается.

Примеры:
  # проверка без отправки
  python3 telegram_post.py --photo out/news-x.jpg --text "<b>Заголовок</b>\\nТекст" --dry-run

  # пробный пост себе в личку (сначала нажмите Start у бота)
  python3 telegram_post.py --photo out/news-x.jpg --text-file post.html --chat 234578511 \\
      --button "Открыть в каталоге|https://listai.pro/kategorija/razdevalka"

  # боевой пост в канал
  python3 telegram_post.py --photo out/news-x.jpg --text-file post.html --chat @listaipro \\
      --button "Открыть в каталоге|https://listai.pro/..."

Текст в формате HTML Telegram: <b>жирный</b>, <i>курсив</i>, <a href="...">ссылка</a>.
"""
import argparse
import json
import mimetypes
import os
import ssl
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CAPTION_LIMIT = 1024
CA_FILE = "/etc/ssl/cert.pem"  # системные сертификаты macOS
TOKEN_FILE = Path.home() / ".listai_bot_token"


def get_token(token_file=None):
    token = os.environ.get("TG_BOT_TOKEN")
    path = Path(token_file) if token_file else TOKEN_FILE
    if not token and path.exists():
        token = path.read_text().strip()
    if not token:
        sys.exit("Нет токена: задайте TG_BOT_TOKEN или создайте файл ~/.listai_bot_token")
    return token


def multipart(fields, file_field, file_path):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
             f"filename=\"{file_path.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
    body += file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--photo")
    ap.add_argument("--text")
    ap.add_argument("--text-file")
    ap.add_argument("--chat", default="@listaipro", help="@канал или числовой id чата")
    ap.add_argument("--button", action="append", default=[], help='"Текст|https://ссылка", можно несколько')
    ap.add_argument("--token-file", help="путь к файлу с токеном (по умолчанию ~/.listai_bot_token)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    text = a.text or (Path(a.text_file).read_text() if a.text_file else "")
    text = text.replace("\\n", "\n").strip()
    photo = Path(a.photo) if a.photo else None
    if photo and not photo.exists():
        sys.exit(f"Нет файла {photo}")
    limit = CAPTION_LIMIT if photo else 4096
    if len(text) > limit:
        sys.exit(f"Текст {len(text)} знаков, лимит {limit}. Сократите.")

    keyboard = None
    if a.button:
        rows = []
        for b in a.button:
            label, _, url = b.partition("|")
            if not url.startswith("https://"):
                sys.exit(f"Кнопка '{b}': нужен формат 'Текст|https://ссылка'")
            rows.append([{"text": label.strip(), "url": url.strip()}])
        keyboard = json.dumps({"inline_keyboard": rows})

    print(f"Чат: {a.chat} | картинка: {photo.name if photo else 'нет'} | текст: {len(text)}/{limit} | кнопок: {len(a.button)}")
    if a.dry_run:
        print("--- подпись ---\n" + text)
        return

    token = get_token(a.token_file)
    if photo:
        fields = {"chat_id": a.chat, "caption": text, "parse_mode": "HTML"}
        if keyboard:
            fields["reply_markup"] = keyboard
        body, ctype = multipart(fields, "photo", photo)
        req = Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=body,
                      headers={"Content-Type": ctype})
    else:
        data = {"chat_id": a.chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard:
            data["reply_markup"] = json.loads(keyboard)
        req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=json.dumps(data).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        ctx = ssl.create_default_context(cafile=CA_FILE) if Path(CA_FILE).exists() else None
        with urlopen(req, timeout=60, context=ctx) as r:
            res = json.load(r)
    except HTTPError as e:
        detail = json.loads(e.read().decode() or "{}").get("description", e.reason)
        sys.exit(f"Telegram вернул ошибку: {detail}")
    except URLError as e:
        sys.exit(f"Сеть недоступна: {e.reason}")
    print("Отправлено, message_id =", res["result"]["message_id"])


if __name__ == "__main__":
    main()
