# ComfyUI Controller — پل امن Workflowهای قدیمی به Direct Queue

**مبنای بررسی کد:** مخزن `ImanNasrEsfahani/comfyui-controller`، شاخه `main`، Commit مشاهده‌شده `db9df9e6e61ebe88f2ce47bc62f8db971609a30a` در ۲۰۲۶-۱۰-۱۶. دسترسی فقط خواندنی. هیچ تغییری در GitHub، سرور واقعی، دیتابیس یا Salad توسط این بسته اعمال نشده است.

## این نسخه دقیقاً چه چیزی حل می‌کند؟

در نصب فعلی، `model_families`، `model_versions`، `worker_images` و `deployment_profiles` در **Registry جدید** خالی‌اند، بااینکه چهار Workflow قدیمی و تنظیمات `salad_active` وجود دارند. مدل معتبر در UI جدید فقط پس از شواهد امضا، سازگاری و Deployment فعال نمایش داده می‌شود. کد فعلی عملیات approve/activate را 503 می‌کند؛ لذا افزودن دستی `ready` یا `tested_pass` راه‌حل معتبر نیست.

این بسته یک مسیر **موقت، مجزا و مخصوص مدیر** اضافه می‌کند تا Workflowهای ذخیره‌شده، Hash ثابت و نام فایل‌های مدل مشاهده شوند و مدیر **پس از آزمون واقعی سازگاری روی Worker** بتواند Workflowهای تأییدشده توسط *خودش* را با شیوه Direct Queue سابق اجرا کند. مدل‌ها در Registry اصلی همچنان `unverified` باقی می‌مانند. رابط تازه `LegacyDirectPanel` در بالای صفحه «ساخت تصویر» برای مدیر ظاهر می‌شود؛ منوی مدل استاندارد همچنان خالی می‌ماند تا مسیر Registry کامل شود.

مهم‌ترین تفاوت فنی این مسیر با کد قدیمی: پیش از آنکه Worker بتواند Job را Claim کند، درخواست، Snapshot، `owner_user_id` و `ownership_state='verified'` در **یک تراکنش SQLite** ذخیره می‌شوند. Assetهای خروجی صرفاً مالکیت Job والد را به ارث می‌برند؛ ورودی‌های تصاویر بین کاربران جدا می‌مانند؛ CSRF و نقش مدیر کنترل می‌شود؛ درخواست تکراری دوباره در صف قرار نمی‌گیرد.

## محتویات ZIP

| مسیر | نوع | کاربرد |
| --- | --- | --- |
| `backend/app/owner_direct_bridge.py` | جدید | Bridge امن، انتخاب Workflow، صف اتمیک، جلوگیری از درخواست تکراری، کنترل Reference |
| `frontend/src/pages/legacy-direct/LegacyDirectPanel.jsx` | جدید | رابط موقت مدیر و آپلود تصاویر خصوصی |
| `scripts/apply_owner_direct_bridge.py` | جدید | ساخت سه فایل جایگزین با کنترل SHA، بدون overwrite کورکورانه |
| `scripts/owner_direct_preflight.py` | جدید | شناسایی فقط‌خواندنی Workflowها، Image و وضعیت Queue |
| `tests/test_owner_direct_bridge.py` | جدید | آزمون‌های امنیتی و سازگاری |
| `docs/README-FA.md` | جدید | راهنمای حاضر |
| `backend/app/owner_api.py` | توسط Installer تغییر می‌کند | اتصال `GET /api/legacy-direct/workflows` و `POST /api/jobs` به Bridge |
| `backend/app/job_records.py` | توسط Installer تغییر می‌کند | انتساب اتمیک مالکیت خروجی Worker و پشتیبانی از DBهای Legacy |
| `frontend/src/app/router.jsx` | توسط Installer تغییر می‌کند | نمایش پنل در صفحه ساخت تصویر |

