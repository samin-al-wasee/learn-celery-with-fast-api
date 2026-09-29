"""Observe group-call topologies with real WebRTC peers: full mesh vs SFU.

Usage:  python scripts/observe_group_call.py

For N = 2..5 participants, each sends a synthetic noise video (320x240 @ 15 fps, so the
VP8 encoder has real work) for a fixed window and we read RTP bytesSent from getStats().
  mesh: every participant has a peer connection to every other one (N-1 uploads each)
  sfu : every participant has one connection to a forwarding server (aiortc MediaRelay)
Signaling is done in-process here: this measures topology, not our WebSocket.
"""
import asyncio
import os
import time
from fractions import Fraction

import av
from aiortc import MediaStreamTrack, RTCPeerConnection
from aiortc.contrib.media import MediaRelay

WINDOW = 6.0
FPS = 15


class NoiseTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self) -> None:
        super().__init__()
        self._pts = 0

    async def recv(self) -> av.VideoFrame:
        await asyncio.sleep(1 / FPS)
        frame = av.VideoFrame(320, 240, "yuv420p")
        for plane in frame.planes:
            plane.update(os.urandom(plane.buffer_size))
        frame.pts, frame.time_base = self._pts, Fraction(1, FPS)
        self._pts += 1
        return frame


async def connect(a: RTCPeerConnection, b: RTCPeerConnection, prepare_answer=None) -> None:
    await a.setLocalDescription(await a.createOffer())
    await b.setRemoteDescription(a.localDescription)
    # aiortc: the answering side attaches tracks AFTER setRemoteDescription, onto the
    # transceivers the offer created (earlier addTrack makes an extra, unnegotiated one).
    if prepare_answer is not None:
        prepare_answer(b)
    await b.setLocalDescription(await b.createAnswer())
    await a.setRemoteDescription(b.localDescription)


async def sent_bytes(pcs: list[RTCPeerConnection]) -> int:
    total = 0
    for pc in pcs:
        for s in (await pc.getStats()).values():
            if s.type == "outbound-rtp":
                total += s.bytesSent
    return total


async def mesh(n: int) -> tuple[float, int]:
    conns: dict[int, list[RTCPeerConnection]] = {i: [] for i in range(n)}
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = RTCPeerConnection(), RTCPeerConnection()
            # M7: in a mesh every participant encodes and uploads its video once PER PEER.
            a.addTrack(NoiseTrack())
            conns[i].append(a)
            conns[j].append(b)
            pairs.append((a, b))
    await asyncio.gather(*(connect(a, b, lambda pc: pc.addTrack(NoiseTrack())) for a, b in pairs))
    await asyncio.sleep(WINDOW)
    per_peer = [await sent_bytes(conns[i]) for i in range(n)]
    for a, b in pairs:
        await a.close()
        await b.close()
    return sum(per_peer) / n / WINDOW / 1024, n - 1


async def sfu(n: int) -> tuple[float, float]:
    relay = MediaRelay()
    clients = [RTCPeerConnection() for _ in range(n)]
    server = [RTCPeerConnection() for _ in range(n)]
    loop = asyncio.get_running_loop()
    incoming = {i: loop.create_future() for i in range(n)}
    for i, (c, s) in enumerate(zip(clients, server)):
        # Each participant uploads ONE stream and receives n-1.
        c.addTransceiver(NoiseTrack(), direction="sendonly")
        for _ in range(n - 1):
            c.addTransceiver("video", direction="recvonly")
        s.on("track", lambda track, i=i: incoming[i].set_result(track) if not incoming[i].done() else None)

    def server_sends(pc: RTCPeerConnection) -> None:
        for t in pc.getTransceivers()[1:]:
            t.direction = "sendrecv"  # answers the client's recvonly as sendonly

    await asyncio.gather(*(connect(c, s, server_sends) for c, s in zip(clients, server)))
    tracks = [await asyncio.wait_for(incoming[i], 10) for i in range(n)]
    for i, s in enumerate(server):
        senders = [t.sender for t in s.getTransceivers()[1:]]
        others = [tracks[j] for j in range(n) if j != i]
        for sender, track in zip(senders, others):
            # M7: forward the single upload (aiortc re-encodes per sender; a real SFU only
            # forwards RTP packets, which is why production SFUs are C++/Go/Rust).
            sender.replaceTrack(relay.subscribe(track))
    await asyncio.sleep(WINDOW)
    client_up = [await sent_bytes([c]) for c in clients]
    server_up = await sent_bytes(server)
    for pc in clients + server:
        await pc.close()
    return sum(client_up) / n / WINDOW / 1024, server_up / WINDOW / 1024


async def phase(name: str, coro, limit: float = 120):  # noqa: ANN001, ANN201
    # A stuck negotiation must fail loudly, not hang the experiment (the bare-await run stalled).
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, limit)
    except TimeoutError:
        print(f"   ... {name} did NOT finish within {limit:.0f}s", flush=True)
        return None
    print(f"   ... {name} done in {time.perf_counter() - t0:.0f}s", flush=True)
    return result


async def main() -> None:
    rows = []
    for n in (2, 3, 4, 5):
        t0 = time.process_time()
        m = await phase(f"mesh({n})", mesh(n))
        mesh_cpu = time.process_time() - t0
        s = await phase(f"sfu({n})", sfu(n))
        rows.append((n, m, s, mesh_cpu))
    print(f"{'N':>2} | {'mesh: uplink/participant':>25} {'encodes':>8} | {'SFU: uplink/participant':>24} | {'SFU server uplink':>18}")
    for n, m, s, mesh_cpu in rows:
        mesh_col = f"{m[0]:>20.0f} KB/s {m[1]:>8}" if m else f"{'timed out':>25} {'-':>8}"
        sfu_col = f"{s[0]:>19.0f} KB/s | {s[1]:>13.0f} KB/s" if s else f"{'timed out':>24} | {'-':>18}"
        print(f"{n:>2} | {mesh_col} | {sfu_col}   (mesh CPU {mesh_cpu:.1f}s)")


if __name__ == "__main__":
    asyncio.run(main())
