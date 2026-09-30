# -*- coding: utf-8 -*-
import io
import json
import os
import re
import struct
import sys
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from PIL import Image, ImageDraw

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_PATH = ADDON.getAddonInfo('path')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
SETTINGS_FILE = os.path.join(PROFILE, 'viewer_settings.json')
LISTING_CACHE_FILE = os.path.join(PROFILE, 'last_picture_listing.json')
TEMP_DIR = xbmcvfs.translatePath('special://temp/')
SHADOW_TEXTURE = os.path.join(ADDON_PATH, 'resources', 'skins', 'Default', 'media', 'shadow.png')
DEFAULT_BACKGROUND_IMAGE = os.path.join(ADDON_PATH, 'resources', 'media', 'defaultBackground-0.1.55.jpg')

# 0.1.43: Play/Pause/Stop are deliberately NOT owned by the picture viewer.
# Slideshow control is Up/Down only, so Kodi's media keys remain available for
# normal audio playback. Older 0.1.28-0.1.42 releases installed two JJS keymaps;
# remove those once on upgrade so no stale mapping can keep intercepting keys.
LEGACY_MEDIA_KEYMAP_FILES = (
    'zz_jjs_pictureviewer.xml',
    'zzz_jjs_pictureviewer_active.xml',
    # 0.1.46 briefly installed a Pictures-window Select override while testing
    # direct use of Kodi's native picture browser. That approach was reverted,
    # but the profile keymap survives add-on updates unless we remove it here.
    'zz_jjs_pictureviewer_select.xml',
)


def _keymap_path(filename):
    return 'special://profile/keymaps/' + filename


def _delete_keymap(filename):
    path = _keymap_path(filename)
    if not xbmcvfs.exists(path):
        return False
    try:
        return bool(xbmcvfs.delete(path))
    except Exception:
        return False


def _cleanup_legacy_media_keymaps():
    changed = False
    for filename in LEGACY_MEDIA_KEYMAP_FILES:
        try:
            if _delete_keymap(filename):
                changed = True
                _log('Legacy media keymap removed: %s' % filename)
        except Exception as exc:
            _log('Legacy media keymap could not be removed %s: %r' %
                 (filename, exc), xbmc.LOGWARNING)
    if changed:
        xbmc.executebuiltin('ReloadKeymaps')

IMAGE_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tif', '.tiff'
}


class _RenderCancelled(Exception):
    pass


# Session-local cache of already decoded, EXIF-corrected source images at
# at most screen resolution. This keeps visual setting changes (border/shadow/
# gallery size) from re-reading and re-decoding the original NAS image.
_BASE_IMAGE_CACHE = OrderedDict()
_BASE_IMAGE_CACHE_LOCK = threading.RLock()
_BASE_IMAGE_CACHE_LIMIT = 4

# A single broken/blocked source image must never hold forward navigation forever.
# Prefetch is deliberately abandoned after this deadline; the image is marked
# bad for the current viewer session and navigation continues with the next one.
PREFETCH_TIMEOUT_SECONDS = 12.0


def _base_cache_get(path):
    with _BASE_IMAGE_CACHE_LOCK:
        image = _BASE_IMAGE_CACHE.pop(path, None)
        if image is None:
            return None
        _BASE_IMAGE_CACHE[path] = image
        try:
            return image.copy()
        except Exception:
            return None


def _base_cache_put(path, image):
    with _BASE_IMAGE_CACHE_LOCK:
        old = _BASE_IMAGE_CACHE.pop(path, None)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        try:
            _BASE_IMAGE_CACHE[path] = image.copy()
        except Exception:
            return
        while len(_BASE_IMAGE_CACHE) > _BASE_IMAGE_CACHE_LIMIT:
            _key, victim = _BASE_IMAGE_CACHE.popitem(last=False)
            try:
                victim.close()
            except Exception:
                pass


def _clear_base_cache():
    with _BASE_IMAGE_CACHE_LOCK:
        while _BASE_IMAGE_CACHE:
            _key, image = _BASE_IMAGE_CACHE.popitem(last=False)
            try:
                image.close()
            except Exception:
                pass


def _safe_remove(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# Kodi action ids used by the Shield remote / keyboard.
ACTION_LEFT = 1
ACTION_RIGHT = 2
ACTION_UP = 3
ACTION_DOWN = 4
ACTION_SELECT_ITEM = 7
ACTION_PARENT_DIR = 9
ACTION_PREVIOUS_MENU = 10
ACTION_SHOW_INFO = 11
ACTION_NAV_BACK = 92
ACTION_CONTEXT_MENU = 117
# Internal GUI-thread handoff used by the slideshow timer. The timer must never
# call WindowXML properties synchronously from its worker thread.
ACTION_JJS_SETTLE = 61     # Number3 / REMOTE_3
ACTION_NEXT_PICTURE = 28

# Kodi's native slideshow window id.
WINDOW_PICTURES = 10002
WINDOW_SLIDESHOW = 12007
PICTURE_VIEW_IDS = (50, 51, 550, 551, 500, 514, 510)

# XML controls in resources/skins/Default/1080i/PictureViewer.xml
CTRL_BG_BLACK = 1001
CTRL_BG_IMAGE = 1002
CTRL_SHADOW = 1003
CTRL_FRAME = 1004
CTRL_PHOTO_A = 1005
CTRL_STATUS = 1006
CTRL_PHOTO_B = 1007
CTRL_PROJECTOR_GHOST_A = 1008
CTRL_PROJECTOR_GHOST_B = 1009
CTRL_DUMMY_FOCUS = 9900

BTN_MODE = 9101
BTN_GALLERY_SIZE = 9102
BTN_BACKGROUND = 9103
BTN_CUSTOM_BACKGROUND = 9104
BTN_BORDER = 9105
BTN_BORDER_WIDTH = 9106
BTN_SHADOW = 9107
BTN_SHADOW_WIDTH = 9108
BTN_SHADOW_OFFSET = 9109
BTN_SHADOW_OPACITY = 9110
BTN_SLIDESHOW = 9112
BTN_SLIDESHOW_INTERVAL = 9113
BTN_PRELOAD_NEXT = 9114
BTN_TRANSITION = 9115
BTN_TRANSITION_DURATION = 9116

CANVAS_W = 1920
CANVAS_H = 1080

DEFAULTS = {
    'settings_version': 13,
    'display_mode': 'gallery',
    'gallery_percent': 85,
    'background_mode': 'viewer_default',
    'custom_background': DEFAULT_BACKGROUND_IMAGE,
    'white_border': True,
    'border_width': 10,
    'shadow': True,
    'shadow_width': 26,
    'shadow_offset': 30,
    'shadow_opacity': 60,
    'slideshow_interval': 5,
    'preload_next': True,
    'transition_mode': 'projector',
    'transition_duration_ms': 700,
}


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, msg), level)


def _ensure_profile():
    if not xbmcvfs.exists(PROFILE):
        xbmcvfs.mkdirs(PROFILE)


def load_settings():
    data = dict(DEFAULTS)
    stored = {}
    try:
        if xbmcvfs.exists(SETTINGS_FILE):
            f = xbmcvfs.File(SETTINGS_FILE)
            raw = f.read()
            f.close()
            stored = json.loads(raw) if raw else {}
            if isinstance(stored, dict):
                data.update(stored)
    except Exception as exc:
        _log('Settings could not be read: %r' % (exc,), xbmc.LOGWARNING)

    # One-time migration from 0.1.0-0.1.2: their Python WindowDialog used a
    # coordinate model that was wrong on the Shield and the 92 % default was
    # almost fullscreen. Keep all user choices, but migrate the old gallery size.
    try:
        old_version = int(stored.get('settings_version', 0)) if isinstance(stored, dict) else 0
    except Exception:
        old_version = 0

    # A fresh install has no persisted settings. Return the current defaults
    # directly; historical migrations apply only to real settings from older
    # add-on versions.
    if not stored:
        return data

    if old_version < 3:
        if not stored or int(stored.get('gallery_percent', 92)) == 92:
            data['gallery_percent'] = 82

    # 0.1.4's default shadow was too weak on a TV. Only migrate the exact
    # old defaults; deliberate user choices are preserved.
    if old_version < 5:
        try:
            if (int(stored.get('shadow_width', 28)) == 28 and
                    int(stored.get('shadow_offset', 12)) == 12 and
                    int(stored.get('shadow_opacity', 58)) == 58):
                data['shadow_width'] = 70
                data['shadow_offset'] = 22
                data['shadow_opacity'] = 90
        except Exception:
            pass
        data['settings_version'] = 5

    # 0.1.9: one-image look-ahead and slideshow settings. Existing users get
    # conservative defaults; no other settings are changed.
    if old_version < 6:
        if 'slideshow_interval' not in stored:
            data['slideshow_interval'] = 5
        if 'preload_next' not in stored:
            data['preload_next'] = True
        data['settings_version'] = 6
        save_settings(data)
    if int(data.get('settings_version', 0) or 0) < 7:
        data['settings_version'] = 7
        save_settings(data)

    # 0.1.16: stable two-layer transitions. Existing installations default to
    # a conservative crossfade; no rendering/prefetch setting is changed.
    if int(data.get('settings_version', 0) or 0) < 8:
        if 'transition_mode' not in stored:
            data['transition_mode'] = 'fade'
        data['settings_version'] = 8
        save_settings(data)

    # 0.1.17: one compound VisibleChange animation and an explicit duration.
    if int(data.get('settings_version', 0) or 0) < 9:
        if 'transition_duration_ms' not in stored:
            data['transition_duration_ms'] = 350
        data['settings_version'] = 9
        save_settings(data)

    # 0.1.31 changes only the defaults for fresh installations. Existing
    # installations keep every stored visual/slideshow preference unchanged.
    if int(data.get('settings_version', 0) or 0) < 10:
        data['settings_version'] = 10
        save_settings(data)

    # 0.1.35: Hoch/Runter are slideshow controls again.  The historical
    # jump-size setting is obsolete; remove only that key and preserve every
    # other user setting unchanged.
    if int(data.get('settings_version', 0) or 0) < 11:
        data.pop('jump_size', None)
        data['settings_version'] = 11
        save_settings(data)
    else:
        data.pop('jump_size', None)

    # 0.1.37: the bundled PictureViewer wallpaper is now a first-class
    # background choice. Migrate only the exact former default path; a user
    # selected custom image remains custom and is never overwritten.
    if int(data.get('settings_version', 0) or 0) < 12:
        if (data.get('background_mode') == 'custom' and
                str(data.get('custom_background', '') or '') == DEFAULT_BACKGROUND_IMAGE):
            data['background_mode'] = 'viewer_default'
        data['settings_version'] = 12
        save_settings(data)
    # 0.1.50: new public-release defaults. Migrate only the exact previous
    # shadow defaults so deliberate user choices remain untouched.
    if int(data.get('settings_version', 0) or 0) < 13:
        try:
            if (int(stored.get('shadow_width', 24)) == 24 and
                    int(stored.get('shadow_offset', 30)) == 30 and
                    int(stored.get('shadow_opacity', 90)) == 90):
                data['shadow_width'] = 26
                data['shadow_offset'] = 30
                data['shadow_opacity'] = 60
        except Exception:
            pass
        data['settings_version'] = 13
        save_settings(data)
    return data


