"""Local addition: atem_control.localhooks, which names switchers Bonjour
has not heard (the Connect page's Recent list and the connection log)."""
from unittest import mock

import pytest

from atem_control import localhooks
from atem_control.localhooks import LocalHooks

IP = '192.0.2.40'


@pytest.fixture
def data_dir(tmp_path, settings):
    settings.DATA_DIR = tmp_path
    return tmp_path


def _live(name, model):
    return mock.patch.object(localhooks, '_live', return_value=(name, model))


def test_connect_saves_the_switchers_own_name(data_dir):
    with _live('Main Hall', 'ATEM 1 M/E Production Studio 4K'):
        LocalHooks().record_video_mode(IP, '1080p59.94')
    assert localhooks.saved(IP) == ('Main Hall', 'ATEM 1 M/E Production Studio 4K')


def test_saved_name_survives_a_restart_and_the_switcher_being_off(data_dir):
    with _live('Main Hall', 'ATEM 1 M/E Production Studio 4K'):
        LocalHooks().record_video_mode(IP, '1080p59.94')
    with _live('', ''), mock.patch('atem_control.hooks.Hooks.name_for_ip', return_value=None):
        assert LocalHooks().name_for_ip(IP) == 'Main Hall'


def test_bonjour_name_comes_first_then_the_live_session(data_dir):
    localhooks.remember(IP, 'Old name')
    with mock.patch('atem_control.hooks.Hooks.name_for_ip', return_value='From Bonjour'):
        assert LocalHooks().name_for_ip(IP) == 'From Bonjour'
    with mock.patch('atem_control.hooks.Hooks.name_for_ip', return_value=None), _live('Live name', ''):
        assert LocalHooks().name_for_ip(IP) == 'Live name'


def test_unknown_switcher_has_no_name(data_dir):
    with _live('', ''), mock.patch('atem_control.hooks.Hooks.name_for_ip', return_value=None):
        assert LocalHooks().name_for_ip(IP) is None


def test_rename_updates_the_saved_name(data_dir):
    localhooks.remember(IP, 'Main Hall', 'ATEM 1 M/E Production Studio 4K')
    LocalHooks().record_named(IP, 'Chapel')
    assert localhooks.saved(IP) == ('Chapel', 'ATEM 1 M/E Production Studio 4K')


def test_unnamed_switcher_is_read_once_in_the_background(data_dir):
    started = []
    with _live('', ''), mock.patch('atem_control.hooks.Hooks.name_for_ip', return_value=None), \
         mock.patch.object(localhooks.threading, 'Thread') as thread:
        thread.return_value.start.side_effect = lambda: started.append(1)
        localhooks._fetching.discard(IP)
        LocalHooks().name_for_ip(IP)
        LocalHooks().name_for_ip(IP)
    assert started == [1]          # once per run, however often the page asks


def test_background_read_skips_addresses_not_in_recent(data_dir):
    runs = {}

    class Inline:
        def __init__(self, target, **_kw):
            runs['target'] = target

        def start(self):
            runs['target']()

    acquire = mock.MagicMock()
    with mock.patch.object(localhooks.threading, 'Thread', Inline), \
         mock.patch.object(localhooks, '_recent_ips', return_value={'192.0.2.99'}), \
         mock.patch('atemwire.pool.acquire_connection', acquire):
        localhooks._fetching.discard(IP)
        localhooks._fetch_once(IP)
    acquire.assert_not_called()
