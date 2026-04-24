import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import os
import time
import html
from dotenv import load_dotenv
import random
from datetime import datetime

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://habr.com/ru/hub/programming/articles/"
PAGES_TO_PARSE = 3

HEADERS = {
    "User-Agent": (
       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

EXCEL_FILE = "articles.xlsx"
SEEN_FILE = "seen.json"
DELAY_RANGE = (1, 2)


def load_seen(path: str) -> set[str]:
    """Загружает множество уже спарсенных ссылок из JSON-файла."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[WARN] Не смог прочитать {path}: {e}. Начинаю с пустого множества.")
        return set()


def save_seen(path: str, seen: set[str]) -> None:
    """Сохраняет множество ссылок в JSON-файл (как список)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def fetch_page(url: str) -> BeautifulSoup | None:
    """
    Загружает страницу по URL и возвращает BeautifulSoup.
    При ошибке логирует и возвращает None.
    Делает случайную задержку ПЕРЕД запросом.
    """
    delay = random.uniform(*DELAY_RANGE)
    time.sleep(delay)

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[SKIP] Не смог загрузить {url}: {e}")
        return None

    return BeautifulSoup(response.text, "html.parser")


def find_article_cards(soup: BeautifulSoup) -> list:
    """Находит на странице все карточки статей."""
    cards = soup.find_all("article", class_="tm-articles-list__item")
    print(f"[INFO] Найдено карточек на странице: {len(cards)}")
    return cards


def safe_text(card, selector: str, attr: str | None = None) -> str | None:
    """
    Безопасно извлекает текст или значение атрибута по CSS-селектору.
    Возвращает None, если элемент не найден.
    """
    el = card.select_one(selector)
    if el is None:
        return None
    if attr is not None:
        return el.get(attr)
    return el.get_text(strip=True)


def parse_card(card, base_url: str = "https://habr.com") -> dict | None:
    """
    Парсит одну карточку статьи.
    Если не смогли достать ссылку или заголовок — возвращаем None
    (без URL статью нельзя дедуплицировать, она бесполезна).
    """
    href = safe_text(card, "h2.tm-title a.tm-title__link", attr="href")
    title = safe_text(card, "h2.tm-title a.tm-title__link")
    raw_date = safe_text(card, "time", attr="datetime")

    if not href or not title:
        print("[SKIP] Не удалось извлечь заголовок или ссылку из карточки")
        return None

    url = href if href.startswith("http") else base_url + href

    article = {
        "title": title,
        "author": safe_text(card, "a.tm-user-info__username"),
        "date": raw_date[:16].replace("T", " ") if raw_date else None,
        "rating": safe_text(card, "span.tm-votes-meter__value"),
        "views": safe_text(card, "span.tm-icon-counter__value"),
        "url": url,
    }

    missing = [k for k, v in article.items() if v is None]
    if missing:
        print(f"[WARN] Поля не найдены ({', '.join(missing)}) для {url}")

    return article


def build_page_url(base_url: str, page_num: int) -> str:
    """Формирует URL для нужной страницы хаба."""
    if page_num == 1:
        return base_url
    return f"{base_url}page{page_num}/"


def scrape(base_url: str, pages: int, seen: set[str]) -> list[dict]:
    """
    Обходит страницы хаба, парсит карточки, фильтрует уже виденные.
    Возвращает список новых статей (dict-ы).

    ВАЖНО: функция НЕ модифицирует seen — только читает из него.
    Добавление URL в seen теперь происходит в main() после успешной
    отправки в Telegram (at-least-once delivery semantics).
    """
    new_articles: list[dict] = []
    new_urls: set[str] = set()  # дедупликация дублей в пределах одного запуска

    for page_num in range(1, pages + 1):
        page_url = build_page_url(base_url, page_num)
        print(f"\n[INFO] === Страница {page_num}: {page_url} ===")

        soup = fetch_page(page_url)
        if soup is None:
            continue

        cards = find_article_cards(soup)

        for card in cards:
            article = parse_card(card)
            if article is None:
                continue

            if article["url"] in seen:
                print(f"[SKIP] Уже видели: {article['url']}")
                continue

            if article["url"] in new_urls:
                print(f"[SKIP] Дубль в этом запуске: {article['url']}")
                continue

            new_articles.append(article)
            new_urls.add(article["url"])
            print(f"[OK]   + {article['title'][:70]}")

    print(f"\n[INFO] Всего новых статей собрано: {len(new_articles)}")
    return new_articles


def save_to_excel(path: str, new_articles: list[dict]) -> None:
    """
    Сохраняет новые статьи в Excel.
    Если файл уже существует — дописывает к существующим данным.
    Автоматически удаляет дубликаты по URL (защита от повторной записи).
    """
    if not new_articles:
        print("[INFO] Нет новых статей — Excel не трогаем.")
        return

    new_df = pd.DataFrame(new_articles)

    if os.path.exists(path):
        try:
            old_df = pd.read_excel(path)
            combined = pd.concat([old_df, new_df], ignore_index=True)
            print(f"[INFO] Дописываю к существующим {len(old_df)} статьям.")

            # Удаляем дубли по URL (оставляем первое вхождение)
            before = len(combined)
            combined = combined.drop_duplicates(subset="url", keep="first")
            after = len(combined)
            if before > after:
                print(f"[INFO] Удалил {before - after} дублей по URL")
        except Exception as e:
            print(f"[WARN] Не смог прочитать старый {path}: {e}. Перезаписываю.")
            combined = new_df
    else:
        combined = new_df
        print(f"[INFO] Создаю новый файл {path}.")

    combined.to_excel(path, index=False)
    print(f"[OK]   Сохранено строк всего: {len(combined)} → {path}")


def rating_to_int(article: dict) -> int:
    """Безопасно превращает рейтинг из строки в число.
    Обрабатывает None, хабровский длинный минус '−', и мусор."""
    raw = article.get("rating")
    if not raw:
        return 0
    try:
        return int(raw.replace("−", "-"))
    except (ValueError, AttributeError, TypeError):
        return 0


def send_to_telegram(article: dict, retries: int = 3) -> bool:
    """Отправляет одну статью в Telegram с ретраями при таймаутах."""
    title = article.get("title") or "(без заголовка)"
    author = article.get("author") or "—"
    rating = article.get("rating") or "—"
    views = article.get("views") or "—"
    article_url = article.get("url") or ""

    safe_title = html.escape(title)
    safe_author = html.escape(author)

    text = (
        f"📰 <b>{safe_title}</b>\n"
        f"👤 {safe_author} · ⭐ {rating} · 👁 {views}\n\n"
        f"{article_url}"
    )

    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(api_url, data=data, timeout=20)
            if response.status_code == 200:
                return True
            print(f"[WARN] Telegram вернул {response.status_code}: {response.text[:200]}")
            return False
        except requests.Timeout:
            print(f"[WARN] Таймаут, попытка {attempt}/{retries}. Жду 3 сек...")
            if attempt < retries:
                time.sleep(3)
        except requests.RequestException as e:
            print(f"[WARN] Сетевая ошибка: {e}")
            return False

    print("[WARN] Не смог отправить после всех попыток.")
    return False


def send_status_message(text: str) -> bool:
    """Отправляет простое статус-сообщение в Telegram (без форматирования)."""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }
    try:
        response = requests.post(api_url, data=data, timeout=20)
        return response.status_code == 200
    except requests.RequestException:
        return False


def main() -> None:
    print("[INFO] === Старт парсинга Хабра ===")

    seen = load_seen(SEEN_FILE)
    print(f"[INFO] Загружено ссылок из {SEEN_FILE}: {len(seen)}")

    new_articles = scrape(BASE_URL, PAGES_TO_PARSE, seen)

    if new_articles:
        print(f"\n[INFO] Отправляю {len(new_articles)} статей в Telegram...")
        sent_articles: list[dict] = []  # только те, что реально долетели

        for article in new_articles:
            if send_to_telegram(article):
                seen.add(article["url"])
                sent_articles.append(article)
            time.sleep(1)

        print(f"[INFO] Отправлено в Telegram: {len(sent_articles)}/{len(new_articles)}")

        # Сохраняем ТОЛЬКО успешно отправленные — ни в seen, ни в Excel мусора нет
        save_to_excel(EXCEL_FILE, sent_articles)
        save_seen(SEEN_FILE, seen)

        # TOP-3 по успешно отправленным
        if sent_articles:
            top_3 = sorted(sent_articles, key=rating_to_int, reverse=True)[:3]
            print("\n[INFO] === ТОП-3 ПО РЕЙТИНГУ ===")
            for article in top_3:
                rating = article.get("rating") or "—"
                title = article.get("title") or "(без заголовка)"
                print(f"⭐ {rating:>5} | {title}")
        else:
            print("\n[INFO] Ни одна статья не была доставлена — TOP-3 пропускаем.")
    else:
        print("\n[INFO] Новых статей нет.")

    print("\n[INFO] === Готово ===")


if __name__ == "__main__":
    try:
        print(f"[INFO] === Проверка: {datetime.now():%Y-%m-%d %H:%M:%S} ===")
        main()
    except Exception as e:
        error_text = f"⚠️ Ошибка: {str(e)[:200]}"
        print(f"[ERROR] {error_text}")
        try:
            send_status_message(error_text)
        except Exception:
            pass
        raise  # пусть GitHub Actions пометит запуск как failed