def save_settings(settings):
    _ensure_profile()
    try:
        # jump_size belonged to the old Hoch/Runter navigation model and must
        # never be written again from 0.1.35 onward.
        settings.pop('jump_size', None)
        settings['settings_version'] = 13
        f = xbmcvfs.File(SETTINGS_FILE, 'w')
        f.write(json.dumps(settings, ensure_ascii=False, indent=2))
        f.close()
    except Exception as exc:
        _log('Settings could not be saved: %r' % (exc,), xbmc.LOGERROR)


def _save_listing_cache(folder, image_names):
    """Persist the exact sorted image list Kodi's Pictures plugin just displayed.

    Opening an image normally happens immediately after this directory listing.
    Reusing it avoids a second expensive xbmcvfs.listdir() over large SMB/NFS
    folders before the first picture can be shown.
    """
    _ensure_profile()
    try:
        payload = {
            'folder': folder,
            'saved_at': time.time(),
            'images': list(image_names),
        }
        f = xbmcvfs.File(LISTING_CACHE_FILE, 'w')
        f.write(json.dumps(payload, ensure_ascii=False))
        f.close()
    except Exception as exc:
        _log('Picture-list cache could not be written: %r' % (exc,), xbmc.LOGWARNING)


def _load_listing_cache(folder, selected_image='', max_age=1800):
    """Return [(name,path), ...] from the most recent Pictures listing if valid."""
    try:
        if not xbmcvfs.exists(LISTING_CACHE_FILE):
            return []
        f = xbmcvfs.File(LISTING_CACHE_FILE)
        raw = f.read()
        f.close()
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            return []
        cached_folder = str(payload.get('folder') or '')
        if cached_folder.rstrip('/\\').casefold() != str(folder or '').rstrip('/\\').casefold():
            return []
        try:
            age = max(0.0, time.time() - float(payload.get('saved_at') or 0))
        except Exception:
            return []
        if age > float(max_age):
            return []
        names = payload.get('images') or []
        if not isinstance(names, list) or not names:
            return []
        result = []
        for name in names:
            if not isinstance(name, str):
                continue
            if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            result.append((name, join_vfs(folder, name)))
        if not result:
            return []
        if selected_image and _find_start_index(result, selected_image) == 0:
            # Index 0 is ambiguous: it may be the real first picture or a miss.
            req = str(selected_image).rstrip('/\\').casefold()
            if not any(path.rstrip('/\\').casefold() == req for _name, path in result):
                return []
        return result
    except Exception as exc:
        _log('Picture-list cache could not be read: %r' % (exc,), xbmc.LOGWARNING)
        return []


def natural_key(value):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r'(\d+)', value)]


def join_vfs(folder, name):
    if not folder:
        return name
    if folder.endswith('/') or folder.endswith('\\'):
        return folder + name
    sep = '/' if '://' in folder or '/' in folder else '\\'
    return folder + sep + name


def parent_path(path):
    value = (path or '').rstrip('/\\')
    slash = max(value.rfind('/'), value.rfind('\\'))
    return value[:slash + 1] if slash >= 0 else ''


def list_images(folder):
    try:
        _dirs, files = xbmcvfs.listdir(folder)
    except Exception as exc:
        _log('Folder could not be read %s: %r' % (folder, exc), xbmc.LOGERROR)
        return []
    result = []
    for name in files:
        ext = os.path.splitext(name)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            result.append((name, join_vfs(folder, name)))
    result.sort(key=lambda item: natural_key(item[0]))
    return result


def _read_prefix(path, size=1048576):
    try:
        f = xbmcvfs.File(path)
        raw = f.readBytes(size)
        f.close()
        return bytes(raw)
    except Exception:
        return b''


def _jpeg_exif_orientation(segment):
    """Return JPEG EXIF orientation (1..8) from one APP1 segment."""
    try:
        if not segment.startswith(b'Exif\x00\x00'):
            return 1
        tiff = segment[6:]
        if len(tiff) < 8:
            return 1
        endian = tiff[:2]
        if endian == b'II':
            order = '<'
        elif endian == b'MM':
            order = '>'
        else:
            return 1
        if struct.unpack(order + 'H', tiff[2:4])[0] != 42:
            return 1
        ifd0 = struct.unpack(order + 'I', tiff[4:8])[0]
        if ifd0 < 0 or ifd0 + 2 > len(tiff):
            return 1
        count = struct.unpack(order + 'H', tiff[ifd0:ifd0 + 2])[0]
        pos = ifd0 + 2
        for _ in range(count):
            if pos + 12 > len(tiff):
                break
            tag, typ, num = struct.unpack(order + 'HHI', tiff[pos:pos + 8])
            if tag == 0x0112 and typ == 3 and num >= 1:
                value = struct.unpack(order + 'H', tiff[pos + 8:pos + 10])[0]
                return value if 1 <= value <= 8 else 1
            pos += 12
    except Exception:
        pass
    return 1


def _jpeg_size(data):
    """JPEG dimensions with EXIF orientation applied, without decoding pixels."""
    pos = 2
    orientation = 1
    dimensions = None
    while pos + 4 <= len(data):
        if data[pos] != 0xff:
            pos += 1
            continue
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        if marker == 0xda:  # start of scan: metadata/size must already be known
            break
        if pos + 2 > len(data):
            break
        length = struct.unpack('>H', data[pos:pos + 2])[0]
        if length < 2 or pos + length > len(data):
            break
        payload = data[pos + 2:pos + length]
        if marker == 0xe1:
            orientation = _jpeg_exif_orientation(payload)
        elif marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
                        0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            if len(payload) >= 5:
                h, w = struct.unpack('>HH', payload[1:5])
                dimensions = (w, h)
        pos += length
    if not dimensions:
        return None
    w, h = dimensions
    # Orientations 5..8 rotate the displayed image by 90 degrees. Kodi applies
    # this automatically, so the frame geometry must use the displayed axes too.
    if orientation in (5, 6, 7, 8):
        w, h = h, w
    return w, h


def image_size(path):
    """Best-effort displayed dimensions from headers; never decodes the full image."""
    data = _read_prefix(path)
    if len(data) < 24:
        return None
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
            return struct.unpack('>II', data[16:24])
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return struct.unpack('<HH', data[6:10])
        if data.startswith(b'BM') and len(data) >= 26:
            w, h = struct.unpack('<ii', data[18:26])
            return abs(w), abs(h)
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
            chunk = data[12:16]
            if chunk == b'VP8X' and len(data) >= 30:
                w = 1 + int.from_bytes(data[24:27], 'little')
                h = 1 + int.from_bytes(data[27:30], 'little')
                return w, h
            if chunk == b'VP8L' and len(data) >= 25 and data[20] == 0x2f:
                bits = int.from_bytes(data[21:25], 'little')
                w = (bits & 0x3fff) + 1
                h = ((bits >> 14) & 0x3fff) + 1
                return w, h
            if chunk == b'VP8 ':
                pos = data.find(b'\x9d\x01\x2a', 20)
                if pos >= 0 and len(data) >= pos + 7:
                    w, h = struct.unpack('<HH', data[pos + 3:pos + 7])
                    return w & 0x3fff, h & 0x3fff
        if data[:2] == b'\xff\xd8':
            return _jpeg_size(data)
    except Exception:
        return None
    return None


def _pil_orientation_value(image):
    orientation = 1
    try:
        exif = image._getexif() if hasattr(image, '_getexif') else None
        if exif:
            orientation = int(exif.get(0x0112, 1) or 1)
    except Exception:
        orientation = 1
    return orientation if 1 <= orientation <= 8 else 1


def _pil_orientation(image, orientation=None):
    """Apply EXIF orientation using Pillow APIs available in Kodi's older PIL module."""
    if orientation is None:
        orientation = _pil_orientation_value(image)

    transpose = {
        2: getattr(Image, 'FLIP_LEFT_RIGHT', 0),
        3: getattr(Image, 'ROTATE_180', 3),
        4: getattr(Image, 'FLIP_TOP_BOTTOM', 1),
        5: getattr(Image, 'TRANSPOSE', 5),
        6: getattr(Image, 'ROTATE_270', 4),
        7: getattr(Image, 'TRANSVERSE', 6),
        8: getattr(Image, 'ROTATE_90', 2),
    }.get(orientation)
    if transpose is not None:
        try:
            image = image.transpose(transpose)
        except Exception:
            pass
    return image


