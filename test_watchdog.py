import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import subprocess
from f50_watchdog import Policy, save_state, load_state, interface_for, F50Error


class PolicyTests(unittest.TestCase):
    def test_twenty_seconds_and_success_resets_failure(self):
        p = Policy(startup_grace=0)
        self.assertFalse(p.observe(False, 0))
        self.assertFalse(p.observe(False, 19.9))
        self.assertFalse(p.observe(True, 20))
        self.assertFalse(p.observe(False, 21))
        self.assertFalse(p.observe(False, 40.9))
        self.assertTrue(p.observe(False, 41))

    def test_permanent_outage_retries_every_five_minutes(self):
        p = Policy(startup_grace=0)
        self.assertFalse(p.observe(False, 0))
        for attempt in (20, 320, 620, 920):
            self.assertFalse(p.observe(False, attempt - 0.1))
            self.assertTrue(p.observe(False, attempt))
            self.assertFalse(p.observe(False, attempt + 1))

    def test_healthy_during_cooldown_waits_until_five_minutes(self):
        p = Policy(startup_grace=0)
        p.observe(False, 0)
        self.assertTrue(p.observe(False, 20))
        for now in (30, 90, 299, 319):
            self.assertFalse(p.observe(True, now))
            self.assertTrue(p.locked)
        self.assertFalse(p.observe(True, 320))
        self.assertFalse(p.locked)
        p.observe(False, 321)
        self.assertFalse(p.observe(False, 340.9))
        self.assertTrue(p.observe(False, 341))

    def test_brief_recovery_during_wait_does_not_cancel_retry(self):
        p = Policy(startup_grace=0)
        p.observe(False, 0)
        p.observe(False, 20)
        self.assertFalse(p.observe(True, 100))
        self.assertFalse(p.observe(False, 319))
        self.assertTrue(p.observe(False, 320))

    def test_startup_grace(self):
        p = Policy(started=100)
        for now in (100, 200, 279):
            self.assertFalse(p.observe(False, now))
        self.assertFalse(p.observe(False, 280))
        self.assertFalse(p.observe(False, 299))
        self.assertTrue(p.observe(False, 300))

    def test_process_restart_waits_five_minutes_before_retry(self):
        p = Policy(locked=True, started=0, startup_grace=0)
        for now in (0, 20, 299.9):
            self.assertFalse(p.observe(False, now))
        self.assertTrue(p.observe(False, 300))
        self.assertFalse(p.observe(False, 599.9))
        self.assertTrue(p.observe(False, 600))

    def test_lock_survives_disk_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            save_state(path, True)
            p = Policy(locked=load_state(path), startup_grace=0)
            self.assertFalse(p.observe(False, 0))
            self.assertFalse(p.observe(False, 299))
            self.assertTrue(p.observe(False, 300))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{broken')
            with self.assertLogs(level='ERROR'):
                self.assertTrue(load_state(path))

    def test_route_cannot_fall_back_to_unrelated_router(self):
        route = subprocess.CompletedProcess([], 0, 'gateway: 10.80.1.1\ninterface: en0\n', '')
        with patch('f50_watchdog.subprocess.run', return_value=route):
            with self.assertRaises(F50Error):
                interface_for('192.168.0.1')

    def test_direct_usb_route_is_accepted(self):
        route = subprocess.CompletedProcess([], 0, 'gateway: aa:bb:cc:dd:ee:ff\ninterface: en10\n', '')
        with patch('f50_watchdog.subprocess.run', return_value=route):
            self.assertEqual(interface_for('192.168.0.1'), 'en10')


if __name__ == '__main__':
    unittest.main()
