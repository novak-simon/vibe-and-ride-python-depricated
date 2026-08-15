import unittest

from workout.model import Interval, Workout
from workout.scheduler import WorkoutScheduler, WorkoutStatus


class FakeMonotonic:
    def __init__(self, start: float = 0.0):
        self._time = start

    def __call__(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds


class WorkoutSchedulerTest(unittest.TestCase):
    def setUp(self):
        intervals = [
            Interval(duration=5.0, power=0.5),
            Interval(duration=8.0, power=0.8),
            Interval(duration=3.0, power=0.4),
        ]
        self.workout = Workout(
            name="test",
            author="author",
            sport_type=None,
            tags=[],
            description=None,
            intervals=intervals,
        )
        self.clock = FakeMonotonic()
        self.scheduler = WorkoutScheduler(self.workout, time_fn=self.clock)

    def test_initial_state(self):
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.NOT_STARTED)
        self.assertEqual(state.total_elapsed, 0.0)
        self.assertEqual(state.total_remaining, 16.0)
        self.assertEqual(state.interval_index, 0)
        self.assertEqual(state.elapsed_in_interval, 0.0)
        self.assertEqual(state.remaining_in_interval, 5.0)
        self.assertTrue(state.interval_changed)

    def test_start_and_progress(self):
        self.scheduler.start()
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.RUNNING)
        self.assertEqual(state.interval_index, 0)
        self.assertEqual(state.total_elapsed, 0.0)
        self.assertTrue(state.interval_changed)

        self.clock.advance(2.3)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.RUNNING)
        self.assertAlmostEqual(state.total_elapsed, 2.3)
        self.assertAlmostEqual(state.elapsed_in_interval, 2.3)
        self.assertAlmostEqual(state.remaining_in_interval, 2.7)
        self.assertEqual(state.interval_index, 0)
        self.assertFalse(state.interval_changed)

    def test_interval_transition(self):
        self.scheduler.start()
        self.clock.advance(5.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.interval_index, 1)
        self.assertAlmostEqual(state.elapsed_in_interval, 0.0)
        self.assertAlmostEqual(state.remaining_in_interval, 8.0)
        self.assertTrue(state.interval_changed)

        self.clock.advance(8.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.interval_index, 2)
        self.assertAlmostEqual(state.elapsed_in_interval, 0.0)
        self.assertTrue(state.interval_changed)

    def test_workout_completion(self):
        self.scheduler.start()
        self.clock.advance(16.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.FINISHED)
        self.assertIsNone(state.interval_index)
        self.assertEqual(state.total_elapsed, 16.0)
        self.assertEqual(state.total_remaining, 0.0)
        self.assertTrue(state.interval_changed)

    def test_pause_and_resume(self):
        self.scheduler.start()
        self.clock.advance(2.0)
        self.scheduler.pause()
        self.clock.advance(5.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.PAUSED)
        self.assertAlmostEqual(state.total_elapsed, 2.0)
        self.assertEqual(state.interval_index, 0)

        self.scheduler.resume()
        self.clock.advance(1.5)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.RUNNING)
        self.assertAlmostEqual(state.total_elapsed, 3.5)
        self.assertEqual(state.interval_index, 0)

    def test_reset_after_finish(self):
        self.scheduler.start()
        self.clock.advance(16.0)
        self.scheduler.get_state()
        self.assertEqual(self.scheduler.status, WorkoutStatus.FINISHED)

        self.scheduler.reset()
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.NOT_STARTED)
        self.assertEqual(state.total_elapsed, 0.0)
        self.assertEqual(state.interval_index, 0)

    def test_resync_to_beginning(self):
        self.scheduler.resync(0.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.NOT_STARTED)
        self.assertEqual(state.total_elapsed, 0.0)
        self.assertEqual(state.interval_index, 0)

    def test_resync_into_middle(self):
        self.scheduler.resync(6.3)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.PAUSED)
        self.assertEqual(state.interval_index, 1)
        self.assertAlmostEqual(state.elapsed_in_interval, 1.3)
        self.assertAlmostEqual(state.remaining_in_interval, 6.7)

    def test_resync_on_boundary(self):
        self.scheduler.resync(5.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.PAUSED)
        self.assertEqual(state.interval_index, 1)
        self.assertAlmostEqual(state.elapsed_in_interval, 0.0)

    def test_resync_to_end(self):
        self.scheduler.resync(16.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.FINISHED)
        self.assertIsNone(state.interval_index)
        self.assertEqual(state.total_elapsed, 16.0)

    def test_resync_past_end(self):
        self.scheduler.resync(20.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.FINISHED)
        self.assertEqual(state.total_elapsed, 16.0)

    def test_resync_while_running_preserves_running_state(self):
        self.scheduler.start()
        self.clock.advance(1.0)
        self.scheduler.resync(10.0)
        state = self.scheduler.get_state()
        self.assertEqual(state.status, WorkoutStatus.RUNNING)
        self.assertEqual(state.total_elapsed, 10.0)
        self.assertEqual(state.interval_index, 1)


if __name__ == "__main__":
    unittest.main()