def _open_pil_source(path, cancel_event=None):
    """Return (source, cleanup) for Pillow without leaving VFS staging files.

    Local files are opened directly. smb:// / nfs:// files are read in 1 MiB
    chunks into memory so an obsolete/closing prefetch can stop cooperatively
    between chunks instead of leaving a long-running xbmcvfs.copy() behind.
    """
    translated = xbmcvfs.translatePath(path)
    if translated and os.path.isfile(translated):
        return translated, None

    stream = io.BytesIO()
    f = None
    try:
        f = xbmcvfs.File(path)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise _RenderCancelled()
            chunk = f.readBytes(4 * 1024 * 1024)
            if not chunk:
                break
            stream.write(bytes(chunk))
        if cancel_event is not None and cancel_event.is_set():
            raise _RenderCancelled()
        stream.seek(0)
        return stream, stream.close
    except Exception:
        try:
            stream.close()
        except Exception:
            pass
        raise
    finally:
        if f is not None:
            try:
                f.close()
            except Exception:
                pass

def _nine_slice(source, width, height, border=70):
    """Render Kodi's shadow texture like <texture border=\"70\">."""
    width = max(1, int(width))
    height = max(1, int(height))
    src = source.convert('RGBA')
    sw, sh = src.size
    sbx = min(int(border), sw // 2)
    sby = min(int(border), sh // 2)
    dbx = min(sbx, width // 2)
    dby = min(sby, height // 2)
    out = Image.new('RGBA', (width, height), (0, 0, 0, 0))

    lanczos = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 1))

    def put(box, dest):
        x1, y1, x2, y2 = dest
        if x2 <= x1 or y2 <= y1:
            return
        tile = src.crop(box)
        size = (x2 - x1, y2 - y1)
        if tile.size != size:
            tile = tile.resize(size, lanczos)
        # Keep the tile's RGBA alpha exactly. Passing the tile again as a
        # mask would multiply its alpha and make the soft shadow nearly vanish.
        out.paste(tile, (x1, y1))

    # corners
    put((0, 0, sbx, sby), (0, 0, dbx, dby))
    put((sw - sbx, 0, sw, sby), (width - dbx, 0, width, dby))
    put((0, sh - sby, sbx, sh), (0, height - dby, dbx, height))
    put((sw - sbx, sh - sby, sw, sh), (width - dbx, height - dby, width, height))
    # edges and center
    put((sbx, 0, sw - sbx, sby), (dbx, 0, width - dbx, dby))
    put((sbx, sh - sby, sw - sbx, sh), (dbx, height - dby, width - dbx, height))
    put((0, sby, sbx, sh - sby), (0, dby, dbx, height - dby))
    put((sw - sbx, sby, sw, sh - sby), (width - dbx, dby, width, height - dby))
    put((sbx, sby, sw - sbx, sh - sby), (dbx, dby, width - dbx, height - dby))
    return out


def _shadow_with_opacity(width, height, opacity):
    with Image.open(SHADOW_TEXTURE) as src:
        shadow = _nine_slice(src, width, height, 70)

    # The source texture is deliberately soft. Scale its alpha well beyond the
    # source maximum so that even on a medium-bright background 100 % in the UI
    # produces a clearly black shadow while preserving width, offset and falloff.
    opacity = max(0, min(100, int(opacity)))
    strength = (opacity / 100.0) * 2.70
    alpha = shadow.getchannel('A').point(lambda a: min(255, int(a * strength)))
    shadow.putalpha(alpha)
    return shadow


def _prepare_base_picture(source_path, token, cancel_event=None):
    """Decode one source once per session, corrected and limited to screen size.

    The returned image contains only the picture itself (no border/shadow). It is
    cached in RAM at <= 1920x1080, so changing visual settings never has to read
    the original file from NAS/VFS again.
    """
    cached = _base_cache_get(source_path)
    if cached is not None:
        return cached

    pil_source = None
    cleanup_source = None
    try:
        pil_source, cleanup_source = _open_pil_source(source_path, cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            raise _RenderCancelled()
        with Image.open(pil_source) as opened:
            orientation = _pil_orientation_value(opened)
            raw_w, raw_h = opened.size
            disp_w, disp_h = (raw_h, raw_w) if orientation in (5, 6, 7, 8) else (raw_w, raw_h)
            base_w, base_h = fit_rect(disp_w, disp_h, CANVAS_W, CANVAS_H)

            if (getattr(opened, 'format', '') or '').upper() == 'JPEG':
                draft_size = (base_h, base_w) if orientation in (5, 6, 7, 8) else (base_w, base_h)
                try:
                    opened.draft('RGB', draft_size)
                except Exception:
                    pass

            opened.load()
            if cancel_event is not None and cancel_event.is_set():
                raise _RenderCancelled()
            picture = _pil_orientation(opened, orientation).convert('RGBA')

        lanczos = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 1))
        if picture.size != (base_w, base_h):
            picture = picture.resize((base_w, base_h), lanczos)
        if cancel_event is not None and cancel_event.is_set():
            try:
                picture.close()
            except Exception:
                pass
            raise _RenderCancelled()
        _base_cache_put(source_path, picture)
        return picture
    finally:
        if cleanup_source is not None:
            try:
                cleanup_source()
            except Exception:
                pass


def _render_overlay(source_path, settings, token, cancel_event=None):
    """Build one immutable atomic 1920x1080 viewer layer.

    The expensive source decode is cached separately. Render output paths are
    unique for their lifetime; a background prefetch can therefore never replace
    the bytes of an image Kodi is still loading asynchronously.
    """
    picture = _prepare_base_picture(source_path, token, cancel_event)
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise _RenderCancelled()
        s = settings
        if s['display_mode'] == 'fullscreen':
            border = 0
            max_w = CANVAS_W
            max_h = CANVAS_H
            shadow_width = 0
            shadow_offset = 0
        else:
            pct = max(50, min(98, int(s['gallery_percent']))) / 100.0
            outer_w = int(CANVAS_W * pct)
            outer_h = int(CANVAS_H * pct)
            border = max(0, int(s['border_width'])) if s['white_border'] else 0
            max_w = max(1, outer_w - 2 * border)
            max_h = max(1, outer_h - 2 * border)
            shadow_width = max(0, int(s['shadow_width'])) if s['shadow'] else 0
            shadow_offset = int(s['shadow_offset']) if s['shadow'] else 0

        img_w, img_h = fit_rect(picture.size[0], picture.size[1], max_w, max_h)
        lanczos = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 1))
        if picture.size != (img_w, img_h):
            display_picture = picture.resize((img_w, img_h), lanczos)
        else:
            display_picture = picture.copy()

        frame_w = img_w + 2 * border
        frame_h = img_h + 2 * border
        frame_x = (CANVAS_W - frame_w) // 2
        frame_y = (CANVAS_H - frame_h) // 2
        img_x = frame_x + border
        img_y = frame_y + border

        layer = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))

        if s['display_mode'] == 'gallery' and s['shadow'] and shadow_width > 0:
            sw = frame_w + 2 * shadow_width
            sh = frame_h + 2 * shadow_width
            shadow = _shadow_with_opacity(sw, sh, s['shadow_opacity'])
            try:
                sx = frame_x - shadow_width + shadow_offset
                sy = frame_y - shadow_width + shadow_offset
                layer.paste(shadow, (sx, sy))
            finally:
                try:
                    shadow.close()
                except Exception:
                    pass

        if border > 0:
            draw = ImageDraw.Draw(layer)
            draw.rectangle((frame_x, frame_y, frame_x + frame_w - 1, frame_y + frame_h - 1),
                           fill=(255, 255, 255, 255))

        layer.paste(display_picture, (img_x, img_y), display_picture)
        try:
            display_picture.close()
        except Exception:
            pass

        rendered = os.path.join(TEMP_DIR, 'jjs_pictureviewer_render_%s.png' % token)
        _safe_remove(rendered)
        if cancel_event is not None and cancel_event.is_set():
            raise _RenderCancelled()
        layer.save(rendered, 'PNG', compress_level=0)
        if cancel_event is not None and cancel_event.is_set():
            _safe_remove(rendered)
            raise _RenderCancelled()
        try:
            layer.close()
        except Exception:
            pass
        return rendered
    finally:
        try:
            picture.close()
        except Exception:
            pass

def fit_rect(iw, ih, max_w, max_h):
    """Contain: one axis reaches its limit, the other follows the aspect ratio."""
    if not iw or not ih or iw <= 0 or ih <= 0:
        return max(1, int(max_w)), max(1, int(max_h))
    scale = min(float(max_w) / float(iw), float(max_h) / float(ih))
    return max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))


def _existing_image(path):
    if not path:
        return ''
    try:
        return path if xbmcvfs.exists(path) else ''
    except Exception:
        return ''


def resolve_skin_wallpaper():
    """Resolve Confluence's actual current wallpaper before using generic fallbacks."""
    # Confluence Custom: custom background when enabled.
    for key in ('CustomBackgroundPath', 'MasterCustomBackgroundPath'):
        try:
            value = xbmc.getInfoLabel('Skin.String(%s)' % key).strip()
        except Exception:
            value = ''
        if value and _existing_image(value):
            return value

    # Confluence's CommonBackground uses Skin.CurrentTheme -> backgrounds/<theme>.jpg
    try:
        theme = xbmc.getInfoLabel('Skin.CurrentTheme').strip()
    except Exception:
        theme = ''
    if theme:
        themed = 'special://skin/backgrounds/%s.jpg' % theme
        if _existing_image(themed):
            return themed

    for path in (
        'special://skin/backgrounds/SKINDEFAULT.jpg',
        'special://skin/backgrounds/background.jpg',
        'special://skin/backgrounds/default.jpg',
        'special://skin/media/background.jpg',
        'special://skin/media/background.png',
    ):
        if _existing_image(path):
            return path
    return ''


def _find_start_index(images, requested_path):
    req = (requested_path or '').rstrip('/\\').casefold()
    if not req:
        return 0
    for idx, (_name, path) in enumerate(images):
        if path.rstrip('/\\').casefold() == req:
            return idx
    return 0


