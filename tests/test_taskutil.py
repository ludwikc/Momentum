import asyncio
import unittest

from taskutil import cancel_unless_current


class CancelUnlessCurrentTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_a_different_task(self):
        async def sleeper():
            await asyncio.sleep(30)

        task = asyncio.create_task(sleeper())
        await asyncio.sleep(0)  # let it start
        cancel_unless_current(task)
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_does_not_cancel_the_calling_task(self):
        # Regression for the safety-cap bug: the safety task ran the publish
        # pipeline itself; teardown cancelling it killed the pipeline at its
        # next await. With the guard, the pipeline finishes.
        finished = []

        async def pipeline():
            cancel_unless_current(asyncio.current_task())
            await asyncio.sleep(0)  # a naive task.cancel() would explode here
            finished.append(True)

        await asyncio.create_task(pipeline())
        self.assertEqual(finished, [True])

    async def test_none_is_a_no_op(self):
        self.assertIsNone(cancel_unless_current(None))
