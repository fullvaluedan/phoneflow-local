"""Optional observation adapter using an installed Artemis checkout.

Run with that checkout's Python environment. Uses its helper transport manager
and local HTTP observations; never creates an LLM runner. No vendored sources.
"""
import argparse
import base64
import contextlib
import io
import json
from pathlib import Path
import sys
import time
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--serial', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--tree-only', action='store_true')
    p.add_argument('--serve', action='store_true', help='JSON lines on stdin/stdout; keep imports and helper client warm')
    a = p.parse_args()
    sys.path.insert(0, str(a.repo.resolve()))
    a.out.mkdir(parents=True, exist_ok=True)
    # Keep library logging and accidental prints away from the JSON response.
    with contextlib.redirect_stdout(sys.stderr):
        from artemis.runtime.helper_manager import helper_manager
        session = helper_manager.attach(a.serial, provision=False)
        # The general Artemis observation client also manages wake/display policy.
        # PhoneFlow owns that responsibility, so use the helper transport directly.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def fetch(path):
            headers = {'X-Artemis-Token': session.token} if session.token else {}
            request = urllib.request.Request(session.base_url+path, headers=headers)
            with opener.open(request, timeout=8) as response:
                return response.read()
        try:
            def observe(tree_only, out):
                started = time.monotonic()
                out = Path(out).resolve()
                out.mkdir(parents=True, exist_ok=True)
                # No install/upgrade/enable. Uses an already configured helper only.
                if tree_only:
                    xml = fetch('/dump_xml').decode('utf-8')
                    result = {'backend': 'artemis-helper', 'atomic': False}
                else:
                    snap = json.loads(fetch('/snapshot?fields=xml'))
                    if not snap.get('success') or not snap.get('has_screenshot') or not snap.get('screenshot_base64'):
                        raise RuntimeError('Helper did not provide an atomic screenshot; use ADB observation')
                    xml = snap.get('xml', '')
                    from PIL import Image
                    data = base64.b64decode(snap['screenshot_base64'], validate=True)
                    path = out/'snapshot.png'
                    with Image.open(io.BytesIO(data)) as im:
                        im.save(path)
                    result = {'backend': 'artemis-helper', 'atomic': True, 'screenshot': str(path)}
                path = out/'hierarchy.xml'
                path.write_text(xml, encoding='utf-8')
                result.update(hierarchy=str(path), elapsed_ms=round((time.monotonic()-started)*1000),
                              text_freshness='not_guaranteed_by_atomic_capture')
                return result
            if a.serve:
                for line in sys.stdin:
                    try:
                        request = json.loads(line)
                        result = {'ok': True, 'result': observe(request.get('tree_only', False), request['out'])}
                    except Exception as e:
                        result = {'ok': False, 'error': type(e).__name__+': '+str(e)}
                    print(json.dumps(result), file=sys.__stdout__, flush=True)
            else:
                result = observe(a.tree_only, a.out)
        finally:
            helper_manager.detach(a.serial)
    if not a.serve:
        print(json.dumps(result))


if __name__ == '__main__':
    main()