class PictureViewer(xbmcgui.WindowXMLDialog):
    """One-image-at-a-time viewer with immutable renders and one-picture look-ahead."""

    def configure(self, folder, images, index):
        self.folder = folder
        self.images = images
        self.index = max(0, min(index, len(images) - 1))
        self.settings = load_settings()
        self.dim_cache = {}
        self.menu_open = False
        self.ready = False

        self.current_slot = None
        self.previous_slot = None
        self.current_render_path = ''
        self.previous_render_path = ''
        self.render_serial = 0
        self.prefetch = None
        self.prefetch_inflight = None
        self.prefetch_thread = None
        self.prefetch_cancel_event = None
        self.prefetch_request = 0
        self.bad_image_indices = set()
        self.prefetch_disabled_session = False
        # Forward navigation must never wait synchronously for a background
        # VFS prefetch.  If Kodi/NAS I/O is briefly busy (notably around an
        # audio track change), remember one requested +1 step and dispatch it
        # after the prefetch worker has released the VFS path.
        self.pending_next_move = None
        self.render_generation = 0
        self.render_lock = threading.RLock()
        self.transition_lock = threading.Lock()
        self.rendering = False
        self.closing = False

        self.slideshow_active = False
        self.slideshow_paused = False
        self.last_change = time.monotonic()
        self.slideshow_thread = None
        self.stop_event = threading.Event()
        self.shutdown_done = False
        self.active_photo_layer = ''
        self.pending_projector_layer = ''
        self.transition_direction = 'next'
        self.transition_until = 0.0
        self.transition_serial = 0
        self.transition_settle_queued_serial = 0
        self.transition_settle_queued_at = 0.0
        self.play_indicator_until = 0.0

    def onInit(self):
        self.bg_black = self.getControl(CTRL_BG_BLACK)
        self.bg_image = self.getControl(CTRL_BG_IMAGE)
        self.shadow_img = self.getControl(CTRL_SHADOW)
        self.frame_img = self.getControl(CTRL_FRAME)
        self.photo_a = self.getControl(CTRL_PHOTO_A)
        self.photo_b = self.getControl(CTRL_PHOTO_B)
        self.projector_ghost_a = self.getControl(CTRL_PROJECTOR_GHOST_A)
        self.projector_ghost_b = self.getControl(CTRL_PROJECTOR_GHOST_B)
        self.status = self.getControl(CTRL_STATUS)
        self.clearProperty('JJSMenu')
        self.clearProperty('JJSPhotoLayer')
        self.clearProperty('JJSSlideshowIcon')
        self.setProperty('JJSProjectorActive', '0')
        self.setProperty('JJSTransitionMode', 'none')
        self.setProperty('JJSTransitionDir', 'next')
        self.setProperty('JJSTransitionMs', str(int(self.settings.get('transition_duration_ms', 350))))
        self.setFocusId(CTRL_DUMMY_FOCUS)
        self.ready = True
        self._refresh_menu_labels()
        if self._show_current(allow_prefetch=False, animate=False):
            self._kick_prefetch()
        else:
            # If the image selected in Kodi itself is broken, don't open the
            # viewer on an empty/background-only screen. Walk forward once
            # through the folder until a usable picture is found.
            start_index = self.index
            attempted = set()
            candidate = self._next_usable_index(start_index, 1)
            while candidate != start_index and candidate not in attempted:
                attempted.add(candidate)
                self.index = candidate
                if self._show_current(allow_prefetch=False, animate=False):
                    self._kick_prefetch()
                    break
                candidate = self._next_usable_index(candidate, 1)
            else:
                self.index = start_index
        self._start_slideshow_thread()

    def shutdown(self):
        if getattr(self, 'shutdown_done', False):
            return
        self.shutdown_done = True
        self.closing = True
        self.slideshow_active = False
        self.slideshow_paused = False
        self.play_indicator_until = 0.0
        try:
            self.clearProperty('JJSPhotoLayer')
            self.clearProperty('JJSProjectorActive')
            self.clearProperty('JJSTransitionMode')
            self.clearProperty('JJSTransitionDir')
            self.clearProperty('JJSTransitionMs')
            self.clearProperty('JJSSlideshowIcon')
        except Exception:
            pass
        try:
            self.stop_event.set()
        except Exception:
            pass

        with self.render_lock:
            self.pending_next_move = None
            self.prefetch_request += 1
            if self.prefetch_cancel_event is not None:
                self.prefetch_cancel_event.set()
            self._discard_prefetch_locked()
            prefetch_thread = self.prefetch_thread
        slideshow_thread = self.slideshow_thread

        current = threading.current_thread()
        # Cooperative VFS reads wake between 1 MiB chunks. Wait briefly so the
        # embedded Kodi Python interpreter is not left holding orphan workers.
        for thread, label in ((prefetch_thread, 'Prefetch'),
                              (slideshow_thread, 'Slideshow')):
            if thread and thread is not current and thread.is_alive():
                thread.join(3.0)
                if thread.is_alive():
                    _log('%s-Thread beendet sich nicht rechtzeitig' % label, xbmc.LOGWARNING)

    def _dimensions(self, path):
        if path not in self.dim_cache:
            self.dim_cache[path] = image_size(path)
        return self.dim_cache[path]

    def _apply_background(self):
        if self.settings['display_mode'] == 'fullscreen':
            self.bg_image.setImage('')
            return
        mode = self.settings.get('background_mode', 'viewer_default')
        if mode == 'black':
            self.bg_image.setImage('')
            return
        if mode == 'custom':
            path = self.settings.get('custom_background', '')
        elif mode == 'viewer_default':
            path = DEFAULT_BACKGROUND_IMAGE
        else:
            path = resolve_skin_wallpaper()
        # The bundled default can change between add-on versions while keeping the same
        # logical role. Never let Kodi's texture cache pin an older bundled wallpaper.
        # Custom/skin wallpapers keep normal caching; the bundled default is loaded fresh.
        use_cache = (mode != 'viewer_default')
        self.bg_image.setImage(path if path and _existing_image(path) else '', useCache=use_cache)

    def _layout_current(self):
        for photo in (self.photo_a, self.photo_b, self.projector_ghost_a, self.projector_ghost_b):
            photo.setPosition(0, 0)
            photo.setWidth(CANVAS_W)
            photo.setHeight(CANVAS_H)
        self.frame_img.setVisible(False)
        self.shadow_img.setVisible(False)

    def _transition_mode(self):
        mode = str(self.settings.get('transition_mode', 'fade') or 'fade')
        return mode if mode in ('none', 'fade', 'zoom', 'slide', 'projector') else 'fade'

    def _transition_duration_ms(self):
        allowed = (120, 180, 250, 350, 500, 700, 1000, 1500)
        try:
            value = int(self.settings.get('transition_duration_ms', 350))
        except Exception:
            value = 350
        return min(allowed, key=lambda item: abs(item - value))

    def _switch_photo_layer(self, rendered, animate=True, direction=1):
        """Display a finished render through the stable A/B pipeline.

        Fade/zoom/slide continue to flip the persistent A/B layers directly.
        Projector is deliberately different: A/B stay frozen while two temporary
        full-canvas overlays perform old-out/new-in.  Only after the animation
        deadline is the hidden persistent layer committed to the new picture.
        This prevents transient A/B/ghost overlap, especially when landscape and
        portrait images alternate.
        """
        target_layer = 'A' if self.active_photo_layer != 'A' else 'B'
        target = self.photo_a if target_layer == 'A' else self.photo_b
        mode = self._transition_mode() if animate and self.active_photo_layer else 'none'
        duration_ms = self._transition_duration_ms()

        # Preload the future persistent layer while it is still hidden.
        target.setImage(rendered, useCache=False)

        if mode == 'projector' and self.current_render_path:
            # 1008 is the outgoing overlay, 1009 the incoming overlay.  Keep the
            # outgoing control's *base* position off-screen in the direction it
            # leaves. Kodi Visible animations return to the control's base
            # position after they finish; an off-screen base prevents the old
            # landscape picture from snapping back behind a portrait while the
            # projector property is still true for a few cleanup milliseconds.
            outgoing_base_x = -CANVAS_W if direction >= 0 else CANVAS_W
            self.projector_ghost_a.setPosition(outgoing_base_x, 0)
            self.projector_ghost_b.setPosition(0, 0)
            self.projector_ghost_a.setImage(self.current_render_path, useCache=False)
            self.projector_ghost_b.setImage(rendered, useCache=False)

        with self.transition_lock:
            # Every visual switch gets an identity.  A delayed internal settle
            # action from an older transition must never terminate a newer one.
            self.transition_serial += 1
            self.transition_settle_queued_serial = 0
            self.transition_settle_queued_at = 0.0
            self.setProperty('JJSTransitionDir', 'next' if direction >= 0 else 'prev')
            self.setProperty('JJSTransitionMs', str(duration_ms))

            if mode == 'projector' and self.current_render_path:
                self.pending_projector_layer = target_layer
                self.setProperty('JJSTransitionMode', 'projector')
                # This single visibility change hides persistent A/B and reveals
                # both projector overlays simultaneously.
                self.setProperty('JJSProjectorActive', '1')
            else:
                self.pending_projector_layer = ''
                self.setProperty('JJSProjectorActive', '0')
                self.setProperty('JJSTransitionMode', mode)
                self.setProperty('JJSPhotoLayer', target_layer)
                self.active_photo_layer = target_layer

            self.transition_until = time.monotonic() + ((duration_ms + 45) / 1000.0 if mode != 'none' else 0.0)

    def _allocate_slot(self):
        # 0.1.10: tokens are monotonic and never reused during this viewer
        # session. Kodi may still be loading a texture after setImage() returns,
        # so reusing six filenames can display the wrong picture under races.
        with self.render_lock:
            self.render_serial += 1
            return '%d_%d' % (int(time.time() * 1000), self.render_serial)

    def _display_rendered(self, index, rendered, slot, animate=True, direction=1):
        name, _path = self.images[index]
        self._apply_background()
        self._layout_current()
        # 0.1.59 diagnostic: feed the original source image directly to Kodi's
        # normal A/B image-control pipeline. The Pillow/render step still runs so
        # only the texture source handed to setImage() changes.
        _source_name, source_path = self.images[index]
        self._switch_photo_layer(source_path, animate=animate, direction=direction)

        stale = self.previous_render_path
        self.previous_render_path = self.current_render_path
        self.current_render_path = rendered
        self.previous_slot = self.current_slot
        self.current_slot = slot
        # Once an image has survived one complete subsequent display it is safe
        # to delete its immutable temp file. Current + previous always remain.
        if stale and stale not in (self.current_render_path, self.previous_render_path):
            _safe_remove(stale)

        self.status.setLabel('%d / %d   %s' % (index + 1, len(self.images), name))
        # For slideshow timing, the selected interval starts after the XML
        # transition has completed, not while the new picture is still moving.
        self.last_change = max(time.monotonic(), self.transition_until)

    def _discard_prefetch_locked(self):
        if self.prefetch_cancel_event is not None:
            self.prefetch_cancel_event.set()
        old = self.prefetch
        self.prefetch = None
        if old and old.get('path'):
            _safe_remove(old.get('path'))

    def _take_prefetch(self, index):
        with self.render_lock:
            p = self.prefetch
            if (p and p.get('index') == index and
                    p.get('generation') == self.render_generation and
                    p.get('path') and os.path.exists(p['path'])):
                self.prefetch = None
                return p
        return None

    def _defer_forward_move_if_prefetch_busy(self, index, source):
        """Queue one +1 navigation without ever blocking the WindowXML thread.

        A matching look-ahead can be inside xbmcvfs.File.readBytes() while Kodi
        changes audio tracks.  Older versions waited here for up to 60 seconds,
        which made the entire viewer appear frozen.  Keep the current picture
        interactive and let the worker re-dispatch the move when it is done.
        """
        with self.render_lock:
            inflight = self.prefetch_inflight
            matching = bool(inflight and inflight.get('index') == index and
                            inflight.get('generation') == self.render_generation)
            if not matching:
                return False
            current = self.pending_next_move
            # A manual key press wins over a slideshow tick for the same target;
            # otherwise keep exactly one pending step to avoid repeat-key skips.
            if (not current or current.get('target') != index or
                    (source == 'manual' and current.get('source') != 'manual')):
                self.pending_next_move = {'target': index, 'source': source}
            return True

    def _mark_bad_image(self, index, reason=''):
        """Remember one unreadable/stuck image for this viewer session.

        The folder listing itself is left untouched so cursor restoration and the
        Kodi Pictures window keep their exact original order. Navigation simply
        walks around indices known to be unusable.
        """
        if index < 0 or index >= len(self.images):
            return False
        already = index in self.bad_image_indices
        self.bad_image_indices.add(index)
        if not already:
            name, path = self.images[index]
            detail = (' (%s)' % reason) if reason else ''
            _log('Image skipped for this session: %s [%s]%s' %
                 (name, path, detail), xbmc.LOGWARNING)
        return not already

    def _next_usable_index(self, start, delta):
        """Return next index not marked bad, wrapping once through the list."""
        if not self.images or not delta:
            return start
        step = 1 if delta > 0 else -1
        count = len(self.images)
        for distance in range(1, count + 1):
            idx = (start + step * distance) % count
            if idx not in self.bad_image_indices:
                return idx
        return start

    def _show_current(self, allow_prefetch=True, animate=True, direction=1):
        if not self.images:
            return False
        target = self.index

        cached = self._take_prefetch(target)
        if cached:
            self._display_rendered(target, cached['path'], cached['slot'], animate=animate, direction=direction)
            self._kick_prefetch()
            return True

        # A jump/backward move makes any look-ahead for the old position obsolete.
        with self.render_lock:
            self.prefetch_request += 1
            self._discard_prefetch_locked()

        slot = self._allocate_slot()
        _name, path = self.images[target]
        self.rendering = True
        try:
            rendered = _render_overlay(path, self.settings, slot)
        except Exception as exc:
            self._mark_bad_image(target, repr(exc))
            _log('Image could not be prepared %s: %r' % (path, exc), xbmc.LOGERROR)
            return False
        finally:
            self.rendering = False

        self._display_rendered(target, rendered, slot, animate=animate, direction=direction)
        self._kick_prefetch()
        return True

    def _kick_prefetch(self):
        if self.closing or not self.images or len(self.images) < 2:
            return
        if self.prefetch_disabled_session:
            return
        if not bool(self.settings.get('preload_next', True)):
            return

        target = self._next_usable_index(self.index, 1)
        if target == self.index:
            return
        generation = self.render_generation
        with self.render_lock:
            if (self.prefetch and self.prefetch.get('index') == target and
                    self.prefetch.get('generation') == generation):
                return
            # At most one image may be prepared in the background. If an older
            # request became obsolete after a jump/settings change, let it finish
            # harmlessly before starting the next one; never run two preloads.
            if self.prefetch_inflight:
                return
            self.prefetch_request += 1
            request = self.prefetch_request
            self._discard_prefetch_locked()
            slot = self._allocate_slot()
            cancel_event = threading.Event()
            self.prefetch_cancel_event = cancel_event
            self.prefetch_inflight = {
                'index': target, 'generation': generation,
                'request': request, 'slot': slot, 'cancel_event': cancel_event,
                'started_at': time.monotonic()
            }

        settings_snapshot = dict(self.settings)
        path = self.images[target][1]

        def worker():
            rendered = ''
            render_failed = False
            failure_reason = ''
            try:
                if self.closing:
                    return
                # Each render uses an immutable unique target, so look-ahead can
                # start immediately without risking a filename collision. Abort obsolete work
                # before decoding if the user jumped elsewhere in the meantime.
                with self.render_lock:
                    inflight = self.prefetch_inflight
                    if (not inflight or inflight.get('request') != request or
                            request != self.prefetch_request):
                        return
                rendered = _render_overlay(path, settings_snapshot, slot, cancel_event)
            except _RenderCancelled:
                rendered = ''
            except Exception as exc:
                render_failed = True
                failure_reason = repr(exc)
                _log('Prefetch failed %s: %r' % (path, exc), xbmc.LOGWARNING)
            finally:
                restart = False
                deferred_action = ''
                with self.render_lock:
                    inflight = self.prefetch_inflight
                    valid = bool(inflight and inflight.get('request') == request)
                    if valid:
                        self.prefetch_inflight = None
                        if self.prefetch_cancel_event is cancel_event:
                            self.prefetch_cancel_event = None
                    if self.prefetch_thread is threading.current_thread():
                        self.prefetch_thread = None
                    kept_render = bool(valid and rendered and not self.closing and
                                       request == self.prefetch_request and
                                       generation == self.render_generation)
                    if valid and render_failed and not self.closing:
                        self._mark_bad_image(target, failure_reason)
                    if kept_render:
                        self.prefetch = {
                            'index': target, 'generation': generation,
                            'request': request, 'slot': slot, 'path': rendered
                        }

                    pending = self.pending_next_move
                    if (valid and pending and pending.get('target') == target and
                            not self.closing):
                        source = pending.get('source', 'manual')
                        if source == 'manual':
                            deferred_action = 'Right'
                        elif self.slideshow_active and not self.slideshow_paused:
                            deferred_action = 'NextPicture'
                        self.pending_next_move = None

                    # A broken image is marked bad above. Do not retry the same
                    # file forever; start look-ahead for the next usable image.
                    # Stale/cancelled requests may also restart normally.
                    if valid and not kept_render and not self.closing and not deferred_action:
                        restart = True
                    if rendered and not kept_render:
                        _safe_remove(rendered)
                if deferred_action:
                    xbmc.executebuiltin('Action(%s)' % deferred_action)
                # A stale one-image look-ahead may finish after a jump. Start the
                # look-ahead for the *current* image only after the stale worker
                # is gone, preserving the strict one-preload limit.
                elif restart:
                    self._kick_prefetch()

        thread = threading.Thread(target=worker, name='JJS-PicturePrefetch')
        thread.daemon = True
        with self.render_lock:
            self.prefetch_thread = thread
        thread.start()

    def _move(self, delta, source='manual'):
        if not self.images or not delta or self.rendering:
            return
        if time.monotonic() < self.transition_until:
            return
        # Clear completed animation mode/ghost visibility before a new move.
        self._settle_transition(force=False)

        old_index = self.index
        attempted = set()
        candidate = self._next_usable_index(old_index, delta)

        while candidate != old_index and candidate not in attempted:
            attempted.add(candidate)

            # The normal +1 path is the only one that can match look-ahead.
            # Never wait for that worker on the GUI thread. A watchdog below
            # marks a truly stuck/broken prefetched image bad and re-dispatches
            # the pending step, so Right can never remain trapped forever.
            if delta == 1 and self._defer_forward_move_if_prefetch_busy(candidate, source):
                return

            with self.render_lock:
                pending = self.pending_next_move
                if pending and pending.get('target') != candidate:
                    self.pending_next_move = None

            self.index = candidate
            if self._show_current(allow_prefetch=(delta == 1), animate=True,
                                  direction=(1 if delta > 0 else -1)):
                return

            # _show_current marks decode/read failures bad. Continue immediately
            # with the following usable image instead of restoring the old index
            # and hitting the same corrupt file on every key press.
            candidate = self._next_usable_index(candidate, delta)

        self.index = old_index

    def _start_slideshow_thread(self):
        if self.slideshow_thread and self.slideshow_thread.is_alive():
            return

        def loop():
            while not self.closing and not self.stop_event.is_set():
                wait_time = 0.10
                try:
                    now = time.monotonic()

                    # A damaged image or a blocked VFS/Pillow read can leave the
                    # one-picture look-ahead worker alive indefinitely. Never let
                    # that trap forward navigation. After a bounded wait, mark
                    # that source bad for this session, abandon prefetch for the
                    # rest of the viewer session (prevents accumulating orphan
                    # workers), and re-dispatch any pending step so it skips over
                    # the bad image. The daemon worker may finish later; its
                    # request id is invalidated and its result is discarded.
                    timeout_action = ''
                    timed_out = False
                    with self.render_lock:
                        inflight = self.prefetch_inflight
                        started_at = inflight.get('started_at', 0.0) if inflight else 0.0
                        if (inflight and started_at and
                                now - started_at >= PREFETCH_TIMEOUT_SECONDS):
                            target = inflight.get('index', -1)
                            cancel_event = inflight.get('cancel_event')
                            if cancel_event is not None:
                                cancel_event.set()
                            self._mark_bad_image(target, 'Prefetch-Timeout %.0f s' % PREFETCH_TIMEOUT_SECONDS)
                            self.prefetch_request += 1
                            self.prefetch_inflight = None
                            if self.prefetch_cancel_event is cancel_event:
                                self.prefetch_cancel_event = None
                            self.prefetch_disabled_session = True
                            pending = self.pending_next_move
                            if pending and pending.get('target') == target:
                                source = pending.get('source', 'manual')
                                if source == 'manual':
                                    timeout_action = 'Right'
                                elif self.slideshow_active and not self.slideshow_paused:
                                    timeout_action = 'NextPicture'
                                self.pending_next_move = None
                            timed_out = True
                    if timed_out:
                        _log('Prefetch abandoned after %.0f s; preloading temporarily disabled' %
                             PREFETCH_TIMEOUT_SECONDS, xbmc.LOGWARNING)
                        if timeout_action:
                            xbmc.executebuiltin('Action(%s)' % timeout_action)

                    # Do not accumulate abandoned VFS workers. Prefetch stays off
                    # while the timed-out daemon thread is still alive. If it
                    # eventually unwinds, automatically allow one-picture
                    # look-ahead again.
                    recover_prefetch = False
                    with self.render_lock:
                        if self.prefetch_disabled_session:
                            thread = self.prefetch_thread
                            if thread is None or not thread.is_alive():
                                self.prefetch_disabled_session = False
                                recover_prefetch = True
                    if recover_prefetch and bool(self.settings.get('preload_next', True)):
                        _log('Prefetch worker available again; preloading resumed')
                        self._kick_prefetch()

                    # XML Visible animations must be settled on Kodi's GUI thread.
                    # 0.1.41 still did three synchronous SetProperty(..., wait=True)
                    # calls here while holding transition_lock.  If Kodi's GUI was
                    # busy (for example around an audio track change), the worker
                    # could wait for the GUI while the next GUI action waited for
                    # transition_lock: a true deadlock with only the background
                    # left visible.  Hand the cleanup back through an ordinary
                    # WindowXML action, exactly like automatic NextPicture steps.
                    queue_settle = False
                    if self.transition_until:
                        wait_time = 0.025
                        if now >= self.transition_until:
                            with self.transition_lock:
                                if self.transition_until and time.monotonic() >= self.transition_until:
                                    serial = self.transition_serial
                                    # Re-queue after 0.5 s if Kodi ever drops the
                                    # first action while another dialog is closing.
                                    if (self.transition_settle_queued_serial != serial or
                                            now - self.transition_settle_queued_at >= 0.5):
                                        self.transition_settle_queued_serial = serial
                                        self.transition_settle_queued_at = now
                                        queue_settle = True
                    if queue_settle:
                        xbmc.executebuiltin('Action(Number3)')

                    if self.play_indicator_until and now >= self.play_indicator_until:
                        # Never synchronously wait for Kodi's GUI thread from this
                        # worker.  The 0.1.36 status timeout added a wait=True
                        # builtin here; if Kodi was busy this could block the
                        # slideshow/timer worker and, together with projector
                        # state, leave only the background visible.  Queue the
                        # property clear asynchronously instead.
                        xbmc.executebuiltin('ClearProperty(JJSSlideshowIcon)')
                        self.play_indicator_until = 0.0

                    interval = max(1, int(self.settings.get('slideshow_interval', 5)))
                    due = (time.monotonic() - self.last_change) >= interval
                    if (self.slideshow_active and not self.slideshow_paused and
                            not self.menu_open and not self.rendering and due):
                        # Never touch WindowXML controls from this worker. Action()
                        # is delivered to the active Kodi window, so _move() stays
                        # on the normal WindowXML callback path.
                        # Use a slideshow-specific action, never Right.  A queued
                        # NextPicture can be identified and discarded after Stop/Pause;
                        # a queued Right was indistinguishable from manual navigation.
                        self.last_change = time.monotonic()
                        xbmc.executebuiltin('Action(NextPicture)')
                except Exception as exc:
                    _log('Slideshow timer: %r' % (exc,), xbmc.LOGWARNING)
                if self.stop_event.wait(wait_time):
                    break

        self.slideshow_thread = threading.Thread(target=loop, name='JJS-PictureSlideshow')
        self.slideshow_thread.daemon = True
        self.slideshow_thread.start()

    def _settle_transition(self, force=False):
        """Commit any completed transition and return to one persistent layer."""
        with self.transition_lock:
            now = time.monotonic()
            if not force and now < self.transition_until:
                return False

            try:
                if self.pending_projector_layer:
                    layer = self.pending_projector_layer
                    # While ProjectorActive is still 1 the overlays cover this
                    # A/B commit, so it cannot flash on screen.
                    self.setProperty('JJSPhotoLayer', layer)
                    self.active_photo_layer = layer
                    self.pending_projector_layer = ''
                self.setProperty('JJSProjectorActive', '0')
                self.setProperty('JJSTransitionMode', 'none')
            except Exception:
                pass
            self.transition_until = 0.0
            self.transition_settle_queued_serial = 0
            self.transition_settle_queued_at = 0.0
        return True

    def _show_play_indicator(self):
        self.setProperty('JJSSlideshowIcon', 'play')
        self.play_indicator_until = time.monotonic() + 2.0

    def _show_pause_indicator(self):
        self.setProperty('JJSSlideshowIcon', 'pause')
        self.play_indicator_until = 0.0

    def _show_stop_indicator(self):
        self.setProperty('JJSSlideshowIcon', 'stop')
        self.play_indicator_until = time.monotonic() + 2.0

    def _clear_slideshow_indicator(self):
        self.clearProperty('JJSSlideshowIcon')
        self.play_indicator_until = 0.0

    def _start_slideshow(self):
        """Start or resume the slideshow and give the current image a full interval."""
        self._settle_transition(force=False)
        self.slideshow_active = True
        self.slideshow_paused = False
        self.last_change = time.monotonic()
        self._show_play_indicator()
        self._refresh_menu_labels()
        self._kick_prefetch()

    def _stop_slideshow(self):
        """Stop automatic advance without interrupting an in-flight transition."""
        self.slideshow_active = False
        self.slideshow_paused = False
        with self.render_lock:
            if self.pending_next_move and self.pending_next_move.get('source') == 'slideshow':
                self.pending_next_move = None
        self.last_change = time.monotonic()
        self._show_stop_indicator()
        # Never tear down a running XML animation.  Forcing JJSTransitionMode to
        # 'none' in mid-flight can leave Kodi's animated control transform in an
        # undefined/off-screen state.  If the transition is already finished we
        # can settle it now; otherwise the next navigation/start will settle it
        # after transition_until.
        self._settle_transition(force=False)
        self._refresh_menu_labels()

    def _pause_slideshow(self):
        """Toggle pause/resume only while a slideshow is active."""
        if not self.slideshow_active:
            return
        self.slideshow_paused = not self.slideshow_paused
        if self.slideshow_paused:
            with self.render_lock:
                if self.pending_next_move and self.pending_next_move.get('source') == 'slideshow':
                    self.pending_next_move = None
            # Pause stops only the timer.  A picture transition already in flight
            # is allowed to finish normally; aborting it can corrupt A/B/ghost
            # layer state.  Completed transitions are settled immediately.
            self._settle_transition(force=False)
            self._show_pause_indicator()
        else:
            # Resuming always starts a fresh full interval on the current picture.
            self._settle_transition(force=False)
            self.last_change = time.monotonic()
            self._show_play_indicator()
            self._kick_prefetch()
        self._refresh_menu_labels()

    def _playpause_slideshow(self):
        """Shield-style single Play/Pause key: start -> pause -> resume."""
        if not self.slideshow_active:
            self._start_slideshow()
        else:
            self._pause_slideshow()

    def _toggle_slideshow(self):
        # Menu button keeps its established Start/Stop behaviour.
        if self.slideshow_active:
            self._stop_slideshow()
        else:
            self._start_slideshow()

    def _open_menu(self):
        # Opening the menu supersedes a not-yet-dispatched manual/slideshow step;
        # otherwise a late Action(Right) could unexpectedly close the menu.
        with self.render_lock:
            self.pending_next_move = None
        self.menu_open = True
        self.setProperty('JJSMenu', '1')
        self._refresh_menu_labels()
        self.setFocusId(BTN_MODE)

    def _close_menu(self):
        self.menu_open = False
        self.clearProperty('JJSMenu')
        self.setFocusId(CTRL_DUMMY_FOCUS)
        self.last_change = time.monotonic()

    def _set_button_label(self, cid, base, value=''):
        try:
            label = base if not value else '%s    [COLOR grey]%s[/COLOR]' % (base, value)
            self.getControl(cid).setLabel(label)
        except Exception:
            pass

    def _refresh_menu_labels(self):
        if not getattr(self, 'ready', False):
            return
        s = self.settings
        self._set_button_label(BTN_MODE, 'Display mode',
                               'Gallery' if s['display_mode'] == 'gallery' else 'Fullscreen')
        self._set_button_label(BTN_GALLERY_SIZE, 'Gallery size', '%d %%' % int(s['gallery_percent']))
        self._set_button_label(BTN_BACKGROUND, 'Background', {
            'viewer_default': 'Picture Viewer Default',
            'skin': 'Skin-Wallpaper',
            'black': 'Black',
            'custom': 'Custom image',
        }.get(s.get('background_mode', 'viewer_default'), 'Picture Viewer Default'))
        self._set_button_label(BTN_CUSTOM_BACKGROUND, 'Custom background image',
                               os.path.basename(s.get('custom_background', '').rstrip('/\\')) or 'not selected')
        self._set_button_label(BTN_BORDER, 'White border', 'On' if s['white_border'] else 'Off')
        self._set_button_label(BTN_BORDER_WIDTH, 'Border width', '%d px' % int(s['border_width']))
        self._set_button_label(BTN_SHADOW, 'Shadow', 'On' if s['shadow'] else 'Off')
        self._set_button_label(BTN_SHADOW_WIDTH, 'Shadow width', '%d px' % int(s['shadow_width']))
        self._set_button_label(BTN_SHADOW_OFFSET, 'Shadow offset', '%d px' % int(s['shadow_offset']))
        self._set_button_label(BTN_SHADOW_OPACITY, 'Shadow strength', '%d %%' % int(s['shadow_opacity']))
        slideshow_label = ('Paused' if self.slideshow_active and self.slideshow_paused
                           else ('Stop' if self.slideshow_active else 'Start'))
        self._set_button_label(BTN_SLIDESHOW, 'Slideshow', slideshow_label)
        self._set_button_label(BTN_SLIDESHOW_INTERVAL, 'Slideshow interval',
                               '%d s' % int(s.get('slideshow_interval', 5)))
        self._set_button_label(BTN_PRELOAD_NEXT, 'Preload next image',
                               'On' if s.get('preload_next', True) else 'Off')
        self._set_button_label(BTN_TRANSITION, 'Transition', {
            'none': 'Off', 'fade': 'Fade', 'zoom': 'Gentle zoom',
            'slide': 'Slide', 'projector': 'Projector'
        }.get(s.get('transition_mode', 'fade'), 'Fade'))
        self._set_button_label(BTN_TRANSITION_DURATION, 'Transition duration',
                               '%d ms' % self._transition_duration_ms())

    def _choose_number(self, heading, current, min_value, max_value):
        value = xbmcgui.Dialog().numeric(0, heading, str(current))
        if value == '':
            return None
        try:
            n = int(value)
        except Exception:
            return None
        return max(min_value, min(max_value, n))

    def _choose_background_image(self):
        # Use Kodi's normal file-manager sources instead of an unscoped browser.
        # The old empty shares argument combined with the bundled default image
        # could open the selector inside this add-on's installation directory.
        # "files" starts from Kodi's normal file sources (plus local drives), so
        # SMB/NFS and other paths configured in the File Manager are reachable.
        current = self.settings.get('custom_background', '')
        if (self.settings.get('background_mode') != 'custom' or
                _norm_vfs_path(current) == _norm_vfs_path(DEFAULT_BACKGROUND_IMAGE)):
            current = ''
        try:
            return xbmcgui.Dialog().browseSingle(
                2, 'Select background image', 'files',
                useThumbs=True, treatAsFolder=False, defaultt=current)
        except TypeError:
            return xbmcgui.Dialog().browseSingle(
                2, 'Select background image', 'files', '', True, False, current)

    def _settings_changed(self, focus_id):
        save_settings(self.settings)
        self.render_generation += 1
        with self.render_lock:
            self.pending_next_move = None
            self.prefetch_request += 1
            self._discard_prefetch_locked()
        self._refresh_menu_labels()
        self._show_current(allow_prefetch=False, animate=False)
        if self.menu_open:
            self.setFocusId(focus_id)

    def onClick(self, control_id):
        s = self.settings
        if control_id == BTN_MODE:
            s['display_mode'] = 'fullscreen' if s['display_mode'] == 'gallery' else 'gallery'
            self._settings_changed(control_id)
        elif control_id == BTN_GALLERY_SIZE:
            options = [60, 65, 70, 75, 80, 82, 85, 88, 90, 92, 95]
            labels = ['%d %%' % v for v in options]
            try:
                pre = options.index(int(s['gallery_percent']))
            except ValueError:
                pre = -1
            idx = xbmcgui.Dialog().select('Gallery size', labels, preselect=pre)
            if idx >= 0:
                s['gallery_percent'] = options[idx]
                self._settings_changed(control_id)
        elif control_id == BTN_BACKGROUND:
            values = [
                ('viewer_default', 'Picture Viewer Default'),
                ('skin', 'Skin-Wallpaper'),
                ('black', 'Black'),
                ('custom', 'Custom image'),
            ]
            current = s.get('background_mode', 'viewer_default')
            pre = next((i for i, item in enumerate(values) if item[0] == current), 0)
            idx = xbmcgui.Dialog().select('Background', [item[1] for item in values], preselect=pre)
            if idx >= 0:
                s['background_mode'] = values[idx][0]
                if s['background_mode'] == 'custom' and not s.get('custom_background'):
                    image = self._choose_background_image()
                    if image:
                        s['custom_background'] = image
                self._settings_changed(control_id)
        elif control_id == BTN_CUSTOM_BACKGROUND:
            image = self._choose_background_image()
            if image:
                s['custom_background'] = image
                s['background_mode'] = 'custom'
                self._settings_changed(control_id)
        elif control_id == BTN_BORDER:
            s['white_border'] = not bool(s['white_border'])
            self._settings_changed(control_id)
        elif control_id == BTN_BORDER_WIDTH:
            n = self._choose_number('Border width in pixels', int(s['border_width']), 0, 100)
            if n is not None:
                s['border_width'] = n
                self._settings_changed(control_id)
        elif control_id == BTN_SHADOW:
            s['shadow'] = not bool(s['shadow'])
            self._settings_changed(control_id)
        elif control_id == BTN_SHADOW_WIDTH:
            n = self._choose_number('Shadow width in pixels', int(s['shadow_width']), 0, 150)
            if n is not None:
                s['shadow_width'] = n
                self._settings_changed(control_id)
        elif control_id == BTN_SHADOW_OFFSET:
            n = self._choose_number('Shadow offset in pixels', int(s['shadow_offset']), 0, 100)
            if n is not None:
                s['shadow_offset'] = n
                self._settings_changed(control_id)
        elif control_id == BTN_SHADOW_OPACITY:
            n = self._choose_number('Shadow strength in percent', int(s['shadow_opacity']), 0, 100)
            if n is not None:
                s['shadow_opacity'] = n
                self._settings_changed(control_id)
        elif control_id == BTN_SLIDESHOW:
            self._toggle_slideshow()
            self.setFocusId(control_id)
        elif control_id == BTN_SLIDESHOW_INTERVAL:
            n = self._choose_number('Slideshow interval in seconds',
                                    int(s.get('slideshow_interval', 5)), 1, 3600)
            if n is not None:
                s['slideshow_interval'] = n
                save_settings(s)
                self.last_change = time.monotonic()
                self._refresh_menu_labels()
                self.setFocusId(control_id)
        elif control_id == BTN_PRELOAD_NEXT:
            s['preload_next'] = not bool(s.get('preload_next', True))
            save_settings(s)
            with self.render_lock:
                self.pending_next_move = None
                self.prefetch_request += 1
                self._discard_prefetch_locked()
            self._refresh_menu_labels()
            if s['preload_next']:
                self._kick_prefetch()
            self.setFocusId(control_id)
        elif control_id == BTN_TRANSITION:
            values = [('none', 'Off'), ('fade', 'Fade'),
                      ('zoom', 'Gentle zoom'), ('slide', 'Slide'),
                      ('projector', 'Projector')]
            current = s.get('transition_mode', 'fade')
            pre = next((i for i, item in enumerate(values) if item[0] == current), 1)
            idx = xbmcgui.Dialog().select('Transition', [item[1] for item in values], preselect=pre)
            if idx >= 0:
                s['transition_mode'] = values[idx][0]
                save_settings(s)
                self._refresh_menu_labels()
                self.setFocusId(control_id)
        elif control_id == BTN_TRANSITION_DURATION:
            values = [120, 180, 250, 350, 500, 700, 1000, 1500]
            labels = ['%d ms' % value for value in values]
            current = self._transition_duration_ms()
            try:
                pre = values.index(current)
            except ValueError:
                pre = 3
            idx = xbmcgui.Dialog().select('Transition duration', labels, preselect=pre)
            if idx >= 0:
                s['transition_duration_ms'] = values[idx]
                save_settings(s)
                self.setProperty('JJSTransitionMs', str(values[idx]))
                self._refresh_menu_labels()
                self.setFocusId(control_id)

    def onAction(self, action):
        action_id = action.getId()

        if action_id == ACTION_JJS_SETTLE:
            # Internal timer -> GUI-thread handoff.  Ignore a stale Number3 from
            # an older transition; it must never cut a newly started animation.
            with self.transition_lock:
                queued_serial = self.transition_settle_queued_serial
                current_serial = self.transition_serial
                due = bool(self.transition_until and
                           time.monotonic() >= self.transition_until)
            if queued_serial == current_serial and due:
                self._settle_transition(force=False)
            elif queued_serial != current_serial:
                with self.transition_lock:
                    if self.transition_settle_queued_serial == queued_serial:
                        self.transition_settle_queued_serial = 0
                        self.transition_settle_queued_at = 0.0
            return

        if self.menu_open:
            if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_PARENT_DIR,
                             ACTION_RIGHT, ACTION_CONTEXT_MENU):
                self._close_menu()
                return
            return

        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK, ACTION_PARENT_DIR):
            self.shutdown()
            self.close()
            return
        if action_id == ACTION_NEXT_PICTURE:
            # Slideshow timer steps use NextPicture, never Right.  If Stop or
            # Pause happened after the action was queued, swallow it here.
            if self.slideshow_active and not self.slideshow_paused:
                self._move(1, source='slideshow')
            return
        if action_id in (ACTION_SELECT_ITEM, ACTION_CONTEXT_MENU):
            self._open_menu()
            return
        if action_id == ACTION_LEFT:
            self._move(-1)
        elif action_id == ACTION_RIGHT:
            self._move(1, source='manual')
        elif action_id == ACTION_UP:
            # Viewer-native slideshow control: start when stopped, otherwise
            # pause/resume.  This intentionally mirrors Play/Pause.
            self._playpause_slideshow()
        elif action_id == ACTION_DOWN:
            # Viewer-native slideshow stop.  Manual Left/Right navigation is
            # unaffected and remains exactly one picture per press.
            self._stop_slideshow()

