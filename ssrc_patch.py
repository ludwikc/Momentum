"""Runtime patch fixing a crash in discord-ext-voice-recv's SSRC bookkeeping.

`VoiceRecvClient._remove_ssrc` unconditionally does
`self._reader.speaking_timer.drop_ssrc(ssrc)`, but `_reader` defaults to (and is
reset back to) the `MISSING` sentinel outside of an active `listen()` call —
every other method touching `_reader` (`_add_ssrc`, `dispatch_sink`, `get_speaking`)
guards with `if self._reader:` first. When a member's SSRC is torn down while
`_reader` is MISSING (e.g. a leave racing the connect()->listen() window), this
raises `AttributeError: '_MissingSentinel' object has no attribute 'speaking_timer'`
on the voice websocket poller task. That exception is never awaited/caught, so it
only prints a "Task exception was never retrieved" traceback — but the recording
cog's `self.vc` is never torn down, silently wedging `self.recording` True forever
and blocking every future auto-record join.

This patch adds the missing guard so a leaving member can never crash the poller.

Call apply() once before recording (it is idempotent).
"""
import logging

from discord.ext.voice_recv.voice_client import VoiceRecvClient

logger = logging.getLogger("momentum_bot.ssrc_patch")


def apply() -> None:
    """Monkey-patch VoiceRecvClient._remove_ssrc to guard against a MISSING reader. Idempotent."""
    if getattr(VoiceRecvClient, "_ssrc_patched", False):
        return

    def _remove_ssrc(self, *, user_id: int) -> None:
        ssrc = self._id_to_ssrc.pop(user_id, None)
        if ssrc:
            if self._reader:
                self._reader.speaking_timer.drop_ssrc(ssrc)
            self._ssrc_to_id.pop(ssrc, None)

    VoiceRecvClient._remove_ssrc = _remove_ssrc
    VoiceRecvClient._ssrc_patched = True
    logger.info("SSRC-teardown patch applied to voice_recv VoiceRecvClient")
