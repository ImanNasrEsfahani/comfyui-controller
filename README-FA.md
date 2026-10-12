# ComfyUI Controller — فایل‌های کامل جایگزینی GitHub

**مبنای دقیق:** `ef0c166689120bf02a56f159a373c1ec84b2bd73` (`review 03`).

این ZIP **حاوی خود فایل‌های نهایی** است، نه Installer یا اسکریپت تولیدکننده فایل. تمام فایل‌ها با مسیر دقیق مخزن قرار داده شده‌اند؛ آن‌ها را مستقیماً در GitHub از طریق Upload files در همان مسیرها اضافه/جایگزین و یک Commit کن. دسترسی دستیار به مخزن فقط خواندنی بوده و هیچ Commit یا Push از جانب او انجام نشده است.

## محتوا

- `backend/app/integrated_main.py` (جدید): Entrypoint یکپارچه Backend، نصب Routerهای نسخه جدید، تقدم مسیرهای owner-scoped و غیرفعال‌کردن مسیرهای global ناامن Legacy از سطح API جدید.
- `backend/app/migrate_offline.py` (جدید): Backup و اجرای مرحله‌ای Migration روی کپی آفلاین، تطبیق تعداد رکوردها، نصب اتمیک دیتابیس پس از توقف سرویس‌ها.
- `backend/app/create_admin.py` (جدید): ساخت Superadmin به شکل تعاملی با رمز مخفی.
- `frontend/Dockerfile` (جایگزین کامل): فعال‌سازی UI احراز هویت و Studio در زمان `vite build`.
- `docker-compose.yml` (جایگزین کامل): استفاده Backend از `app.integrated_main:app` با Volumeها، پورت‌ها و Scheduler سابق.
- `scripts/configure_auth_env.py` (جدید): تنظیم ایمن فلگ‌ها در `.env` خصوصی **روی سرور**، بدون تغییر Secrets و بدون افزودن `.env` به Git.
- `tests/test_integrated_entrypoint.py` (جدید): تست‌های ساختاری فایل‌های تحویلی.

## محدودیت صریح و اساسی

این بسته **Login/UI و APIها را یکپارچه می‌کند، نه قابلیت‌های ناقص محصول را**: طبق سورس Commit مبنا، `owner_api` درخواست Generate/Retry مالک‌محور و `worker_v11_api` Claim نسخه ۱۱ را فعلاً با HTTP `503` رد می‌کنند. زیرساخت Video نیز به معنای اجرای واقعی مدل نیست و تا تأیید مستقل، فلگ آن غیرفعال می‌ماند. مدل‌های آماده/تأییدشده و یکپارچگی End-to-End GPU همچنان نیازمند کار و تست مستقل هستند. در این نسخه داده‌های Legacy بدون مالک به‌صورت خودکار به حساب تازه نسبت داده نمی‌شوند. آخرین Unified CI مبنا نیز یک تست ناموفق (`Salad instances`, 502) دارد. این نسخه بدون تأیید دستی نباید محصول عمومی نهایی تلقی شود.

## انتقال از GitHub به سرور (بعد از ثبت Commit توسط خودت)

دستورات را در Linux VM و در مسیر پروژه اجرا کن. فرض مسیر `/var/www/comfyui-controller` و `.env` قبلی محفوظ است.

```bash
set -euo pipefail
cd /var/www/comfyui-controller
git status --short
# این دستور باید هیچ خروجی نداشته باشد؛ در غیر این صورت متوقف شو.
test -z "$(git status --porcelain)"
git pull --ff-only origin main
git log -1 --oneline
docker compose --profile direct config --quiet
```

### پیش‌شرط‌های حیاتی

- پیش از توقف سه سرویس مطمئن شو Job در حال پردازش/انتقال وجود ندارد؛ در غیر این صورت صبر کن.
- درایو/مسیر Backup فضای کافی داشته باشد؛ R2 و Secrets موجود در `.env` نباید جابه‌جا شوند.
- در اجرای اولیه Migration روی کپی، ۱۳۷ Job و ۶۲ Asset ورودی و ۸۰ Asset خروجی قدیمی باید حفظ شوند. این شمارش مربوط به وضعیت گزارش‌شده قبلی است؛ اگر تعداد تغییر کرده، معیار آخرین Snapshot معتبر است.
- از Volume مشترک با `docker compose down -v` استفاده نکن؛ `git reset --hard` هم اجرا نکن.

### بررسی Jobهای فعال، Build و تنظیم `.env`

