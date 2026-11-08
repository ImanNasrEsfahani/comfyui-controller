# گزارش ممیزی و تست نسخه اصلاح‌شده SCAIL-2 Character Replacement

**مبنای بررسی:** فایل ZIP اولیه ۱۹ فایلی؛ ساختار واقعی شاخه `main` مخزن `ImanNasrEsfahani/comfyui-controller` با دسترسی فقط‌خواندنی؛ فهرست وظایف ۶۰گانه و سند UI/UX پروژه؛ Workflow ثابت `ruashots/scail2-skill` در commit `91a79f518fc48ae4546fa815eacffa4bf194a3c6`؛ فهرست مدل‌های رسمی Hugging Face.

## نتیجه تست‌های قابل اجرا

| رده | وضعیت | شواهد |
|---|---|---|
| Python syntax | PASS | `python -m compileall` برای Backend، Worker، Scripts و Tests |
| Backend API + واقعی SQLite | PASS | POST upload، ownership، CSRF، idempotency، queue و lease |
| Worker (Mock inference) + FFmpeg واقعی | PASS | MP4 کوتاه از `ffmpeg`، ادغام صوت اختیاری، ذخیره ساختگی R2، دریافت MP4 |
| مالکیت فایل و HTTP Range | PASS | ۲۰۶ Partial Content و رد دسترسی کاربر دوم |
| Cancel / Retry / Stalled | PASS | وضعیت نامطمئن نیازمند بازبینی مدیر؛ لغو بدون تأیید ComfyUI قطعی نمی‌شود |
| Migration و Backup | PASS | تست دو بار اجرا و نگهداری هر دو فایل backup |
| Patcher | PASS | اجرای تکراری idempotent و عدم تغییر هیچ فایل در صورت Anchor ناسازگار |
| Artifact hash و sharding | PASS | تست ساخت Shard کوچک، Verify، Restore و رد قطعه خراب |
| GitHub Actions YAML و مدل‌ها | PASS static | جدول مدل‌ها ۷ SHA-256 کامل؛ Tag GHCR lowercase و CI تست‌ها |
| Frontend JSX و CSS | PASS syntax | TypeScript transpile و CSS parser محلی؛ نه Browser E2E |
| Workflow حقیقی upstream | PASS static | ۴۰ Node در گراف اصلی؛ ۳۶ Node پس از تغییرات کیفیت و حذف خروجی‌های فرعی؛ هیچ اتصال معلقی در گراف کنترل‌شده |
| مجموعه تست‌های Python | **۲۱ PASS** | `python -m unittest discover -s tests -p 'test_scail2*.py' -v` |

## نقص‌هایی که اصلاح شدند

- مسیر ویرایش شخصیت در `routeUtils.js` ثبت نشده بود و در Router اصلی به 404 تبدیل می‌شد.
- Patcher قدیمی، امکان ایجاد تغییرات نیمه‌اعمال‌شده را داشت؛ نسخه جدید همه مسیرها را پیش از اولین نوشتن اعتبارسنجی می‌کند.
- نام Backup دارای دقت ثانیه بود؛ اجرای دوباره در همان ثانیه آن را بازنویسی می‌کرد.
- گرفتن Lease قبل از ساخت لینک‌های R2، در صورت شکست Signer یک Job یتیم ایجاد می‌کرد.
- Cancel در Worker بدون دریافت تأیید اجرای Interrupt گزارش می‌شد.
- Jobهای با Worker گم‌شده می‌توانستند دوباره به اجرا بروند، درحالی‌که Worker قبلی شاید همچنان در حال پردازش بود.
- وضعیت Readiness Worker به‌صورت ثابت false گزارش می‌شد؛ اکنون Heartbeat اختصاصی دارد.
- فهرست مدل‌ها برای VAE، Text Encoder و CLIP Vision فاقد SHA-256 بود؛ اکنون با هش‌های اصلی بررسی می‌شوند.
- امکان عبور Shard ناقص از Build قبل از انتشار Image وجود داشت؛ اکنون هش کامل ۷ وزن پیش از Push تأیید می‌شود.
- نام GHCR از حروف بزرگ GitHub repository owner استفاده می‌کرد و در Docker tag نامعتبر می‌شد؛ lowercase شد.
- آپلود دیررس می‌توانست در UI به فایلی که کاربر بعداً انتخاب کرده بود منتسب شود؛ نسخه آپلود کنترل می‌شود.
- Seed عددی بزرگ در مرورگر با `Number` گرد می‌شد؛ به‌شکل رشته ارسال و سمت Backend به int تبدیل می‌شود.
- بررسی Signature و Limit روی مسیر فایل ویدیویی بهینه شد و صف Job سقف اولیه پیدا کرد.

## محدوده مهم و آزمون‌های باقی‌مانده

این تست‌ها یک مدل شبیه‌سازی‌شده به‌جای SCAIL-2 به کار بردند. در نتیجه **هیچ اثباتی وجود ندارد که NVIDIA RTX 5090 مدل FP16 را بدون مشکل VRAM اجرا می‌کند، یا Docker build واقعی تضمین‌شده است**. همچنین کانتینر واقعی Salad، ComfyUI Native، KJNodes، VideoHelperSuite، Easy Use، SAM3، دسترسی HF و R2 در این محیط تست نشده‌اند. برای ادامه، Build واقعی `:thin` در GHCR و اجرای یک Job کوتاه در Salad، سپس آزمون کیفیت `:fp16-baked` لازم است.

سه قابلیت همچنان خارج از نسخه اول هستند: Autoscaling مستقل از GPU بر اساس صف SCAIL-2، پاکسازی دوره‌ای فایل‌های موقت/بدون مرجع، و اتصال خروجی‌ها به Library عمومی Controller. این موارد در README صریحاً از بخش تکمیل‌شده جدا شده‌اند. قابلیت چندکاراکتری نیز در نسخه اول ارائه نشده است.

**نتیجه ممیزی:** بسته اصلاح‌شده آماده بررسی و اعمال روی Checkout و شروع CI واقعی است؛ نه گواهی Production Ready یا Runtime GPU تأییدشده. هیچ تغییر یا Commit به مخزن GitHub اصلی ارسال نشده است.


## پیوست ممیزی v3 — پاسخ به خطای GitHub Actions

- **شواهد ورودی:** `python-and-worker` با دو خطای collection شکست خورد:
  `test_scail2_deep.py` و `test_scail2_overlay.py` هر دو در import
  `model_parts.py` و بارگذاری `huggingface_hub` متوقف شدند.
- **علت:** Dependency دانلود مدل، در سطح ماژول import می‌شد درحالی‌که
  Job عمومی تست فقط وابستگی‌های Backend را نصب کرده بود.
- **رفع:** تبدیل importهای `huggingface_hub` در `model_parts.py` و
  `download_models.py` به import تنبل درون تابع دانلود؛ حفظ تابع خارجی
  برای patchهای Mock تست‌ها.
- **تست رگرسیون جدید:** بارگذاری دو ماژول در حالی که import بسته عمداً
  غیرمجاز شده است؛ بدون نصب مدل و بدون درخواست شبکه.
- **نتیجه محلی:** ۲۱ تست SCAIL-2 موفق. نتیجه ۶۵۳ تست اصلی مخزن را
  تا Re-run دوباره GitHub نمی‌توان «تأیید نهایی» نامید.
- **محدودیت:** Build Docker، اجرای CUDA، دانلود وزن‌ها، Salad و R2 واقعی
  همچنان در این محیط اجرا نشده‌اند.
