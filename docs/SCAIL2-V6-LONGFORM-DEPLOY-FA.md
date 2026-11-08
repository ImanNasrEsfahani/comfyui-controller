# SCAIL-2 long-form upload / windowed rendering — v6 BETA

**مخزن GitHub اصلی فقط خوانده شد؛ هیچ Push یا Deploy مستقیم انجام نشده است.** این ZIP یک Patch افزایشی روی نسخه فعلی v5 + v4 SCAIL-2 است، نه جایگزین کل پروژه.

## چه چیزی عوض شد؟

- آپلود ویدئو از مرورگر مستقیم به R2 با S3 Multipart؛ بدون ارسال بدنه بزرگ از Nginx / FastAPI.
- قبول فایل ورودی با پسوندهای رایج MOV, MKV, AVI, MP4, WebM, WMV, FLV, MXF, MPEG, MTS, 3GP و فایل‌های نامشخص `.bin`. پسوند اثبات معتبر بودن فایل نیست؛ FFmpeg در Worker دیکود می‌کند. برخی کدک‌ها/فایل‌های DRM یا خراب پذیرفته نمی‌شوند.
- حذف سقف زمانی ثابت برای **مسیر multipart جدید**. Backend قدیمی `/assets/video` همچنان محدودیت کوتاه دارد و به‌عنوان مسیر legacy باقی مانده است.
- حداقل 16 MiB برای Part و نهایت 10,000 Part مطابق Cloudflare R2.
- سقف پیش‌فرض عملی هر فایل **20 GiB** از طریق `CHARACTER_REPLACE_MAX_VIDEO_GIB` قابل تغییر است. این عدد به دلیل فضای 100GB Salad و فایل‌های مدل سنگین است؛ ادعای حجم واقعاً بی‌نهایت نداریم.
- Worker برای ویدئوی بلند هر بار فقط پنجره 81 فریمی می‌سازد و با 5 فریم overlap ادامه می‌دهد؛ به FFmpeg اجازه می‌دهد خروجی یکپارچه MP4 با صدای اصلی بسازد.
- آپلود خروجی به R2 به‌صورت streaming؛ امضای URL خروجی درست قبل از انتقال مجدداً دریافت می‌شود.

### ⚠️ محدودیت کیفیت که هنوز باقی است

این نسخه **BETA** است: پنجره‌ها در ComfyUI به‌صورت **Prompt مستقل** اجرا می‌شوند و پنج فریم ورودی هم‌پوشانی دارند، اما هنوز 5 **فریم تولیدشده قبلی** به مدل بعدی منتقل نمی‌شوند. پس احتمال پرش هویت/نور/ظاهر در مرزهای 4.75 ثانیه‌ای وجود دارد. این بسته رفع *محدودیت آپلود، مدت ثابت، و مصرف حافظه یک Batch بزرگ* است، نه ضمانت یکدست بودن ویدئوی چندساعته. برای Quality واقعی long-form از native previous_frames / Infinity / GAP با تست عملی روی GPU و قابلیت checkpoint استفاده شود. استقرار با ترافیک واقعی بدون این تست توصیه نمی‌شود.

**Resume بعد از قطع یا Restart Worker هنوز کامل نیست.** Job شکست‌خورده باید دوباره از ابتدا اجرا شود. مدل 14B FP16 روی RTX5090 32GB و RAM24GB ممکن است به CPU offload نیاز داشته باشد و با کمبود حافظه مواجه شود.

## نصب (فقط پس از تهیه بکاپ)

۱. در Checkout محلی یا محیط توسعه، فایل ZIP را روی همان مسیرهای نسبی استخراج کن؛ `git diff` را بازبینی و تست‌ها را اجرا کن. فایل‌های قدیمی حذف نمی‌شوند. این ZIP افزایشی است؛ اسکریپت v4 `apply_scail2_overlay.py` را مجدداً اجرا نکن اگر نسخه v5 از قبل اعمال شده است.

۲. روی Backend، همان تنظیمات قبلی محفوظ بمانند و در صورت نیاز اضافه کن:

```env
CHARACTER_REPLACE_ENABLED=true
CHARACTER_REPLACE_MAX_VIDEO_GIB=20
# CHARACTER_REPLACE_WORKER_TOKEN=secret already set in private .env
```