```bash
cd /var/www/comfyui-controller
# فقط آمار وضعیت Jobها؛ هیچ متن پرامپت یا رمز نمایش نمی‌دهد
docker compose exec -T backend python - <<'PY'
import os,sqlite3
path=os.environ.get('DB_PATH','/app/data/controller.db')
with sqlite3.connect('file:'+path+'?mode=ro',uri=True) as c:
 print('Jobs by state:', c.execute('SELECT state,count(*) FROM jobs GROUP BY state ORDER BY state').fetchall())
PY

# Build قبل از توقف سرویس‌ها
docker compose --profile direct build backend frontend scheduler

# Backup private env
BACKUP_DIR="$HOME/comfyui-backups/new-ui-$(date +%Y%m%d-%H%M%S)"
mkdir -p -m 700 "$BACKUP_DIR"
cp -a .env "$BACKUP_DIR/.env.pre-upgrade"
printf '%s\n' "$BACKUP_DIR" > "$HOME/comfyui-backups/LAST_INTEGRATED_UI_BACKUP"
chmod 600 "$HOME/comfyui-backups/LAST_INTEGRATED_UI_BACKUP"

# Enable Auth and multiuser UI (preserving keys; no credentials printed)
python3 scripts/configure_auth_env.py .env --origin https://comfy.imannasr.com

# CRITICAL: once confirmed that no GPU job is active, stop ALL readers/writers
# and prevent stale scheduler from touching SQLite during copy migration.
docker compose --profile direct stop scheduler frontend backend
```

### اجرای Offline Migration روی دیتابیس واقعی، با Snapshot معتبر

تنها پس از توقف کامل سرویس‌ها و اثبات نبود Job فعال:

```bash
cd /var/www/comfyui-controller
BACKUP_DIR="$(cat "$HOME/comfyui-backups/LAST_INTEGRATED_UI_BACKUP")"
test -d "$BACKUP_DIR"

for action in snapshot migrate install; do
  echo "DATABASE STEP: $action"
  docker compose --profile direct run --rm -T --no-deps \
    -v "$BACKUP_DIR:/backup" backend \
    python -m app.migrate_offline "$action"
done
```

**اخطار:** مرحله `install` دیتابیس واقعی را با کپی مهاجرت‌داده‌شده جایگزین می‌کند. فقط وقتی گام `migrate` بدون خطا تمام شد باید اجرا شود. اگر خطا دیدی، متوقف شو و وضعیت را بررسی کن. اجرای چندباره Snapshot روی همان پوشه تعمداً رد می‌شود.

### Restart، ایجاد مدیر و بررسی

```bash
cd /var/www/comfyui-controller
docker compose --profile direct up -d --no-deps backend frontend
curl -fsS http://127.0.0.1:8100/health
curl -sS -o /dev/null -w 'Auth session: %{http_code}\n' http://127.0.0.1:8100/api/auth/session
curl -sS -o /dev/null -w 'Frontend login: %{http_code}\n' http://127.0.0.1:3100/login
curl -sS -o /dev/null -w 'Private jobs without cookie: %{http_code}\n' http://127.0.0.1:8100/api/jobs
# انتظار: 200، 200، 401 به ترتیب برای سه درخواست پایانی. اگر خلاف آن بود Scheduler را روشن نکن.

docker compose exec backend python -m app.create_admin
# پس از تست Login و اطمینان از نبود خطا، Scheduler همان نسخه را شروع کن:
docker compose --profile direct up -d --no-deps scheduler
```

سپس از طریق `https://comfy.imannasr.com/login` با حساب مدیر وارد شو. ثبت‌نام عمومی عمداً غیرفعال است تا زمانی که سیاست دعوت/ایمیل آزموده شود.

### Rollback با آگاهی از پیامدها

نسخه قبلی فایل‌ها از Git قابل بازیابی است ولی **تنها یک rollback آزمایش‌شده** برای دیتابیس بعد از Migration قابل اعتماد است. برای بازگشت، ابتدا همه سرویس‌ها را متوقف کن، کدهای قبلی را در Git با Commit مناسب برگردان (بدون پاک‌کردن Volume)، و فقط در صورت تأیید سازگاری، Snapshot آفلاین `controller-original.sqlite3` را به کمک عملیات `restore` بازیابی کن. بازیابی Snapshot تمام تغییرات دیتابیس پس از نصب را از بین می‌برد؛ بدون تأیید نسخه و زمان‌بندی آن را اجرا نکن.

## تست‌های تحویل

`python3 -m pytest -q tests/test_integrated_entrypoint.py`

کدهای ارسالی با `py_compile` و تست ساختاری و شبیه‌سازی Routeها بررسی می‌شوند؛ **تست واقعی Docker/Browser/Salad روی VM هنوز توسط کاربر باید انجام شود**.
