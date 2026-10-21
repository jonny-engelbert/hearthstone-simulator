"""Event history sharing preserves rollback, branch isolation and plain JSON."""

from copy import deepcopy
import json
import unittest

from hearthstone.events import EventLog, copy_state
from test_zones import ZoneFixture


class EventLogTests(unittest.TestCase):
    def test_copy_shares_immutable_payloads_but_not_sequence(self):
        event = dict(type='TEST', nested=dict(values=[1, dict(amount=2)]))
        log = EventLog([event])
        event['nested']['values'].append(99)
        self.assertEqual(len(log[0]['nested']['values']), 2)
        other = deepcopy(log)
        self.assertIsNot(other, log)
        self.assertIs(other[0], log[0])
        other.append(dict(type='NEW'))
        self.assertEqual(len(log), 1)
        with self.assertRaises(TypeError):
            other[0]['type'] = 'CHANGED'
        with self.assertRaises(TypeError):
            other[0]['nested']['values'].append(3)
        with self.assertRaises(TypeError):
            other[0]['nested']['values'][1]['amount'] = 99

    def test_plain_json_restore_is_normalized_without_mutating_input(self):
        state = dict(events=[dict(type='TEST', targets=['id'])], entities=[])
        copy = copy_state(state)
        self.assertEqual(json.loads(json.dumps(copy)), state)
        state['events'][0]['targets'].append('new')
        state['entities'].append('new')
        self.assertEqual(copy['events'][0]['targets'], ['id'])
        self.assertEqual(copy['entities'], [])
        for operation in (
            lambda: copy['events'][0].update(type='BAD'),
            lambda: copy['events'][0]['targets'].clear(),
        ):
            with self.assertRaises(TypeError):
                operation()

    def test_all_log_insertion_paths_freeze_payloads(self):
        log = EventLog()
        log.append({'nested': []})
        log.extend([{'nested': []}])
        log.insert(0, {'nested': []})
        log[0] = {'nested': []}
        log[1:2] = [{'nested': []}]
        log += [{'nested': []}]
        for event in log:
            with self.assertRaises(TypeError):
                event['nested'].append(1)
        self.assertEqual(json.loads(json.dumps(log)), [{'nested': []}] * 4)


class EventBranchTests(ZoneFixture):
    def test_action_branches_share_only_immutable_history(self):
        self.add('CS2_029', 'fireball', zone='HAND')
        before = deepcopy(self.state)
        first = self.engine.play(self.state, 0, 'fireball', 'hero-1')
        second = self.engine.play(self.state, 0, 'fireball', 'hero-0')
        self.assertIs(first['events'][0], self.state['events'][0])
        self.assertEqual(self.state, before)
        self.assertNotEqual(first, second)
        with self.assertRaises(TypeError):
            first['events'][0]['type'] = 'CORRUPTED'
        first['events'].append(dict(type='DEBUG'))
        self.assertNotEqual(len(first['events']), len(second['events']))
        self.assertEqual(self.get('hero-0', second)['damage'], 6)

    def test_checkpoint_action_matches_continuation_and_failure_is_atomic(self):
        self.add('CS2_029', 'fireball', zone='HAND')
        restored = json.loads(json.dumps(self.state))
        actual = self.engine.play(self.state, 0, 'fireball', 'hero-1')
        self.assertEqual(actual, self.engine.play(restored, 0, 'fireball', 'hero-1'))
        before = deepcopy(restored)
        with self.assertRaises(ValueError):
            self.engine.play(restored, 0, 'fireball', 'missing')
        self.assertEqual(restored, before)