def _jsonrpc(method, params=None):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        request['params'] = params
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except Exception as exc:
        _log('JSON-RPC %s fehlgeschlagen: %r' % (method, exc), xbmc.LOGERROR)
        return {}


def _plugin_url(**params):
    return 'plugin://%s/?%s' % (ADDON_ID, urlencode(params))


def _picture_sources():
    data = _jsonrpc('Files.GetSources', {'media': 'pictures'})
    result = data.get('result', {}) if isinstance(data, dict) else {}
    sources = result.get('sources', []) if isinstance(result, dict) else []
    clean = []
    for src in sources:
        path = (src.get('file') or '').strip()
        if not path:
            continue
        clean.append(((src.get('label') or path).strip(), path))
    clean.sort(key=lambda item: natural_key(item[0]))
    return clean

def _mime_for_image(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.webp': 'image/webp', '.bmp': 'image/bmp', '.gif': 'image/gif',
        '.tif': 'image/tiff', '.tiff': 'image/tiff'
    }.get(ext, 'image/*')


def _add_plugin_folder(handle, label, real_path):
    item = xbmcgui.ListItem(label=label)
    item.setArt({'icon': 'DefaultFolder.png'})
    url = _plugin_url(action='browse', path=real_path)
    xbmcplugin.addDirectoryItem(handle, url, item, isFolder=True)