**چرا سه فایل اصلی داخل ZIP به شکل جایگزین کامل نیستند؟** فایل‌های واقعی GitHub در این جلسه فقط از طریق اتصال **Read-Only** قابل خواندن بودند، و نسخه Git محلی کامل برای Export دقیق در اختیار اجراکننده نبود. به همین دلیل، ابزار Installer فقط وقتی *SHA واقعی فایل‌های هدف* دقیقاً با Revision بررسی‌شده برابر باشد سه جایگزین را از همان فایل‌های Checkout می‌سازد؛ از دستکاری فایل‌های جدیدتر و از بازنویسی ناامن جلوگیری می‌کند. نیاز به اجرای آن یک‌بار پیش از Commit است.

## مرحله ۱: ساخت نسخه قابل Commit در یک Checkout محلی

ZIP را **در ریشه** نسخه به‌روز GitHub Extract کن. روی سرور اصلی نیز ممکن است، اما برای QA بهتر است ابتدا در Checkout توسعه‌ای انجام شود.

```bash
cd /path/to/comfyui-controller
git status --short
# قبل از ادامه تغییرات محلی را بررسی کن؛ هیچ reset --hard اجرا نکن.
git log -1 --oneline
python3 scripts/apply_owner_direct_bridge.py --repo .
# فقط بعد از Dry-run موفق:
python3 scripts/apply_owner_direct_bridge.py --repo . --apply
python3 -m compileall -q backend/app scripts
python3 -m pytest -q tests/test_owner_direct_bridge.py
python3 scripts/ci_python_matrix.py --repo .
node --test tests/*.mjs
npm --prefix frontend run build
git diff --check
git status --short
```

بعد از بازبینی Diff، فایل‌های تغییرکرده را به GitHub Commit/Push کن. اگر SHAها متفاوت باشند، Installer `SAFE STOP` می‌دهد؛ در این حالت به‌جای دستکاری SHA یا جایگزینی اجباری، باید نسخه را با Commit جدید تطبیق داد.

## مرحله ۲: انتقال نسخه از GitHub به سرور

ابتدا مطمئن شو Job فعال وجود ندارد و از SQLite با روش `Connection.backup` نسخه پشتیبان مستقل داری (و مسیر Volume را از بین نمی‌بری). سرور فعلی Backend، Frontend و Scheduler را از کد **local build** می‌سازد؛ GHCR فقط Image مربوط به Salad Worker است.

```bash
cd /var/www/comfyui-controller
git status --short
git pull --ff-only origin main
docker compose --profile direct config --quiet
docker compose --profile direct build backend frontend
docker compose --profile direct up -d --no-deps --force-recreate --no-build backend frontend
docker compose --profile direct ps
curl -fsS http://127.0.0.1:8100/health
```

Scheduler موجود را بدون ضرورت Restart نکن. هیچ `docker compose down -v`، `docker volume rm` یا `git reset --hard` انجام نده. امکان خروجی GPU منوط به وضعیت همان Worker فعال روی Salad است.

## مرحله ۳: گزارش Workflowهای واقعی بدون نوشتن در DB

این فایل از داخل Backend Container با STDIN اجرا می‌شود، چون Dockerfile فعلی فقط پوشه `app` را به Image کپی می‌کند:

```bash
cd /var/www/comfyui-controller
docker compose exec -T backend python - < scripts/owner_direct_preflight.py
```

این دستور نام/شناسه Workflow، نام basename مدل‌های مشاهده‌شده، Hash دقیق Graph، وضعیت Queue و Image فعال را نشان می‌دهد. هیچ Prompt، رمز، توکن، کلید یا مسیر خصوصی R2 را چاپ نمی‌کند. این داده‌ها **اثبات سلامت مدل در GPU نیستند**.

## مرحله ۴: فعال‌سازی محدود پس از تست واقعی

قبل از تغییر `.env`، به‌صورت مستقل باید روی Worker در Salad مطمئن شوی:

