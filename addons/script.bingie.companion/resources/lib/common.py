"""Small boundaries shared by optional companion actions."""
import json


def rpc(xbmc, method, **params):
    response = json.loads(xbmc.executeJSONRPC(json.dumps(
        {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    if 'error' in response:
        raise RuntimeError('Kodi request failed: ' + method)
    return response.get('result', {})


def skin_string(xbmc, key, value):
    # Keys are fixed by this module's callers; JSON quoting protects commas, quotes and actions.
    if not key.replace('_', '').isalnum():
        raise ValueError('Invalid skin setting')
    xbmc.executebuiltin('Skin.SetString(%s,%s)' % (key, json.dumps(value, ensure_ascii=False)))