def _add_plugin_action(handle, label, action):
    item = xbmcgui.ListItem(label=label)
    item.setArt({'icon': 'DefaultAddSource.png'})
    item.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(handle, _plugin_url(action=action), item, isFolder=False)


def _plugin_manage_sources(handle):
    # Stay inside Kodi's native Pictures/MyPics.xml window.  Switching the
    # current container to Kodi's real pictures source root exposes Kodi's own
    # add/edit/remove source handling and therefore changes sources.xml globally,
    # not a Picture Viewer private list.  Container.Update() keeps navigation
    # history, so Back returns to the JJS Picture Viewer root.
    try:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    except Exception:
        pass
    xbmc.executebuiltin('Container.Update(sources://pictures/)')

def _add_plugin_image(handle, label, real_path):
    # Non-folder plugin item whose click invokes a tiny launch action. The launch
    # action starts our script viewer directly; Kodi's native SlideShow window is
    # never entered, so it never gets a chance to preload the whole directory.
    item = xbmcgui.ListItem(label=label)
    item.setArt({'thumb': real_path, 'icon': real_path})
    try:
        item.setContentLookup(False)
    except Exception:
        pass
    try:
        item.setMimeType(_mime_for_image(real_path))
    except Exception:
        item.setProperty('mimetype', _mime_for_image(real_path))
    item.setProperty('IsPlayable', 'false')
    # Stable identity for restoring the Pictures-list cursor after the modal
    # viewer closes.  Do not infer positions from sort order/view geometry.
    item.setProperty('JJSRealPath', real_path)
    url = _plugin_url(action='launch', path=real_path)
    xbmcplugin.addDirectoryItem(handle, url, item, isFolder=False)