1. همان Image واقعی و مدل‌های موردنظر روی GPU بارگذاری شده‌اند؛ ComfyUI و Nodeها آماده‌اند و خروجی یک inference نمونه در R2 با Hash/مالکیت صحیح ثبت می‌شود.
2. Nameهای Model Loader که در گزارش دیده می‌شود، دقیقاً در Image موجود است؛ حجم VRAM/مجوز/سازگاری گراف و پاسخ Worker تأیید شده است.
3. هیچ Job در وضعیت بحرانی/نامشخص وجود ندارد و برای مصرف GPU آماده‌ای.

سپس در `.env` **سرور** (نه GitHub) این مقادیر را با مشخصات واقعی خودت تنظیم کن:

```dotenv
OWNER_DIRECT_JOB_ENABLED=true
OWNER_DIRECT_IMAGE=ghcr.io/imannasresfahani/comfyui-controller-salad-worker:fp8-direct-v1
OWNER_DIRECT_ALLOWLIST=WORKFLOW_ID@ACTUAL_64_DIGIT_GRAPH_SHA256
```

برای چند Workflow، جفت‌های `ID@SHA` را با `,` از هم جدا کن. رشته‌های بالا مثال‌اند؛ مقدار واقعی `OWNER_DIRECT_ALLOWLIST` را فقط از Preflight همان دیتابیس دریافت کن. به‌شدت توصیه می‌شود ابتدا فقط **یک Workflow تأییدشده** را Allowlist کنی. سپس:

```bash
cd /var/www/comfyui-controller
docker compose --profile direct up -d --no-deps --force-recreate backend
docker compose logs --tail=80 backend
```

به `/create/image` وارد شو؛ در پنل «اجرای Workflow قدیمی — مخصوص مدیر» Workflow را انتخاب کن، فیلدها را تکمیل و Job را ارسال کن. تا قبل از فعال‌سازی، دکمه ارسال نمایش داده نمی‌شود. `OWNER_DIRECT_JOB_ENABLED=false` مجدداً این مسیر را می‌بندد.

## محدودیت‌های مهم و کارهای باز

- این مسیر *Register/Approve/Activate خودکار Phase07* نیست. در صفحه استاندارد «مدل» تا زمانی که pipeline واقعی OCI signature، model SHA، Worker's inference test و active revision تکمیل نشود، مدل تأییدشده‌ای ظاهر نخواهد شد.
- فقط حساب‌های دارای نقش `admin` یا `superadmin` به Pilot دسترسی دارند؛ کاربران عادی نمی‌توانند Job ارسال کنند. نشر عمومی بدون QA مستقل ممنوع است.
- عملیات Retry در `owner_api` همچنان 503 است؛ درخواست جدید برای اجرای دوباره نیاز به ID جدید دارد. بسته‌ای از bypass جدید برای Worker v11 نمی‌سازد.
- در تست‌های محلی ۱۲ آزمون کاملاً آفلاین پاس شده‌اند؛ اتصال واقعی به DB خصوصی، Worker یا R2 اجرا نشده و موفقیت Production یا کل CI ادعا نمی‌شود.
- اگر مدل فایل‌های غیرواقعی، Workflow شامل Nodeهای غیرنصب‌شده یا Image نامطابق باشد، حتی اجرای مجاز هم می‌تواند شکست بخورد. این به معنای نیاز به رفع سازگاری Worker است، نه مجوز تغییر دستی `tested_pass`.

## Rollback

برای توقف فوری ارسال جدید بدون حذف Jobهای موجود:

```dotenv
OWNER_DIRECT_JOB_ENABLED=false
```

سپس فقط Backend را Recreate کن. Jobهای فعال را بدون بررسی نتیجه و Lease حذف نکن. فایل‌های تغییریافته را تنها از Git commit مشخص و با بررسی وضعیت Job و Backup برگردان؛ نه با حذف SQLite یا volume.
