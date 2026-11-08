#!/usr/bin/env python3
"""Fail-closed, idempotent source overlay. NO remote writes, GPU, or secrets.

All upstream anchors are checked before ANY file is modified. This prevents a
partially-integrated checkout when a future upstream version changes a path.
"""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]

PATCHES = (
    ('backend/app/integrated_main.py',
     'from .video_api import router as video_v13_router',
     'from .video_api import router as video_v13_router\nfrom .character_replace_api import router as character_replace_router',
     'from .character_replace_api import router as character_replace_router'),
    ('backend/app/integrated_main.py',
     '    video_v13_router,\n)',
     '    video_v13_router,\n    character_replace_router,\n)',
     '    character_replace_router,\n)'),
    ('backend/app/integrated_main.py',
     "        ('/api/v2/video/models', 'GET'),",
     "        ('/api/v2/video/models', 'GET'),\n        ('/api/v2/character-replace/config', 'GET'),",
     "('/api/v2/character-replace/config', 'GET')"),
    ('frontend/src/auth/routeUtils.js',
     "'/create/video', '/edit/video', '/jobs'",
     "'/create/video', '/edit/video', '/edit/video/character', '/jobs'",
     "'/edit/video/character'"),
    ('frontend/src/app/router.jsx',
     "import {VideoCreatePage,VideoEditPage} from '../pages/video/VideoPages.jsx';",
     "import {VideoCreatePage,VideoEditPage} from '../pages/video/VideoPages.jsx';\nimport {CharacterReplacementPage} from '../pages/video/CharacterReplacementPage.jsx';",
     "import {CharacterReplacementPage} from '../pages/video/CharacterReplacementPage.jsx';"),
    ('frontend/src/app/router.jsx',
     "   else if(route.path==='/edit/video'){title='ویرایش ویدئو';node=<VideoEditPage/>;}",
     "   else if(route.path==='/edit/video/character'){title='جایگزینی کاراکتر';node=<CharacterReplacementPage/>;}\n   else if(route.path==='/edit/video'){title='ویرایش ویدئو';node=<VideoEditPage/>;}",
     "route.path==='/edit/video/character'"),
    ('frontend/src/pages/video/VideoPages.jsx',
     '<AppLink to="/library">مشاهده و دانلود اصل ویدئوهای خودم</AppLink></section>}',
     '<AppLink to="/edit/video/character">ابزار جدید: جایگزینی شخصیت در ویدئو (SCAIL-2)</AppLink> · <AppLink to="/library">مشاهده و دانلود اصل ویدئوهای خودم</AppLink></section>}',
     'ابزار جدید: جایگزینی شخصیت در ویدئو'),
    ('frontend/src/layouts/Layouts.jsx',
     "['/edit/video','ویرایش ویدئو'],",
     "['/edit/video','ویرایش ویدئو'],['/edit/video/character','جایگزینی کاراکتر'],",
     "['/edit/video/character','جایگزینی کاراکتر']"),
    ('backend/Dockerfile',
     'RUN pip install --no-cache-dir -r requirements.txt',
     'RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*\nRUN pip install --no-cache-dir -r requirements.txt',
     'apt-get install -y --no-install-recommends ffmpeg'),
)


def prepare(root=ROOT):
    """Validate all anchors first, return changed contents without touching disk."""
    changes = {}
    original = {}
    for rel, old, new, marker in PATCHES:
        path = root / rel
        if path not in changes:
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f'Missing or unsafe {rel}: apply to a full clean checkout')
            original[path] = path.read_text(encoding='utf-8')
            changes[path] = original[path]
        content = changes[path]
        if marker in content:
            continue
        if content.count(old) != 1:
            raise RuntimeError(f'Upstream mismatch in {rel} (expected exactly one anchor). NO files changed')
        changes[path] = content.replace(old, new, 1)
    return {p: new for p, new in changes.items() if original[p] != new}


def main(root=ROOT):
    pending = prepare(root)
    for file, content in pending.items():
        temp = file.with_suffix(file.suffix + '.scail2.tmp')
        try:
            temp.write_text(content, encoding='utf-8')
            os.chmod(temp, file.stat().st_mode)
            os.replace(temp, file)
        finally:
            temp.unlink(missing_ok=True)
        print('Patched:', file.relative_to(root))
    if not pending:
        print('Overlay already applied; no changes needed.')
    print('Review git diff and run tests before committing.')


if __name__ == '__main__':
    try:main()
    except Exception as exc:sys.exit('No unsafe partial patch: '+str(exc))
