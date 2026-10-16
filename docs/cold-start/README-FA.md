# بسته اصلاح Cold Start و Image Caching برای ComfyUI Controller

مبنای بررسی: شاخه `main` مخزن `ImanNasrEsfahani/comfyui-controller` در ۱۶ اکتبر ۲۰۲۶.

## چه چیزی واقعاً اصلاح شده؟

1. در هر دو مسیر ساخت گروه جدید Salad (`backend/app/salad_control.py`، Direct و Legacy) فیلد رسمی `container.image_caching` با تنظیم `SALAD_IMAGE_CACHING=true` اضافه می‌شود.
2. مسیر استقرار قدیمی `salad-worker/deploy_salad.py` Cache را هم در ساخت اولیه و هم در بررسی اختلاف تنظیمات و اصلاح گروه *خاموش* لحاظ می‌کند؛ `--apply` مانند قبل صریح است.
3. در وضعیت عمومی و پالایش‌شده Backend (`salad_control` و `instance_contract`)، مقدار مشاهده‌شده Image Caching درج می‌شود، **بدون نمایش کلیدهای خصوصی Salad**.
4. اگر کاربر عمداً از طریق Deploy یک Draft تغییر‌یافته را برای گروه خاموش اعمال کند، مقدار Cache نیز با سیاست فعلی تطبیق داده می‌شود.
5. فایل کامل `salad-worker/start.sh` به صورت جایگزین ارائه شده که زمان شروع کانتینر، بازسازی مدل‌های Qwen، آماده‌شدن `comfyui-api`، بررسی Runtime و شروع Worker را در لاگ با قالب `[coldstart]` ثبت می‌کند؛ اجرای مدل و صحت SHA256 تغییر نکرده است.
6. ابزار `scripts/salad_cold_start_audit.py` وضعیت Cache، پیشرفت واقعی Pull (فقط با واحد مشخص)، تعداد Replica و تفکیک زمان‌های Worker را گزارش می‌دهد؛ در حالت پیش‌فرض **فقط خواندنی** است.
7. ابزار Audit فقط پس از اجرای صریح `--apply --confirm-idle-cache-update` و تأیید **صفر Replica، صفر Instance، نبود عملیات Pending و نبود Keep Warm** می‌تواند برای گروه موجود `image_caching=true` درخواست کند. دریافت پاسخ HTTP به‌تنهایی موفقیت قطعی قلمداد نمی‌شود.

**محدودیت مهم:** این بسته حجم مدل ۲۴+ گیگابایتی را کاهش نمی‌دهد و نمی‌تواند زمان Pull در نودهای جدید Salad را تضمین کند. هیچ ادعایی درباره رفع قطعی انتظار یک‌ساعته بدون شواهد زنده وجود ندارد. مهاجرت FP8 به GGUF/Q4 نیازمند Workflow و Benchmark کیفیت جداگانه است و به‌صورت خودکار انجام نشده است.

## نصب روی کپی مخزن و سپس Commit کردن در GitHub

۱. ابتدا از مخزن فعلی خود یک نسخه پشتیبان یا Git branch داشته باشید و مطمئن شوید تغییرات شخصی Commit شده‌اند.

۲. فایل ZIP را روی ریشه مخزن پروژه Extract کنید. فایل `salad-worker/start.sh` مستقیماً جایگزین می‌شود. باقی فایل‌های جدید (`scripts/`، `tests/` و این راهنما) اضافه خواهند شد. چهار فایل فعلی دیگر **توسط Patch محافظت‌شده** اصلاح می‌شوند تا آخرین کد شما پاک نشود.

۳. از ریشه پروژه دستورات زیر را اجرا کنید:

```bash
python3 scripts/apply_salad_coldstart.py --repo . --check
python3 scripts/apply_salad_coldstart.py --repo .
python3 -m unittest discover -s tests -p 'test_salad_coldstart_patch.py' -v
bash -n salad-worker/start.sh
git diff --check
git status --short
```

اگر Patch با پیام `PATCH REFUSED` متوقف شد، **فایل‌ها را دستی حدسی اصلاح نکنید**؛ یعنی Anchorهای مخزن تغییر کرده‌اند و باید برای نسخه جدید تطبیق داده شود. Patch چهار فایل را ابتدا کامل اعتبارسنجی و سپس اصلاح می‌کند. بار دوم اجرای آن هیچ تغییر تکراری ایجاد نمی‌کند.

فایل‌های تغییر‌یافته پس از اجرای Patch عبارت‌اند از:

- `salad-worker/deploy_salad.py`
- `backend/app/salad_control.py`
- `backend/app/instance_contract.py`
- `.env.example`
- `salad-worker/start.sh` (جایگزین کامل داخل ZIP)

به‌علاوه فایل‌های جدید Scripts و Tests. هیچ تغییری خودکار در مخزن GitHub، Salad یا سرور اعمال نمی‌شود.

## استقرار روی سرور

پس از Commit و Push *توسط شما*:

```bash
cd /var/www/comfyui-controller
git pull --ff-only
python3 scripts/sync-env.py
# بررسی کنید که فایل خصوصی .env هنوز تمام رمزها را دارد:
grep '^SALAD_IMAGE_CACHING=' .env
# مقدار پیشنهادی: SALAD_IMAGE_CACHING=true

docker compose up -d --build --force-recreate backend
# فقط در صورتی که Scheduler با پروفایل direct فعال است:
docker compose --profile direct up -d --build --force-recreate scheduler
```

روی همین Instance در حال Pull، با نصب فایل‌های Backend فوراً Cache تغییر نمی‌کند. اگر Image در همین لحظه در حال دانلود است، **برای تست این اصلاحات آن را Stop/Recreate نکنید**.

### تأیید یا فعال‌سازی Cache گروه موجود پس از پایان تمام Jobها

ابتدا نام واقعی Container Group فعال را از Portal یا صفحه Settings برنامه بخوانید؛ نام قدیمی `.env` ممکن است با Active DB متفاوت باشد.

```bash
cd /var/www/comfyui-controller
set -a; source .env; set +a
python3 scripts/salad_cold_start_audit.py --group 'EXACT-ACTIVE-GROUP'
```

برای اعمال تنظیم Cache، **فقط بعد از مطمئن‌شدن از پایان همه Jobها و خالی‌بودن GPU**:

```bash
python3 scripts/salad_cold_start_audit.py \
  --group 'EXACT-ACTIVE-GROUP' \
  --apply --confirm-idle-cache-update
```

این ابزار در صورت وجود هر Instance گزارش‌شده یا Replica فعال، از PATCH خودداری می‌کند. این API نمی‌تواند مستقل از Backend ثابت کند که هیچ Job صف‌شده‌ای وجود ندارد؛ آن را پیش از اجرای اختیاری بررسی کنید. هرگونه تغییر configuration در Salad ممکن است نیازمند زمان تأیید باشد.

### فعال‌شدن لاگ دقیق Worker

اصلاح `salad-worker/start.sh` فقط **بعد از Build و Push دستی Docker Image جدید** و Deployment صریح آن Image در Salad وارد اجرا می‌شود. نسخه فعلی Image فقط با تعویض Backend خودبه‌خود تغییر نمی‌کند. Workflow رسمی پروژه `.github/workflows/build-salad-worker.yml` نیازمند اجرای دستی و تأیید ساخت است؛ Build خودش Deploy نمی‌کند.

برای تحلیل لاگ خروجی:

```bash
python3 scripts/salad_cold_start_audit.py \
  --group 'EXACT-ACTIVE-GROUP' \
  --worker-log /path/to/sanitized-worker.log
```

اگر از Portal دو فایل JSON عمومیِ بررسی‌شده دارید، ابزار را بدون API Key به صورت Offline هم اجرا کنید:

```bash
python3 scripts/salad_cold_start_audit.py \
  --group-json /path/to/group.json \
  --instances-json /path/to/instances.json \
  --worker-log /path/to/sanitized-worker.log
```

فایل JSON خام Salad می‌تواند شامل Secrets باشد؛ آن را به افراد دیگر یا مخزن عمومی نفرستید. خروجی Audit صرفاً فیلدهای عملیاتی غیرمحرمانه را نمایش می‌دهد.

## سنجه‌ها و تعریف‌ها

- **Salad Pull / allocation**: قبل از ورود به `start.sh` است؛ ابزار تنها اطلاعاتی را که API واقعاً برمی‌گرداند نمایش می‌دهد.
- **model_restore**: خواندن قطعات baked، الحاق و اعتبارسنجی SHA256 روی SSD محلی؛ نه دانلود شبکه.
- **api_ready**: بارگذاری سرویس `comfyui-api` و دانلودهای `before_start` در Manifest (در صورت انجام توسط wrapper)، تا دریافت `/ready`.
- **runtime_verified**: اعتبارسنجی CUDA، VAE، LoRA، Qwen و ReActor.
- **direct_worker_spawned**: شروع فرآیند دریافت Job؛ هنوز به معنی تأیید اتصال به Backend نیست.

## نتایج تست

- ۹ تست Unittest روی شبیه‌سازی مسیرهای اصلی: **PASS**.
- Syntax Python برای اسکریپت‌ها: **PASS**.
- `bash -n` روی `salad-worker/start.sh`: **PASS**.
- مقایسه Source Anchorهای Patch با کد `main` خوانده‌شده از GitHub انجام شده؛ **تست کامل روی checkout واقعی در این محیط انجام نشده** (دسترسی GitHub فقط از طریق Connector قابل خواندن بود؛ Git clone در محیط تست امکان‌پذیر نبود).
- Build Docker چندده‌گیگابایتی، اجرای GPU واقعی Salad، تأیید Pull، و تست End-to-End: **انجام نشده**.

## منابع فنی

- SaladCloud Go SDK — `ContainerConfiguration.ImageCaching`: <https://github.com/SaladTechnologies/salad-cloud-sdk-go/blob/main/documentation/models/container_configuration.md>
- نمونه رسمی Salad ComfyUI با `imageCaching=true`: <https://github.com/SaladTechnologies/salad-recipes/blob/master/recipes/comfyui/container-group.json>
- مخزن ComfyUI API تیم Salad: <https://github.com/SaladTechnologies/comfyui-api>
