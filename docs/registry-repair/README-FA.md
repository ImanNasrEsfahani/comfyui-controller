# ComfyUI Controller — ترمیم CI و آماده‌سازی کاتالوگ مدل‌ها

## وضعیت واقعی و محدودیت‌ها

این بسته بر اساس **GitHub main تا commit `ed16f25b5504fda266cdca894bb352c8b4c82b3d`** و آخرین اجرای مشاهده‌شده Unified CI (`38189155070`) تهیه شده است. دسترسی به GitHub فقط خواندنی بوده؛ هیچ تغییر، اجرای Action یا استقرار زنده انجام نشده است.

از خروجی دیتابیس سرور می‌دانیم: `model_families=0`، `model_versions=0`، `worker_images=0`، `deployment_profiles=0` و `workflows=4`. علت خالی بودن منوی مدل، خالی بودن Registry و الزام داشتن جفت Worker/Image/Model تأییدشده است، نه لزوماً پاک شدن مدل‌های نصب‌شده در Salad.

**کارهای انجام‌شده در این بسته:**

1. رفع Mock تست قدیمی `tests/check_frontend_backend_upgrade.py` برای سازوکار Stop جدید. درخواست POST به سرویس Salad از `_provider_call` می‌رود؛ تست با `202 Accepted` آن را فقط pending می‌شمارد و دیگر Stop قطعی جعل نمی‌کند. احراز هویت و سانیتایز خروجی همچنان تست می‌شوند.
2. افزودن پذیرش SHA256 دقیق برای نسخه بررسی‌شده همان تست در `scripts/ci_fixture_fixes.py`. SHAهای اصلی، محدودیت تغییر در fixture تاریخی و `--check` همچنان حفظ شده‌اند. هیچ فیلتر آزمون یا شکست اجباری CI حذف نشده است.
3. ایجاد `scripts/model_onboarding.py` برای **بازرسی فقط‌خواندنی** Workflowهای موجود و شناسایی Loaderها، تهیه الگوی Manifest برای ثبت اطلاعات واقعی مدل و امکان ورود **Draft** پس از تهیه نسخه پشتیبان سازگار SQLite. هیچ Model را `ready`، هیچ Image را `approved` و هیچ Deployment را `active` نمی‌کند.
4. افزودن آزمون‌های واحدِ امنیتی و idempotency ابزار مرحله قبل.

**کارهای هنوز انجام‌نشده و الزامی:** جمع‌آوری شناسه واقعی مدل‌ها و SHA256 فایل weightها؛ بررسی license، VRAM، digest واقعی OCI Image، امضای معتبر image؛ تأیید Runtime و سازگاری مدل در Worker مستقرشده؛ برقراری امکان Activate/Approve در Backend پس از پیاده‌سازی اعتماد و rollback؛ مهاجرت Workflow به Schema معتبر و اتصال Owner-safe Generate/Retry. به‌طور مشخص endpoint `POST /api/jobs` در `backend/app/owner_api.py` فعلاً 503 می‌دهد، و approval/activation در `backend/app/registry_api.py` نیز 503 برمی‌گردانند. صرف نصب این ZIP منو را پر نمی‌کند یا ساخت تصویر را فعال نمی‌سازد.

## نصب فایل‌ها در مخزن

ZIP را از ریشه repo Extract/Copy کن (مسیرها تغییر نکند):

- `tests/check_frontend_backend_upgrade.py` — جایگزین
- `scripts/ci_fixture_fixes.py` — جایگزین
- `scripts/model_onboarding.py` — فایل جدید
- `tests/test_model_onboarding_repair.py` — فایل جدید
- `docs/registry-repair/README-FA.md` — راهنما، فایل جدید

توجه: در بسته ZIP این راهنما زیر `docs/registry-repair/README-FA.md` قرار گرفته است. هیچ `.env`، SQLite DB، Workflow یا image، فایل secret و اجرای Salad تغییر نمی‌کند.

بعد از انتقال به GitHub، اجرای Unified CI بر اثر تغییر `tests/**` و `scripts/**` فعال می‌شود. انتظار اصلاح **همان شکست مشاهده‌شده** را داریم؛ تا وقتی Actions جدید واقعاً اجرا نشده، موفقیت کل CI یا Docker Build قابل تأیید نیست.

## تست روی کپی محلی repo