۳. دیتابیس را **پس از گرفتن بکاپ و در بازه بدون Job فعال** به‌روزرسانی کن. اسکریپت migration افزایشی و idempotent است و خودش backup با timestamp می‌سازد:

```bash
cd /var/www/comfyui-controller
docker compose build backend
docker compose run --rm --no-deps backend python -m app.migrate_scail2
docker compose up -d --no-deps --force-recreate backend
```

قبل از اجرای migration، از مسیر واقعی `DB_PATH` داخل کانتینر و صحت Volume اطمینان پیدا کن.

۴. **Cloudflare R2 > bucket `comfy` > Settings > CORS policy**: فایل `docs/scail2-r2-cors.example.json` را با توجه به Origin واقعی وارد کن. وجود `ExposeHeaders: ["ETag"]` ضروری است. هیچ Credentials یا آدرس عمومی Bucket را در مرورگر قرار نده. Presigned URLها از سمت Backend تولید می‌شوند.

۵. روی GitHub Actions Workflow `Build SCAIL-2 Worker (GHCR)` پروفایل `thin` را Build/Push کن. Image جدید همچنان تگ `:thin` دارد؛ Digest / Build را بررسی کن.

۶. در Salad کانتینر گروه `scail2-video-5090` را **برای ارتقای Image** ویرایش و نسخه جدید را Deploy کن. تگ ثابت `thin` لزوماً تغییر نسخه را تضمین نمی‌کند؛ برای استقرار دقیق از digest جدید استفاده کن. هنگام استقرار `thin` ممکن است وزن‌های مدل دوباره دانلود شوند. پیش از تغییر، لاگ/وضعیت فعلی دانلود را بررسی کن تا هزینه بیهوده ایجاد نشود.

۷. ابتدا MP4 یا MOV 8–12ثانیه‌ای تست کن؛ سپس MKV/AVI و ۳۰ تا ۶۰ ثانیه. تا قبل از E2E روی Salad برای ویدئوهای چنددقیقه‌ای Job باکیفیت بالا ارسال نکن.

### تست محلی

```bash
python -m unittest discover -s tests -p 'test_scail2*.py' -v
node tests/check_scail2_video_edit_ui.cjs
```

تست‌های محلی: API + SQLite + R2 شبیه‌سازی‌شده، مسیر FFmpeg واقعی روی MOV/MPEG4 و پنجره‌ها، Worker Mocked، JSX syntax. **مدل FP16/SAM3 واقعی و Salad GPU اینجا تست نشده‌اند.**

## محدودیت‌های واقعی دیگر

- FFmpeg هر فایل یا کدک رمزگذاری‌شده را پشتیبانی نمی‌کند. برای فایل خراب/DRM باید خطای واضح بدهیم.
- R2 حداکثر حدود 5TiB برای یک Object با Multipart دارد؛ حد واقعی این Container Group پایین‌تر و با disk محدود است.
- FFmpeg طول ویدئو را دقیقاً از container می‌خواند؛ فایل‌های Live Stream یا بدون Duration ثابت در این نسخه پشتیبانی نمی‌شوند.
- فایل‌های طولانی می‌توانند صدها یا هزاران پردازش مدل، هزینه زیاد، خطای فضای دیسک و ناپیوستگی بصری ایجاد کنند. سرور باید quotas/rate limits و برآورد هزینه پیش از اجرا داشته باشد.
- `max_source_gib` تنظیم ظرفیت است؛ «نامحدود» فنی یا اقتصادی وجود ندارد.
- مدل نمی‌تواند تصویر هر انسان دلخواه را با حفظ کامل محیط، نور، هویت و حرکت بی‌خطا تضمین کند.

## معماری مطلوب Production بعدی

`Browser -> presigned R2 multipart -> CPU preflight FFmpeg/ffprobe -> scene detection -> timestamped 81/5 windows -> GPU queue with generated-frame anchors -> per-window R2 checkpoints -> retry by window -> stitch/colour match -> audio mux -> private Library`.

اجرای checkpoint، worker-resume، Generated-Frame conditioning و قیمت‌گذاری هر دقیقه بخش‌های جداگانه‌ای هستند که در این ZIP **کامل نشده‌اند**.
