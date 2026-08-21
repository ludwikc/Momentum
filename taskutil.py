"""Small asyncio task helpers shared by cogs."""
import asyncio


def cancel_unless_current(task: asyncio.Task | None) -> None:
    """Cancel ``task`` unless it is the task calling us (or None).

    ``task.cancel()`` on the *currently running* task raises CancelledError at
    its next await — a teardown helper invoked from within that task would kill
    its own caller's remaining pipeline. That is exactly how every recording
    that hit the safety cap lost its transcript/upload: the safety task ran the
    publish pipeline, teardown cancelled the safety task, boom. Guarding here
    keeps teardown safe to call from any task, including the guarded one.
    """
    if task is not None and task is not asyncio.current_task():
        task.cancel()
