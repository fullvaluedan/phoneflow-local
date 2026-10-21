"""Guard and accounting tests. Device observation was explored with Artemis.

These tests do not touch a device or assert unverified app UI paths.
"""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from phone_flow import Flow, DeviceLock, summarize, legacy_busy, write_json, read_json, utc


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = Flow(dict(session=str(self.root), app='tiktok', account='fixture',
                              serial='fixture', seconds=60, allow=[], adb='unused'))
        self.flow.package = 'com.zhiliaoapp.musically'
        self.flow.ledger = self.root/'ledger.jsonl'
        self.flow.adb = Mock(side_effect=AssertionError('Unexpected device action'))
        self.flow.foreground = Mock(return_value=self.flow.package)
        self.flow.last = dict(id='fresh', mono=time.monotonic(), result={'screenshot': 'fixture.png'})

    def test_expired_queue_never_acts(self):
        with self.assertRaises(TimeoutError):
            self.flow.handle({'op': 'launch', '_expires_epoch': 0})
        self.flow.adb.assert_not_called()

    def test_stale_coordinate_never_acts(self):
        self.flow.last['mono'] -= 46
        with self.assertRaises(ValueError):
            self.flow.handle(dict(op='tap', observation='fresh', xy=[1, 1]))
        self.flow.adb.assert_not_called()

    def test_wrong_app_never_acts(self):
        self.flow.foreground.return_value = 'com.android.settings'
        with self.assertRaises(RuntimeError):
            self.flow.handle(dict(op='next', observation='fresh', surface='video'))
        self.flow.adb.assert_not_called()

    def test_unauthorized_like_never_acts(self):
        with self.assertRaises(ValueError):
            self.flow.handle(dict(op='tap', observation='fresh', action='like', post='p', xy=[1, 1]))
        self.flow.adb.assert_not_called()

    def test_duplicate_review_does_not_inflate_denominator(self):
        request = dict(op='review', observation='fresh', post='creator/title')
        self.assertTrue(self.flow.handle(request)['recorded'])
        self.assertFalse(self.flow.handle(request)['recorded'])
        self.assertEqual(summarize(self.flow.ledger, 'tiktok', 'fixture')['review_exposures'], 1)

    def test_attempt_is_not_counted_as_success(self):
        self.flow.log('review', post='p')
        self.flow.log('action_attempt', post='p', action='like', attempt='x')
        self.assertEqual(summarize(self.flow.ledger, 'tiktok', 'fixture')['verified_actions']['like'], 0)

    def test_verification_needs_new_image(self):
        self.flow.attempts['x'] = dict(post='p', action='like', before='fresh', verified=False)
        with self.assertRaises(ValueError):
            self.flow.handle(dict(op='verify_action', observation='fresh', attempt='x', success=True, evidence_note='red heart'))

    def test_duplicate_verification_rejected(self):
        self.flow.attempts['x'] = dict(post='p', action='like', before='before', verified=False)
        r = dict(op='verify_action', observation='fresh', attempt='x', success=True, evidence_note='red heart')
        self.flow.handle(r)
        with self.assertRaises(ValueError):
            self.flow.handle(r)

    def test_account_ledgers_are_separate(self):
        self.flow.log('review', post='p')
        self.assertEqual(summarize(self.flow.ledger, 'instagram', 'fixture')['review_exposures'], 0)
        self.assertEqual(summarize(self.flow.ledger, 'tiktok', 'other')['review_exposures'], 0)

    def test_legacy_running_timer_blocks_new_session(self):
        write_json(self.root/'work'/'old'/'timer.json', dict(serial='fixture', status='running', started_utc=utc(), duration_seconds=60))
        self.assertEqual(len(legacy_busy(self.root, 'fixture')), 1)
        self.assertEqual(legacy_busy(self.root, 'other'), [])

    def test_system_overlay_does_not_inherit_underlying_app(self):
        self.flow.foreground = Flow.foreground.__get__(self.flow)
        self.flow.text_adb = Mock(return_value='mCurrentFocus=Window{1 u0 NotificationShade}\nmFocusedApp=ActivityRecord{1 u0 com.linkedin.android/.Main}')
        self.assertIsNone(self.flow.foreground())

    def test_existing_like_attempt_cannot_toggle_again(self):
        self.flow.config['allow'] = ['like']
        self.flow.reviews['p'] = 'fresh'
        self.flow.attempts['x'] = dict(post='p', action='like', verified=False)
        with self.assertRaises(ValueError):
            self.flow.handle(dict(op='tap', observation='fresh', action='like', post='p', xy=[1, 1]))
        self.flow.adb.assert_not_called()

    def test_device_lock_excludes_second_owner(self):
        with DeviceLock(str(self.root)):
            with self.assertRaises(RuntimeError):
                with DeviceLock(str(self.root)):
                    self.fail('Second owner acquired the same device lock')

    def test_selector_requires_visual_region(self):
        with self.assertRaisesRegex(ValueError, 'selector_region'):
            self.flow.handle(dict(op='tap', observation='fresh', selector={'text': 'Posts'}))
        self.flow.adb.assert_not_called()

    def test_stale_selector_position_rejected(self):
        self.flow.tree = Mock(return_value=(None, [{'text': 'Posts', 'bounds': '[0,1000][100,1100]'}]))
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.flow.handle(dict(op='tap', observation='fresh', selector={'text': 'Posts'}, selector_region=[0,0,200,400]))
        self.flow.adb.assert_not_called()

    def test_navigation_can_use_90_second_observation(self):
        self.flow.last['mono'] -= 90
        self.flow.tree = Mock(return_value=(None, []))
        self.flow.geometry = Mock(return_value=(1080,2392))
        self.flow.adb = Mock()
        self.flow.observe = Mock(return_value={'id': 'next'})
        self.flow.handle(dict(op='next', observation='fresh', surface='video', settle=0))
        self.flow.adb.assert_called_once()

    def test_blocking_prompt_prevents_scroll(self):
        self.flow.tree = Mock(return_value=(None, [{'text': 'Verify your identity'}]))
        with self.assertRaises(RuntimeError):
            self.flow.handle(dict(op='next', observation='fresh', surface='video'))
        self.flow.adb.assert_not_called()

    def test_timer_cannot_be_rearmed(self):
        self.flow.state['browsing_started_utc'] = utc()
        with self.assertRaisesRegex(ValueError, 'once'):
            self.flow.handle(dict(op='begin_browse', observation='fresh', surface='feed'))

    def test_android16_landscape_viewport_dimensions(self):
        self.flow.text_adb = Mock(side_effect=['Physical size: 1080x2392',
            'Viewport INTERNAL: displayId=0, uniqueId=local:1, orientation=1, logicalFrame=[0, 0, 2392, 1080]'])
        self.assertEqual(self.flow.geometry(), (2392, 1080))

    def test_read_retries_transient_windows_sharing_error(self):
        with patch.object(Path, 'read_text', side_effect=[PermissionError(), '{"ok": true}']), patch('phone_flow.time.sleep'):
            self.assertEqual(read_json('fixture.json'), {'ok': True})


if __name__ == '__main__':
    unittest.main()
