# Habr Telegram Monitor

Telegram-бот, который следит за новыми статьями в хабе [habr.com/ru/hub/programming](https://habr.com/ru/hub/programming) и присылает уведомления в чат. Работает на GitHub Actions — **без сервера**, бесплатно, по расписанию.

## Что умеет

- Парсит 3 страницы хаба Programming каждый час
- Отправляет каждую новую статью в Telegram: заголовок, автор, рейтинг, просмотры, ссылка с превью
- Дедупликация через `seen.json` — повторно статью не пришлёт
- Retry-логика при временных сбоях Telegram API (до 3 попыток с ожиданием)
- **At-least-once delivery**: статья помечается как отправленная только после реальной доставки — ничего не теряется при сбоях сети
- Архивирует отправленные статьи в `articles.xlsx` (title, author, date, rating, views, url)
- При критической ошибке присылает алерт в Telegram и помечает run как failed в Actions

## Архитектура

Cron-воркер, без постоянно работающих процессов:

1. GitHub Actions триггерит workflow по расписанию
2. Workflow поднимает Ubuntu-контейнер, ставит Python 3.12 и зависимости
3. Запускает `parser.py` с переменными из GitHub Secrets
4. Парсер собирает новые статьи → шлёт в Telegram → обновляет `seen.json`
5. Если `seen.json` изменился — коммитит его обратно в репо как новое состояние
6. Контейнер умирает. Следующий запуск — через час

## Стек

- **Python 3.12** с `venv` для изоляции зависимостей
- **`requests`** + **`BeautifulSoup`** для парсинга HTML
- **`pandas`** + **`openpyxl`** для выгрузки в Excel
- **`python-dotenv`** для управления секретами локально
- **Telegram Bot API** для уведомлений
- **GitHub Actions** для автоматического запуска по расписанию

## Локальный запуск

```bash
git clone https://github.com/workjung719/habr-telegram-monitor.git
cd habr-telegram-monitor

python -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
# source .venv/bin/activate           # Linux / macOS

pip install -r requirements.txt

copy .env.example .env                # Windows
# cp .env.example .env                # Linux / macOS
# затем открой .env и подставь свои значения

python parser.py
```

## Переменные окружения

| Переменная | Описание |
|---|---|
| `TELEGRAM_TOKEN` | Токен Telegram-бота от [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Chat ID получателя (узнать у [@userinfobot](https://t.me/userinfobot)) |

## Деплой на GitHub Actions

1. Склонируй / форкни этот репозиторий в свой аккаунт
2. В репозитории зайди в **Settings → Secrets and variables → Actions → New repository secret**
3. Создай два секрета: `TELEGRAM_TOKEN` и `TELEGRAM_CHAT_ID`
4. Открой вкладку **Actions** → выбери workflow **Habr Monitor** → **Run workflow** для первого запуска
5. Далее workflow запускается автоматически по расписанию

## Расписание

Cron-триггер настраивается в `.github/workflows/monitor.yml`:

```yaml
schedule:
  - cron: '0 * * * *'   # каждый час в 00 минут UTC
```

Примеры других расписаний:
- `*/30 * * * *` — каждые 30 минут
- `0 */4 * * *` — каждые 4 часа
- `0 9 * * *` — раз в день в 09:00 UTC

## Структура проекта

```
habr-telegram-monitor/
├── .github/workflows/monitor.yml    # расписание GitHub Actions
├── parser.py                        # основной скрипт
├── requirements.txt                 # Python-зависимости
├── .env.example                     # шаблон переменных окружения
├── .gitignore
├── seen.json                        # состояние: URL уже отправленных статей
└── README.md
```