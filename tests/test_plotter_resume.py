"""Regression coverage for persistent pen-on-paper checkpoints and conservative routing."""

import pytest

from inkstruct.plotter.grbl import GrblLink, MotionControl
from inkstruct.plotter.physical import PaperRegistration, position_page
from inkstruct.plotter.schema import PlotPage, PlotStroke
from inkstruct.plotter.write_session import ProgressFile, lengths, route_page
from test_plotter_machine import SimulatedGrbl


def sample():
    return PlotPage(0, 70, 60, tuple(
        PlotStroke(str(i), ((x, y), (x + 1, y)), independent=0 < i < 5)
        for i, (x, y) in enumerate(((5, 5), (40, 5), (7, 6), (39, 6), (8, 6), (45, 5)))))


def test_routing_preserves_text_and_segments():
    page = sample()
    result = route_page(page)
    assert lengths(result.strokes)[0] < lengths(page.strokes)[0]
    assert (result.strokes[0], result.strokes[-1]) == (page.strokes[0], page.strokes[-1])
    geometry = lambda p: {s.stroke_id: frozenset(s.points) for s in p.strokes}
    assert geometry(page) == geometry(result)


@pytest.mark.parametrize("already_complete", [False, True])
def test_dropped_connection_reopen_and_resume(tmp_path, already_complete):
    page = sample()
    machine = position_page(page, PaperRegistration((0, 0)))
    args = tmp_path, "document", page, "pdf", "device"
    first = ProgressFile.for_page(*args)
    transport = SimulatedGrbl()
    link = GrblLink(transport)
    link.connect()
    def drop(data):
        if data.startswith(b"G1 Z-") and first.read() == (3, True):
            raise OSError("USB removed")
    transport.on_write = drop
    with pytest.raises(OSError, match="USB removed"):
        link.run_page(machine, None, MotionControl(), journal=first)
    journal = ProgressFile.for_page(*args)
    assert journal.read() == (3, True)
    assert ProgressFile.for_page(tmp_path,"edited",page,"pdf","device").read() == (0, False)
    start = 3 + int(already_complete)
    resumed = SimulatedGrbl()
    second = GrblLink(resumed)
    second.connect()
    second.run_page(machine, None, MotionControl(), journal=journal, start=start, height=-.8)
    assert journal.read() == (len(page.strokes), False)
    assert resumed.commands.count(b"G1 Z-0.8 F5000\n") == len(page.strokes) - start
    targets = []
    down = False
    for command in resumed.commands:
        if command.startswith(b"G1 Z"):
            down = command.startswith(b"G1 Z-")
        elif down and command.startswith(b"G1 X"):
            targets.append(command)
    expected = [second.xy_command(s.points[-1], 2500).encode() + b"\n" for s in machine.strokes[start:]]
    assert targets == expected
