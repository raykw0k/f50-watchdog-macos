import unittest
from unittest.mock import Mock
from f50_reboot import F50, F50Error


class AuthenticationTests(unittest.TestCase):
    def test_wrong_password_never_sends_reboot(self):
        device = F50('http://192.168.0.1')
        device.get = Mock(return_value={'LD': 'nonce'})
        device.post = Mock(return_value={'result': '1'})
        with self.assertRaises(F50Error):
            device.reboot('wrong')
        self.assertEqual(device.post.call_count, 1)
        self.assertEqual(device.post.call_args.args[0], 'LOGIN')

    def test_empty_response_is_not_success(self):
        device = F50('http://192.168.0.1')
        device.login = Mock()
        device.get = Mock(side_effect=[
            {'wa_inner_version': 'B16', 'cr_version': 'MU300'},
            {'RD': 'nonce'},
        ])
        device.post = Mock(return_value={})
        with self.assertRaises(F50Error):
            device.reboot('password')
        self.assertEqual(device.post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
