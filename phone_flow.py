"""Persistent, local Android control. No model/API client; assistant chooses actions.

Start one bounded worker, then submit structured commands through local files.
Pillow is optional (only crops and image resizing require it).
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import queue
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
APPS = {
    'tiktok': {'packages': ['com.zhiliaoapp.musically', 'com.ss.android.ugc.trill'], 'visual_first': True},
    'linkedin': {'packages': ['com.linkedin.android'], 'visual_first': False},
    'facebook': {'packages': ['com.facebook.katana'], 'visual_first': False},
    'instagram': {'packages': ['com.instagram.android'], 'visual_first': True},
}
ENGAGEMENT = {'like', 'save', 'follow', 'comment'}


class HelperBridge:
    def __init__(self, config, out):
        self.out = out
        self.responses = queue.Queue()
        self.first = True
        self.process = subprocess.Popen([config['artemis_python'], str(ROOT/'artemis_observer.py'),
            '--repo', config['artemis_repo'], '--serial', config['serial'], '--out', str(out), '--serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        def read():
            for line in self.process.stdout:
                try:
                    self.responses.put(json.loads(line))
                except ValueError:
                    continue
            self.responses.put({'ok': False, 'error': 'Helper bridge exited'})
        threading.Thread(target=read, daemon=True).start()

    def request(self, tree_only=False, timeout=12):
        self.process.stdin.write(json.dumps({'tree_only': tree_only, 'out': str(self.out/uuid.uuid4().hex)})+'\n')
        self.process.stdin.flush()
        try:
            response = self.responses.get(timeout=max(.1, timeout))
        except queue.Empty:
            self.close()
            raise TimeoutError('Helper bridge timed out; disabled for this worker')
        if not response['ok']:
            raise RuntimeError(response['error'])
        self.first = False
        return response['result']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class DeviceLock:
    """OS releases the lock on process exit, including abnormal termination."""
    def __init__(self, serial):
        name = hashlib.sha256(serial.encode()).hexdigest()[:20]
        self.path = Path(tempfile.gettempdir()) / 'phoneflow-locks' / (name + '.lock')

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        # Do not read byte zero before locking: Windows denies reads of a byte
        # already locked by another process, even through another file handle.
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b'0')
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('Another phone_flow worker owns this device')
        return self

    def __exit__(self, *_):
        self.file.close()


class Flow:
    def __init__(self, config):
        self.config = config
        self.out = Path(config['session'])
        self.profile = APPS[config['app']]
        self.deadline = time.monotonic() + config['seconds']
        self.last = None
        self.surface = None
        self.package = None
        self.blocked = False
        self.ledger = ROOT / 'phone-flow-state' / 'ledger.jsonl'
        self.reviews = {}
        self.attempts = {}
        self.evidence = {}
        self.calls = 0
        self.helper = None
        self.state = dict(status='starting', pid=os.getpid(), started_utc=utc(),
                          app=config['app'], account=config['account'], serial=config['serial'],
                          seconds=config['seconds'], allow=config['allow'])

    def adb(self, *parts, timeout=12, final=False):
        remaining = self.deadline - time.monotonic()
        if not final and remaining <= 0:
            raise TimeoutError('Session deadline reached')
        budget = timeout if final else max(.05, min(timeout, remaining))
        self.calls += 1
        r = subprocess.run([self.config['adb'], '-s', self.config['serial'], *parts],
                           capture_output=True, timeout=budget)
        if r.returncode:
            raise RuntimeError(r.stderr.decode('utf-8', errors='replace')[:500])
        return r.stdout

    def text_adb(self, *parts, **kw):
        return self.adb(*parts, **kw).decode('utf-8', errors='replace').strip()

    def save(self):
        self.state.update(heartbeat_utc=utc(), remaining_seconds=max(0, round(self.deadline-time.monotonic(), 1)),
                          adb_calls=self.calls)
        write_json(self.out / 'state.json', self.state)

    def log(self, kind, **data):
        event = dict(time=utc(), session=str(self.out), app=self.config['app'],
                     account=self.config['account'], serial=self.config['serial'], kind=kind, **data)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        return event

    def foreground(self):
        raw = self.text_adb('shell', 'dumpsys', 'window')
        focus = re.search(r'mCurrentFocus=([^\r\n]+)', raw)
        # A notification shade / system overlay must not inherit the app beneath it.
        if focus:
            match = re.search(r'\s([\w.]+)/[^\s}]+', focus[1])
            return match[1] if match else None
        match = re.search(r'mFocusedApp=.*?\s([\w.]+)/[^\s}]+', raw)
        return match[1] if match else None

    def guard(self):
        if self.blocked:
            raise RuntimeError('Session paused after a possible login/restriction/permission prompt; stop and inspect manually')
        if self.foreground() != self.package:
            raise RuntimeError('Foreground app changed; observe or launch before acting')

    def fresh(self, request):
        if not self.last or request.get('observation') != self.last['id']:
            raise ValueError('Supply the latest observation ID')
        if time.monotonic()-self.last['mono'] > 45:
            raise ValueError('Observation older than 45 seconds; observe again')

    def geometry(self):
        raw = self.text_adb('shell', 'wm', 'size')
        size = re.findall(r'(\d+)x(\d+)', raw)
        if not size:
            raise RuntimeError('Screen dimensions unavailable')
        w, h = map(int, size[-1])
        info = self.text_adb('shell', 'dumpsys', 'input')
        m = re.search(r'SurfaceOrientation:\s*(\d+)', info)
        if m and int(m[1]) in (1, 3):
            w, h = h, w
        return w, h

    def tree(self):
        if self.helper:
            result = self.helper.request(tree_only=True, timeout=min(12, self.deadline-time.monotonic()))
            raw = Path(result['hierarchy']).read_text(encoding='utf-8')
            return raw, list(ET.fromstring(raw).iter('node'))
        remote = '/sdcard/codex_flow_' + str(os.getpid()) + '.xml'
        self.adb('shell', 'uiautomator', 'dump', remote, timeout=8)
        raw = self.text_adb('exec-out', 'cat', remote)
        nodes = list(ET.fromstring(raw).iter('node'))
        return raw, nodes

    def observe(self, mode='auto', crop=None):
        if mode not in ('auto', 'image', 'text', 'both'):
            raise ValueError('mode must be auto/image/text/both')
        started = time.monotonic()
        oid = uuid.uuid4().hex[:12]
        package = self.foreground()
        result = dict(id=oid, foreground=package, expected_app=package == self.package,
                      text_freshness='unverified', content_understanding='assistant_required')
        nodes = []
        atomic_image = None
        helper_raw = None
        if self.helper:
            try:
                snap = self.helper.request(timeout=min(25 if self.helper.first else 12, self.deadline-time.monotonic()))
                helper_raw = Path(snap['hierarchy']).read_text(encoding='utf-8')
                atomic_image = Path(snap['screenshot']).read_bytes()
                result.update(backend='artemis-helper', atomic=True, helper_elapsed_ms=snap['elapsed_ms'])
            except Exception as e:
                result['helper_fallback'] = type(e).__name__+': '+str(e)[:250]
                self.helper.close()
                self.helper = None
        if not self.helper:
            result.update(backend='adb', atomic=False)
        if mode in ('text', 'both') or (mode == 'auto' and not self.profile['visual_first']):
            try:
                raw, nodes = ((helper_raw, list(ET.fromstring(helper_raw).iter('node')))
                              if helper_raw is not None else self.tree())
                xml = self.out / 'evidence' / (oid + '.xml')
                xml.write_text(raw, encoding='utf-8')
                result['hierarchy'] = str(xml)
                result['elements'] = [{k: n.get(k, '') for k in
                    ('text', 'content-desc', 'resource-id', 'bounds', 'selected', 'checked', 'clickable')}
                    for n in nodes if n.get('text') or n.get('content-desc') or n.get('clickable') == 'true'][:160]
                labels = ' '.join(n.get('text', '') + ' ' + n.get('content-desc', '') for n in nodes)
                prompts = re.findall(r'(?i)\b(?:captcha|verify your identity|account suspended|allow access|sign in to continue)\b', labels)
                if prompts:
                    self.blocked = True
                    result['possible_blocking_prompt'] = sorted(set(prompts))
            except (RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as e:
                result['hierarchy_error'] = str(e)[:300]
        # Auto may omit the image for useful trees, but NEVER calls the tree fresh.
        # Images remain mandatory for video content and unknown/blocked screens.
        useful = sum(bool(n.get('text') or n.get('content-desc')) for n in nodes
                     if n.get('package') == self.package) >= 4
        need_image = mode in ('image', 'both') or (mode == 'auto' and
                      (self.profile['visual_first'] or not useful or package != self.package or self.blocked))
        if need_image or crop:
            data = atomic_image or self.adb('exec-out', 'screencap', '-p')
            if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise RuntimeError('Invalid screenshot')
            path = self.out / 'evidence' / (oid + '.png')
            path.write_bytes(data)
            result['screenshot'] = str(path)
            result['sha256'] = hashlib.sha256(data).hexdigest()
            if crop:
                from PIL import Image
                im = Image.open(io.BytesIO(data))
                x1, y1, x2, y2 = map(int, crop)
                if not (0 <= x1 < x2 <= im.width and 0 <= y1 < y2 <= im.height):
                    raise ValueError('Crop outside actual screenshot pixels')
                region = path.with_name(oid + '-crop.png')
                im.crop((x1, y1, x2, y2)).save(region)
                result.update(crop=str(region), crop_origin=[x1, y1])
            self.evidence[oid] = str(path)
        result['elapsed_ms'] = round((time.monotonic()-started)*1000)
        self.last = dict(id=oid, mono=time.monotonic(), result=result)
        self.surface = None
        write_json(self.out / 'evidence' / (oid + '.json'), result)
        return result

    def handle(self, r):
        if time.time() > r.get('_expires_epoch', float('inf')):
            raise TimeoutError('Queued request expired; no action performed')
        op = r.get('op')
        if op == 'observe':
            return self.observe(r.get('mode', 'auto'), r.get('crop'))
        if op == 'summary':
            return summarize(self.ledger, self.config['app'], self.config['account'])
        if op == 'launch':
            self.adb('shell', 'input', 'keyevent', '224')
            self.adb('shell', 'monkey', '-p', self.package, '-c', 'android.intent.category.LAUNCHER', '1')
            until = min(self.deadline, time.monotonic()+5)
            while time.monotonic() < until:
                if self.foreground() == self.package:
                    break
                time.sleep(.2)
            return self.observe(r.get('mode', 'auto'))
        if op == 'hold':
            seconds = float(r.get('seconds', 5))
            if not 0 <= seconds <= 60:
                raise ValueError('hold seconds must be 0..60')
            # Wake without changing persistent display settings.
            self.guard()
            self.adb('shell', 'input', 'keyevent', '224')
            hold_started = time.monotonic()
            last_wake = hold_started
            end = min(self.deadline, hold_started+seconds)
            while time.monotonic() < end:
                if (self.out / 'stop-request.json').exists():
                    break
                if time.monotonic()-last_wake > 8:
                    self.guard()
                    self.adb('shell', 'input', 'keyevent', '224')
                    last_wake = time.monotonic()
                time.sleep(max(0, min(.2, end-time.monotonic())))
            return {'held_seconds': round(time.monotonic()-hold_started, 2), 'not_a_completed_video_view': True}
        if op == 'review':
            self.fresh(r)
            self.guard()
            post = str(r.get('post', '')).strip()
            if not post or len(post) > 300:
                raise ValueError('post requires a stable URL/ID or creator+caption label (max 300 chars)')
            if post in self.reviews:
                return {'recorded': False, 'reason': 'already reviewed in this session'}
            self.reviews[post] = self.last['id']
            self.log('review', post=post, observation=self.last['id'],
                     evidence=self.last['result'].get('screenshot'), notes=str(r.get('notes', ''))[:1000])
            return {'recorded': True}
        if op == 'verify_action':
            attempt = self.attempts.get(r.get('attempt'))
            if not attempt or attempt.get('verified'):
                raise ValueError('Unknown or already verified attempt')
            self.fresh(r)
            if r['observation'] == attempt['before'] or not self.last['result'].get('screenshot'):
                raise ValueError('Fresh post-action image required for assistant verification')
            if r.get('success') is not True or not str(r.get('evidence_note', '')).strip():
                raise ValueError('Verification requires success=true and an evidence_note describing observed state')
            attempt['verified'] = True
            self.log('verified_action', post=attempt['post'], action=attempt['action'],
                     attempt=r['attempt'], evidence=self.last['result']['screenshot'],
                     note=str(r['evidence_note'])[:500])
            return {'verified': True, 'verification': 'assistant_assertion_with_image'}
        if op == 'next':
            settle = float(r.get('settle', 1))
            if not 0 <= settle <= 3:
                raise ValueError('settle must be 0..3 seconds')
            self.fresh(r)
            self.guard()
            # The caller must identify the currently visible surface each time.
            if r.get('surface') not in ('feed', 'video', 'carousel'):
                raise ValueError('Confirm current surface: feed/video/carousel')
            w, h = self.geometry()
            points = ([int(w*.8), int(h*.45), int(w*.2), int(h*.45)] if r['surface'] == 'carousel'
                      else [int(w*.48), int(h*.74), int(w*.48), int(h*.28)])
            self.adb('shell', 'input', 'swipe', *map(str, points), '450')
            time.sleep(min(settle, max(0, self.deadline-time.monotonic())))
            return self.observe(r.get('mode', 'auto'))
        if op == 'back':
            self.fresh(r)
            self.guard()
            self.adb('shell', 'input', 'keyevent', '4')
            return self.observe(r.get('mode', 'auto'))
        if op == 'type':
            self.fresh(r)
            self.guard()
            value = str(r.get('text', ''))
            if not re.fullmatch(r'[A-Za-z0-9 .,!?@_:/+\-=]{1,1000}', value):
                raise ValueError('Limited ASCII input only, 1..1000 characters')
            if r.get('purpose') not in ('search', 'comment'):
                raise ValueError('Declare purpose search/comment; field must already be focused')
            if r['purpose'] == 'comment':
                if 'comment' not in self.config['allow'] or r.get('post') not in self.reviews:
                    raise ValueError('Comment composition needs authorization and a reviewed post')
                if r.get('submit_search'):
                    raise ValueError('Comment submission requires a separate inspected tap')
            self.adb('shell', 'input', 'text', "'"+value.replace(' ', '%s')+"'")
            if r.get('submit_search'):
                self.adb('shell', 'input', 'keyevent', '66')
            return self.observe(r.get('mode', 'auto'))
        if op == 'tap':
            self.fresh(r)
            self.guard()
            action = r.get('action', 'navigate')
            if action not in ENGAGEMENT | {'navigate'}:
                raise ValueError('Unknown action')
            if action in ENGAGEMENT:
                if action not in self.config['allow']:
                    raise ValueError('This engagement action is not authorized for the session')
                if r.get('post') not in self.reviews:
                    raise ValueError('Record the reviewed post before engagement')
                if any(a['post'] == r['post'] and a['action'] == action for a in self.attempts.values()):
                    raise ValueError('Duplicate engagement attempt blocked; inspect current state')
            xy = r.get('xy')
            selector = r.get('selector')
            if (xy is None) == (selector is None):
                raise ValueError('Supply exactly one of xy or selector')
            if selector:
                if len(selector) != 1 or next(iter(selector)) not in ('text', 'resource-id', 'content-desc'):
                    raise ValueError('Use one exact text/resource-id/content-desc selector')
                key, val = next(iter(selector.items()))
                _, nodes = self.tree()
                boxes = {n.get('bounds') for n in nodes if n.get(key) == val and n.get('enabled') != 'false'}
                if len(boxes) != 1:
                    raise ValueError('Selector missing or ambiguous; no tap performed')
                nums = re.findall(r'\d+', next(iter(boxes)))
                if len(nums) != 4:
                    raise ValueError('Invalid bounds')
                a, b, c, d = map(int, nums)
                xy = [(a+c)//2, (b+d)//2]
            w, h = self.geometry()
            if len(xy) != 2 or not (0 <= int(xy[0]) < w and 0 <= int(xy[1]) < h):
                raise ValueError('Tap outside actual screenshot pixels')
            attempt_id = uuid.uuid4().hex[:12]
            before = self.last['id']
            if action in ENGAGEMENT:
                self.attempts[attempt_id] = dict(post=r['post'], action=action, before=before, verified=False)
                self.log('action_attempt', post=r['post'], action=action, attempt=attempt_id)
            self.adb('shell', 'input', 'tap', str(int(xy[0])), str(int(xy[1])))
            result = self.observe(r.get('mode', 'image'), r.get('crop'))
            if action in ENGAGEMENT:
                result['attempt'] = attempt_id
            return result
        raise ValueError('Unsupported operation')

    def run(self):
        with DeviceLock(self.config['serial']):
            try:
                inventory = self.text_adb('get-state')
                if inventory != 'device':
                    raise RuntimeError('Device not authorized/ready')
                packages = self.text_adb('shell', 'pm', 'list', 'packages').splitlines()
                self.package = next((p for p in self.profile['packages'] if 'package:'+p in packages), None)
                if not self.package:
                    raise RuntimeError('Target app not installed')
                if self.config.get('artemis_repo'):
                    self.helper = HelperBridge(self.config, self.out/'helper')
                self.state.update(status='running', package=self.package)
                self.save()
                last_wake = time.monotonic()
                last_save = time.monotonic()
                while time.monotonic() < self.deadline:
                    if time.monotonic()-last_save >= 1:
                        self.save()
                        last_save = time.monotonic()
                    if (self.out / 'stop-request.json').exists():
                        break
                    if time.monotonic()-last_wake > 8:
                        self.adb('shell', 'input', 'keyevent', '224')
                        last_wake = time.monotonic()
                    requests = sorted((self.out / 'requests').glob('*.json'))
                    if not requests:
                        time.sleep(.1)
                        continue
                    path = requests[0]
                    result_path = self.out / 'results' / path.name
                    if result_path.exists():
                        path.unlink()
                        continue
                    started = time.monotonic()
                    try:
                        result = dict(ok=True, result=self.handle(read_json(path)))
                    except Exception as e:
                        result = dict(ok=False, error=type(e).__name__+': '+str(e))
                    result['elapsed_ms'] = round((time.monotonic()-started)*1000)
                    write_json(result_path, result)
                    path.unlink()
                self.state['status'] = 'stopped'
            except Exception as e:
                self.state.update(status='failed', error=type(e).__name__+': '+str(e))
            finally:
                if self.helper:
                    self.helper.close()
                # Bounded adb timeouts mean cleanup is best effort, not an exact OS scheduler guarantee.
                try:
                    self.adb('shell', 'input', 'keyevent', '224', final=True, timeout=5)
                    self.adb('shell', 'input', 'keyevent', '3', final=True, timeout=5)
                    self.state['cleanup'] = 'Home command sent'
                except Exception as e:
                    self.state['cleanup_error'] = str(e)
                self.state['ended_utc'] = utc()
                self.save()
                write_json(self.out / 'summary.json', summarize(self.ledger, self.config['app'], self.config['account']))


def summarize(path, app, account):
    rows = []
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            row = json.loads(line)
            if row['app'] == app and row['account'] == account:
                rows.append(row)
    reviews = [r for r in rows if r['kind'] == 'review']
    counts = {a: sum(r['kind'] == 'verified_action' and r.get('action') == a for r in rows) for a in sorted(ENGAGEMENT)}
    return dict(app=app, account=account, review_exposures=len(reviews),
                unique_post_labels=len({r['post'] for r in reviews}), verified_actions=counts,
                percentages={a: round(n/len(reviews)*100, 2) if reviews else None for a, n in counts.items()},
                scope='phone_flow ledger only; historical text reports are not imported',
                counting='review exposure per post label per session; assistant-verified actions only')


def legacy_busy(workspace, serial):
    if not workspace:
        return []
    busy = []
    for path in Path(workspace).glob('work/**/timer.json'):
        try:
            row = read_json(path)
            end = dt.datetime.fromisoformat(row['started_utc']) + dt.timedelta(seconds=row['duration_seconds'])
            if row.get('serial') == serial and row.get('status') == 'running' and dt.datetime.now(dt.timezone.utc) < end:
                busy.append(str(path))
        except (ValueError, KeyError, OSError):
            continue
    return busy


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start')
    start.add_argument('--serial', required=True)
    start.add_argument('--app', choices=APPS, required=True)
    start.add_argument('--account', required=True, help='Verified account label; never guessed by controller')
    start.add_argument('--seconds', type=int, default=420)
    start.add_argument('--allow', nargs='*', choices=sorted(ENGAGEMENT), default=[])
    start.add_argument('--session', type=Path, required=True)
    start.add_argument('--legacy-workspace', type=Path, default=ROOT.parent)
    start.add_argument('--adb', default=shutil.which('adb') or str(Path(os.environ.get('LOCALAPPDATA', ''))/'Programs/platform-tools/adb.exe'))
    start.add_argument('--artemis-repo', type=Path, help='Optional installed Artemis checkout, observation only')
    start.add_argument('--artemis-python', type=Path, help='Python from the Artemis environment')
    call = sub.add_parser('call')
    call.add_argument('--session', type=Path, required=True)
    call.add_argument('--request-file', type=Path, required=True)
    call.add_argument('--wait', type=float, default=30)
    for name in ('status', 'stop'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--session', type=Path, required=True)
    worker = sub.add_parser('_worker')
    worker.add_argument('--session', type=Path, required=True)
    args = p.parse_args()
    session = args.session.resolve()
    if args.command == 'start':
        if not 1 <= args.seconds <= 3600:
            p.error('seconds must be 1..3600')
        if not Path(args.adb).is_file():
            p.error('ADB executable not found')
        if bool(args.artemis_repo) != bool(args.artemis_python):
            p.error('Supply both --artemis-repo and --artemis-python')
        if args.artemis_repo and (not (args.artemis_repo/'artemis').is_dir() or not args.artemis_python.is_file()):
            p.error('Artemis checkout or Python not found')
        if session.exists():
            p.error('Use a new session directory')
        busy = legacy_busy(args.legacy_workspace, args.serial)
        if busy:
            p.error('Legacy timed session still active: '+', '.join(busy))
        # Probe OS lock without taking over a worker. Worker acquires it again.
        with DeviceLock(args.serial):
            pass
        for name in ('requests', 'results', 'evidence'):
            (session/name).mkdir(parents=True)
        config = dict(serial=args.serial, app=args.app, account=args.account, seconds=args.seconds,
                      allow=args.allow, session=str(session), adb=str(Path(args.adb).resolve()))
        if args.artemis_repo:
            config.update(artemis_repo=str(args.artemis_repo.resolve()), artemis_python=str(args.artemis_python.resolve()))
        write_json(session/'config.json', config)
        with (session/'worker.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_worker', '--session', str(session)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        print(json.dumps({'pid': child.pid, 'session': str(session), 'status': 'starting; inspect status'}))
    elif args.command == '_worker':
        try:
            Flow(read_json(session/'config.json')).run()
        except Exception as e:
            write_json(session/'state.json', dict(status='failed', error=str(e), pid=os.getpid()))
    elif args.command == 'call':
        state = read_json(session/'state.json')
        if state['status'] != 'running':
            raise RuntimeError('Worker not running: '+state['status'])
        heartbeat = dt.datetime.fromisoformat(state['heartbeat_utc'])
        if (dt.datetime.now(dt.timezone.utc)-heartbeat).total_seconds() > 90:
            raise RuntimeError('Worker heartbeat stale; inspect before proceeding')
        request = read_json(args.request_file)
        # Request expiry prevents a timed-out queued click firing later.
        rid = str(time.time_ns())+'-'+uuid.uuid4().hex
        request['_expires_epoch'] = time.time()+max(1, args.wait)
        write_json(session/'requests'/(rid+'.json'), request)
        deadline = time.monotonic()+max(1, args.wait)
        response = session/'results'/(rid+'.json')
        while time.monotonic() < deadline:
            if response.exists():
                print(json.dumps(read_json(response), ensure_ascii=False))
                return
            time.sleep(.1)
        print(json.dumps({'pending': rid, 'result_path': str(response), 'warning': 'Do not resubmit a mutation until its result is checked'}))
    elif args.command == 'status':
        print(json.dumps(read_json(session/'state.json'), ensure_ascii=False))
    elif args.command == 'stop':
        write_json(session/'stop-request.json', {'time': utc()})
        print(json.dumps({'stop_requested': True, 'note': 'inspect status for Home cleanup result'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': type(exc).__name__+': '+str(exc)}), file=sys.stderr)
        sys.exit(1)
