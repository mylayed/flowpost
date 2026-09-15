# Перенесення на DigitalOcean (Droplet + Docker Compose)

Бот працює через long polling (домен не потрібен). Нижче — повний шлях від чистого
акаунта DigitalOcean до працюючого бота, з переносом бази з Railway.

## 1. Створити Droplet

У консолі DigitalOcean (cloud.digitalocean.com → Create → Droplets):

- **Image**: вкладка *Marketplace* → "Docker" (Ubuntu з уже встановленим Docker + Compose)
- **Size**: Basic → Regular → **2 GB RAM / 1 vCPU** ($12/міс). 1 GB вистачить не завжди —
  бот + Postgres + Redis + ffmpeg для водяних знаків одночасно можуть з'їсти більше 1 GB.
- **Region**: Frankfurt (fra1) — найближчий до України.
- **Authentication**: SSH key. Якщо у вас ще немає ключа на цьому компʼютері:

```bash
ssh-keygen -t ed25519 -C "flowpost-deploy"
```

  Вміст `~/.ssh/id_ed25519.pub` вставте в поле "New SSH Key" у консолі DO.
- **Hostname**: наприклад `flowpost-bot`.

Натисніть Create Droplet, зачекайте ~1 хв, скопіюйте виданий IP.

## 2. Підключитись і підготувати сервер

```bash
ssh root@YOUR_DROPLET_IP
```

Docker вже встановлено (marketplace-образ). Перевірте:

```bash
docker --version && docker compose version
```

Базовий firewall (SSH дозволено, все інше зайве закриваємо — вхідний HTTP не потрібен,
бот сам ініціює зʼєднання до Telegram):

```bash
ufw allow OpenSSH
ufw enable
```

## 3. Клонувати репозиторій

```bash
apt-get update && apt-get install -y git
git clone https://github.com/mylayed/flowpost.git /opt/flowpost
cd /opt/flowpost
```

Якщо репозиторій приватний — знадобиться GitHub Personal Access Token замість пароля,
або deploy key.

## 4. Створити продакшн `.env`

```bash
cp .env.example .env
nano .env
```

Заповніть реальними значеннями з Railway (Project → Variables): `BOT_TOKEN`, `ADMIN_IDS`,
`SUPPORT_CONTACT`, `ANTHROPIC_API_KEY`, `WEBAPP_ENABLED`, `LIQPAY_*` (лише для старих LiqPay-підписок) і т.д.

Важливо для цього способу деплою:

- `DATABASE_URL` і `REDIS_URL` — **не чіпайте**, їх підставляє `docker-compose.prod.yml`
  (значення в `.env.example` для них ігноруються в проді).
- Додайте новий рядок, якого немає в `.env.example`:

  ```
  POSTGRES_PASSWORD=придумайте-довгий-випадковий-пароль
  ```

- `WEBHOOK_BASE_URL` лишіть порожнім (немає домену → polling, як і зараз).
- `PORT` можна лишити 8080 — назовні він не відкривається.

## 5. Перенести базу даних з Railway

На вашому компʼютері (не на дроплеті) знайдіть у Railway → Postgres → Connect
рядок `DATABASE_URL` (виду `postgresql://user:pass@host:port/railway`) і зробіть дамп:

```bash
pg_dump --no-owner --no-acl "RAILWAY_DATABASE_URL" > flowpost_dump.sql
```

(Якщо `pg_dump` не встановлено локально — можна виконати цю команду прямо на дроплеті,
туди ж і скопіювати файл далі.)

Скопіюйте дамп на дроплет:

```bash
scp flowpost_dump.sql root@YOUR_DROPLET_IP:/opt/flowpost/
```

На дроплеті підніміть поки що тільки Postgres, зачекайте на healthy і відновіть дамп:

```bash
cd /opt/flowpost
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml exec -T postgres pg_isready -U flowpost
docker compose -f docker-compose.prod.yml exec -T postgres psql -U flowpost -d flowpost < flowpost_dump.sql
```

## 6. Зупинити бота на Railway (уникнути конфлікту polling)

Telegram дозволяє лише одному long-polling інстансу отримувати оновлення одночасно.
**Перед стартом бота на DO обовʼязково зупиніть/видаліть сервіс на Railway**
(Railway → Deployments → Remove/Pause), інакше обидва інстанси конфліктуватимуть.

## 7. Запустити бота на DO

```bash
cd /opt/flowpost
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f bot
```

У логах маєте побачити `Starting as @your_bot_username` і `Polling mode`. Alembic-міграції
застосовуються автоматично при старті (`run_migrations` у `__main__.py`).

Напишіть боту в Telegram — перевірте, що відповідає і бачить старі дані (наприклад
`/stats`, якщо ви адмін).

## 8. Прибирання

- Видаліть тимчасовий `flowpost_dump.sql` з дроплета: `rm /opt/flowpost/flowpost_dump.sql`
- Видаліть Postgres-плагін і сервіс на Railway, коли переконаєтесь, що все стабільно
  працює кілька днів.
- (Опційно) Автозапуск після ребута дроплета вже забезпечує `restart: unless-stopped`.

## Оновлення бота надалі

```bash
cd /opt/flowpost
git pull
docker compose -f docker-compose.prod.yml up -d --build
```