def _plugin_listing(handle, real_path=''):
    xbmcplugin.setContent(handle, 'files')
    xbmcplugin.setPluginCategory(handle, 'Pictures')

    if not real_path:
        sources = _picture_sources()
        _add_plugin_action(handle, 'Manage Kodi picture sources…', 'manage_sources')
        for label, path in sources:
            _add_plugin_folder(handle, label, path)
        xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
        return

    try:
        dirs, files = xbmcvfs.listdir(real_path)
    except Exception as exc:
        _log('Picture folder could not be read %s: %r' % (real_path, exc), xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        return

    dirs = sorted(dirs, key=natural_key)
    images = [name for name in files if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS]
    images.sort(key=natural_key)
    # The viewer will usually be launched from exactly this listing. Persisting
    # the already sorted names avoids scanning a large NAS folder a second time
    # before the first picture can appear.
    _save_listing_cache(real_path, images)

    for name in dirs:
        _add_plugin_folder(handle, name, join_vfs(real_path, name))
    for name in images:
        _add_plugin_image(handle, name, join_vfs(real_path, name))

    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_LABEL)
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def _quote_builtin_arg(value):
    return '"%s"' % (str(value).replace('\\', '\\\\').replace('"', '\\"'))


def _plugin_launch(handle, image_path):
    # A non-folder plugin item normally enters Kodi's resolve/play path. Mark it
    # deliberately unresolved, then launch the script viewer as a separate action.
    # This mirrors established Kodi helper-plugin practice and avoids SlideShow.
    try:
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    except Exception:
        pass
    if image_path:
        xbmc.executebuiltin('RunScript(%s,%s)' % (ADDON_ID, _quote_builtin_arg(image_path)))


