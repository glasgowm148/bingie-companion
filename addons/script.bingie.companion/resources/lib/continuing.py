"""Merge explicitly configured video folders without accounts or shared profile state."""
import traceback
from urllib.parse import urlsplit

from .common import rpc


def allowed_source(value):
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ('plugin', 'videodb') and not parsed.username and not parsed.password
    except ValueError:
        return False


def resume_position(item):
    try:
        return max(0, float((item.get('resume') or {}).get('position') or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def item_key(item):
    unique = item.get('uniqueid') or {}
    if isinstance(unique, dict) and unique.get('tmdb'):
        identity = ('tmdb', str(unique['tmdb']))
    else:
        identity = ('title', str(item.get('showtitle') or item.get('title') or item.get('label') or '').casefold())
    if not identity[1]:
        return ('file', item.get('file'))
    return identity + (item.get('season'), item.get('episode'))


def merge(rows):
    """Keep original playback URLs; a resumable duplicate wins over an unstarted episode."""
    found, order = {}, []
    for items in rows:
        for item in items:
            if not item.get('file') or (item.get('playcount', 0) and not resume_position(item)):
                continue
            key = item_key(item)
            if key not in found:
                found[key] = item
                order.append(key)
            elif resume_position(item) and not resume_position(found[key]):
                found[key] = item
    return [found[k] for k in order]


def load_rows(xbmc, addon):
    rows, failures = [], 0
    # Kodi creates a separate settings store for this add-on in each profile. Never read
    # master-profile settings, another user's cache, or cloud watch history as a fallback.
    for index in range(1, 4):
        source = addon.getSetting('source%d' % index).strip()
        if not source:
            continue
        if not allowed_source(source):
            failures += 1
            continue
        try:
            # Kodi applies ``limits`` after the source add-on has built its whole listing: this caps
            # only the size of the reply, not the work done by that add-on or the request's duration.
            rows.append(rpc(xbmc, 'Files.GetDirectory', directory=source, media='video',
                            limits={'start': 0, 'end': 100},
                            properties=['title', 'showtitle', 'season', 'episode', 'playcount',
                                        'resume', 'art', 'uniqueid']).get('files', []))
        except RuntimeError:
            failures += 1
    return merge(rows), failures


def add_items(xbmcgui, xbmcplugin, handle, rows):
    for row in rows:
        li = xbmcgui.ListItem(label=row.get('label') or row.get('title') or '', offscreen=True)
        li.setArt(row.get('art') or {})
        info = li.getVideoInfoTag()  # InfoTagVideo setters: Kodi 20+ (xbmc.python 3.0.1)
        info.setTitle(row.get('title') or row.get('label') or '')
        info.setTvShowTitle(row.get('showtitle') or '')
        for key, setter in (('season', info.setSeason), ('episode', info.setEpisode),
                            ('playcount', info.setPlaycount)):
            if isinstance(row.get(key), int):
                setter(row[key])
        resume = row.get('resume') or {}
        if resume_position(row):
            info.setResumePoint(resume_position(row), float(resume.get('total') or 0))
        folder = row.get('filetype') == 'directory'
        li.setProperty('IsPlayable', 'false' if folder else 'true')
        xbmcplugin.addDirectoryItem(handle, row['file'], li, isFolder=folder)


def serve(handle, mode):
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcplugin
    # Kodi waits for exactly one endOfDirectory per plugin call, whatever happens below.
    succeeded = False
    try:
        addon = xbmcaddon.Addon()
        if mode == 'settings':
            addon.openSettings()
            succeeded = True
        elif mode == 'continue':
            rows, failures = load_rows(xbmc, addon)
            xbmcplugin.setContent(handle, 'episodes')
            add_items(xbmcgui, xbmcplugin, handle, rows)
            # Do not mark a failed request as an authoritative empty successful folder/cache.
            succeeded = bool(rows) or not failures
    except Exception:
        xbmc.log('[Bingie Companion] Continue Watching failed:\n' + traceback.format_exc(), xbmc.LOGERROR)
        succeeded = False
    finally:
        xbmcplugin.endOfDirectory(handle, succeeded=succeeded, cacheToDisc=False)
