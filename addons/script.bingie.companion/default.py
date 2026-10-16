"""Kodi script actions and the optional profile-local Continue Watching plugin."""
import sys
from urllib.parse import parse_qs


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) > 1 and argv[1].lstrip('-').isdigit():
        from resources.lib.continuing import serve
        options = parse_qs(argv[2].lstrip('?')) if len(argv) > 2 else {}
        serve(int(argv[1]), options.get('mode', ['continue'])[0])
    else:
        from resources.lib.navigation import dispatch
        dispatch(argv[1] if len(argv) > 1 else 'settings')


if __name__ == '__main__':
    main()