```bash
python -m pytest -q tests/test_ci_fixture_fixes.py tests/test_model_onboarding_repair.py
python scripts/ci_fixture_fixes.py --check
python scripts/ci_python_matrix.py --repo .
node --test tests/*.mjs
npm --prefix frontend run build
```

آخرین CI رسمی مشاهده‌شده Frontend را PASS و Python را FAIL نشان می‌داد: 52 فایل Python موفق و یک فایل ناموفق، با خطای `502 != 200` در تست `test_instances_are_sanitized_and_stop_requires_authentication`. اجرای Build Salad Worker قبلی نیز هنگام گیت تست‌ها متوقف شده است؛ خود ساخت GPU image هنوز تأیید نشده و باید با اجازه صریح و بعد از CI موفق انجام شود.

## دریافت گزارش چهار Workflow از دیتابیس سرور — فقط خواندنی

از ریشه مخزن روی سرور (اسکریپت جدید هنوز داخل Dockerfile کپی نشده، پس آن را با stdin به Python داخل کانتینر بده):

```bash
cd /path/to/comfyui-controller

docker compose exec -T backend \
  sh -c 'python - --db "$DB_PATH"' \
  < scripts/model_onboarding.py
```

خروجی تعداد Workflowها، نام‌ها و مدل‌لودرها، نام basename فایل مدل (نه مسیر یا secret)، و تعداد آیتم‌های Registry را نشان می‌دهد. این فرمان فقط DB موجود را می‌خواند. اطلاعاتی مانند Prompt اصلی یا ENV مخفی نمایش داده نمی‌شود.

برای ساخت الگوی ورود Draft روی volume کانتینر (اختیاری):

```bash
docker compose exec -T backend \
  sh -c 'python - --db "$DB_PATH" --template /app/data/model-onboarding-manifest.json' \
  < scripts/model_onboarding.py
```

الگو عمداً `models: []` است و بدون تکمیل دقیق مشخصات، امکان وارد کردن ندارد. از درج SHA ساختگی، نام مدل حدسی یا وضعیت runtime تأییدنشده پرهیز کن. قبل از هر عملیاتی باید با Worker واقعی، لایسنس و artifactهای موجود تطبیق داده شود.

برای واردکردن Draftها، ابتدا Manifest واقعی را در کانتینر قرار بده؛ سپس فرمان زیر، قبل از هر write یک backup سازگار SQLite در volume می‌سازد. مسیر backup باید **جدید** باشد و نباید وجود داشته باشد:

```bash
# قبل از اجرا manifest معتبر را به کانتینر منتقل کرده باش.
docker compose exec -T backend \
  sh -c 'python - --db "$DB_PATH" --manifest /app/data/model-onboarding-manifest.json --import-drafts --backup /app/data/registry-before-draft-import.sqlite3' \
  < scripts/model_onboarding.py
```

این مرحله صرفاً اطلاعات در حالت `draft` را ثبت می‌کند. برای مدل‌هایی که از قبل واقعاً تست نشده‌اند، `ready` کردن مستقیم دیتابیس، تزریق دستی `tested_pass`، خاموش‌کردن auth و انتشار بدون تأیید فنی **ممنوع** است. Backup بیرون از سرور نیز نگهداری شود؛ آن را به GitHub نفرست.

## بازبینی بعد از CI

1. Actions > `ComfyUI Controller - Unified CI`: هر دو `python-and-worker` و `frontend` و مرحله `result` باید Success شوند.
2. Actions > `Build Salad GPU Worker`: Build به‌صورت دستی و با تأیید صریح اجرا می‌شود و خودش deploy روی Salad انجام نمی‌دهد.
3. حتی اگر هر دو Action موفق باشند، پلتفرم multi-user تا تأیید واقعی API/Worker/Model و مالکیت اتمیک Job هنوز برای Generate آماده انتشار نیست.

## شواهد آزمون این بسته

- `python -m py_compile` برای سه فایل Python اصلاحی/جدید موفق بود.
- `pytest` در محیط محلیِ محدود روی دو ماژول تست اصلاحات: **10 passed**.
- هیچ تست End-to-End با Salad واقعی، API واقعی سرور یا SQLite خصوصی کاربر اجرا نشده است.
- اجرای کل 610 تست قبلی و Docker image build در این محیط ممکن نبود؛ پس عبارت «همه Buildها موفق شدند» نادرست است.