def run_plugin():
    try:
        handle = int(sys.argv[1])
    except Exception:
        return
    params = parse_qs(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else '')
    action = (params.get('action') or ['root'])[0]
    path = (params.get('path') or [''])[0]
    if action == 'launch':
        _plugin_launch(handle, path)
    elif action == 'manage_sources':
        _plugin_manage_sources(handle)
    else:
        _plugin_listing(handle, path if action == 'browse' else '')



def _capture_picture_list_state():
    """Capture the real Pictures container that currently owns focus."""
    if xbmcgui.getCurrentWindowId() != WINDOW_PICTURES:
        return None
    # Prefer actual focus.  Several Confluence view containers may technically
    # be visible at once; visibility alone can therefore select the wrong one.
    view_id = None
    for candidate in PICTURE_VIEW_IDS:
        try:
            if xbmc.getCondVisibility('Control.HasFocus(%d)' % candidate):
                view_id = candidate
                break
        except Exception:
            pass
    if view_id is None:
        for candidate in PICTURE_VIEW_IDS:
            try:
                if xbmc.getCondVisibility('Control.IsVisible(%d)' % candidate):
                    view_id = candidate
                    break
            except Exception:
                pass
    return {'view_id': view_id} if view_id is not None else None


def _norm_vfs_path(path):
    return str(path or '').rstrip('/\\').casefold()


def _restore_picture_list_state(state, final_image_path):
    """Focus the exact final file in Kodi's existing Pictures container.

    Position arithmetic is deliberately avoided: panel/list views, parent
    entries, folders and Kodi sort modes can all make Container.Position differ
    from the viewer's image-only index.  Each plugin image carries JJSRealPath,
    so locate that exact item in the live container instead.
    """
    if not state or not final_image_path:
        return
    try:
        view_id = int(state['view_id'])
        wanted = _norm_vfs_path(final_image_path)
        try:
            total = int(str(xbmc.getInfoLabel('Container(%d).NumAllItems' % view_id)).strip() or '0')
        except Exception:
            total = 0

        # NumAllItems includes a possible parent item.  Allow two spare slots
        # because skins/containers differ slightly in how that item is exposed
        # through ListItemAbsolute().
        for pos in range(max(0, total) + 2):
            real = xbmc.getInfoLabel(
                'Container(%d).ListItemAbsolute(%d).Property(JJSRealPath)' % (view_id, pos)
            )
            if real and _norm_vfs_path(real) == wanted:
                xbmc.executebuiltin('Control.SetFocus(%d,%d,absolute)' % (view_id, pos))
                _log('Cursor-Ruecksprung: %s -> Position %d' % (final_image_path, pos))
                return

        # Fallback for a container that lost custom properties: compare Path.
        for pos in range(max(0, total) + 2):
            real = xbmc.getInfoLabel('Container(%d).ListItemAbsolute(%d).Path' % (view_id, pos))
            if real and _norm_vfs_path(real) == wanted:
                xbmc.executebuiltin('Control.SetFocus(%d,%d,absolute)' % (view_id, pos))
                _log('Cursor-Ruecksprung via Path: %s -> Position %d' % (final_image_path, pos))
                return
        _log('Cursor-Ruecksprung: Ziel nicht im Container gefunden: %s' % final_image_path,
             xbmc.LOGWARNING)
    except Exception as exc:
        _log('Cursor-Ruecksprung fehlgeschlagen: %r' % (exc,), xbmc.LOGWARNING)


def _cleanup_temp_files():
    _clear_base_cache()
    try:
        names = os.listdir(TEMP_DIR)
    except Exception:
        names = []
    for name in names:
        if not (name.startswith('jjs_pictureviewer_render_') or
                name.startswith('jjs_pictureviewer_source_')):
            continue
        _safe_remove(os.path.join(TEMP_DIR, name))


def show_image(selected_image):
    folder = parent_path(selected_image)
    if not folder:
        return
    images = _load_listing_cache(folder, selected_image)
    if images:
        _log('Picture list from browser cache: %d images' % len(images))
    else:
        images = list_images(folder)
        _log('Picture list rescanned: %d images' % len(images))
    if not images:
        xbmcgui.Dialog().notification(ADDON_NAME, 'No supported images in this folder',
                                      xbmcgui.NOTIFICATION_WARNING, 3000)
        return
    index = _find_start_index(images, selected_image)
    picture_list_state = _capture_picture_list_state()
    viewer = PictureViewer('PictureViewer.xml', ADDON_PATH, 'Default', '1080i')
    viewer.configure(folder, images, index)
    try:
        viewer.doModal()
    finally:
        try:
            viewer.shutdown()
        except Exception:
            pass
        try:
            final_index = int(getattr(viewer, 'index', index))
            final_index = max(0, min(final_index, len(images) - 1))
            _restore_picture_list_state(picture_list_state, images[final_index][1])
        except Exception as exc:
            _log('Cursor-Ruecksprung nach Viewer fehlgeschlagen: %r' % (exc,), xbmc.LOGWARNING)
        del viewer
        _cleanup_temp_files()



def run_script():
    requested = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else ''
    if requested and os.path.splitext(requested)[1].lower() in IMAGE_EXTENSIONS:
        show_image(requested)
        return
    # The *real* Pictures/MyPics.xml window renders our plugin directory. This
    # preserves Kodi/Confluence browsing and sideblade behaviour, while image
    # clicks route directly to our own viewer instead of SlideShow.
    xbmc.executebuiltin('ActivateWindow(Pictures,plugin://%s/,return)' % ADDON_ID)


def run():
    _cleanup_legacy_media_keymaps()
    if sys.argv and str(sys.argv[0]).startswith('plugin://'):
        run_plugin()
    else:
        run_script()

