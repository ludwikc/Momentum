"""Runtime patch adding DAVE (E2EE) decryption to discord-ext-voice-recv.

Discord now mandates the DAVE end-to-end-encryption protocol on voice calls.
discord.py 2.7 establishes and maintains the DAVE/MLS group session (it processes
the MLS welcome/commit/proposal gateway ops), exposing a *receive-capable*
`dave_session` on the voice connection. But discord-ext-voice-recv reads and
transport-decrypts packets through its own pipeline and never applies the DAVE
layer, so the Opus payload stays E2E-encrypted and `opus_decode` raises
"corrupted stream" — which, worse, propagates and kills the packet-router thread.

This patch wraps PacketDecoder._decode_packet so that, when an active DAVE session
is present, each transport-decrypted payload is run through
`dave_session.decrypt(user_id, MediaType.audio, payload)` before Opus decoding.
It also makes decode failures non-fatal (emit a silence frame instead of throwing),
so a single bad packet can no longer stop the whole recording. Modeled on Craig,
which performs the equivalent DAVE decrypt inside its Eris fork.

Call apply() once before recording (it is idempotent).
"""
import logging

import davey
from discord.ext.voice_recv.opus import PacketDecoder

logger = logging.getLogger("momentum_bot.dave_patch")

# Log a decrypt failure at most once per ssrc to avoid flooding the log.
_warned_ssrc: set[int] = set()


def _active_dave_session(decoder: PacketDecoder):
    """Return the connection's DAVE session if it is established, else None."""
    vc = decoder.sink.voice_client
    if vc is None:
        return None
    sess = getattr(getattr(vc, "_connection", None), "dave_session", None)
    if sess is not None and getattr(sess, "ready", False):
        return sess
    return None


def _dave_decrypt(decoder: PacketDecoder, raw: bytes):
    """DAVE-decrypt a transport-decrypted payload.

    Returns the decrypted Opus bytes, the input unchanged when no DAVE session is
    active (transport-only call), or None to signal "drop this packet".
    """
    if not raw:
        return raw
    sess = _active_dave_session(decoder)
    if sess is None:
        return raw  # non-E2EE session: payload is already plain Opus
    vc = decoder.sink.voice_client
    user_id = vc._get_id_from_ssrc(decoder.ssrc)
    if user_id is None:
        return None  # can't attribute the packet to a sender yet
    try:
        out = sess.decrypt(user_id, davey.MediaType.audio, raw)
    except Exception as e:
        if decoder.ssrc not in _warned_ssrc:
            _warned_ssrc.add(decoder.ssrc)
            logger.warning("DAVE decrypt failed (ssrc=%s user=%s, %d bytes): %s",
                           decoder.ssrc, user_id, len(raw), e)
        return None
    return out or None


def apply() -> None:
    """Monkey-patch voice_recv's PacketDecoder to apply DAVE decryption. Idempotent."""
    if getattr(PacketDecoder, "_dave_patched", False):
        return

    def _decode_packet(self, packet):
        assert self._decoder is not None

        # Real packet: DAVE-decrypt, then Opus-decode (never let either throw upward).
        if packet:
            raw = _dave_decrypt(self, packet.decrypted_data)
            if raw is None:
                return packet, self._decoder.decode(None, fec=False)
            try:
                return packet, self._decoder.decode(raw, fec=False)
            except Exception:
                return packet, self._decoder.decode(None, fec=False)

        # Fake packet: use the next buffered packet for FEC, mirroring the original.
        next_packet = self._buffer.peek_next()
        if next_packet is not None:
            nextraw = _dave_decrypt(self, next_packet.decrypted_data)
            try:
                if nextraw:
                    return packet, self._decoder.decode(nextraw, fec=True)
            except Exception:
                pass
        return packet, self._decoder.decode(None, fec=False)

    PacketDecoder._decode_packet = _decode_packet
    PacketDecoder._dave_patched = True
    logger.info("DAVE decryption patch applied to voice_recv PacketDecoder")
