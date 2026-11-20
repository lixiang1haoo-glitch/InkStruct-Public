import json
from dataclasses import asdict, replace

import pytest

from inkstruct.plotter.physical import WorkArea
from inkstruct.plotter.profiles import DeviceAxes, DeviceDatum, DeviceProfile, PageAlignment, PlotterProfiles


@pytest.mark.parametrize("swap", (False, True))
@pytest.mark.parametrize("mirror_x,mirror_y", ((False, False), (False, True), (True, False), (True, True)))
def test_body_ranges_follow_reference_with_signed_calibrated_axes(swap, mirror_x, mirror_y):
    axes = DeviceAxes(x_scale=1.25, y_scale=.8, mirror_x=mirror_x, mirror_y=mirror_y, swap=swap)
    profile = DeviceProfile("physical-device", "N1", "COM3", axes=axes)
    datum = DeviceDatum.create(profile, "A4 左上角")
    first_origin, new_origin = (12, 8), (-4, 2)
    physical_area = WorkArea(-10, -8, 100, 200)
    work_area = datum.to_work_area(physical_area, first_origin)
    assert asdict(datum.to_body_area(work_area, first_origin)) == pytest.approx(asdict(physical_area))
    moved = datum.to_work_area(physical_area, new_origin)
    expected = WorkArea(work_area.left - 16, work_area.top - 6, work_area.right - 16, work_area.bottom - 6)
    assert asdict(moved) == pytest.approx(asdict(expected))
    checkpoint = (31, 42.5)
    alternate = replace(datum, area=physical_area, checkpoint=checkpoint)
    for origin in (first_origin, new_origin):
        observed = alternate.to_work(checkpoint, origin)
        assert alternate.to_body(observed, origin) == checkpoint
        assert alternate.origin_from_checkpoint(observed) == origin
    with pytest.raises(ValueError, match="备用基准点"):
        datum.origin_from_checkpoint((0, 0))


def test_reloaded_placement_requires_current_datum_and_preserves_historic_records(tmp_path):
    store = PlotterProfiles(tmp_path)
    profile = DeviceProfile.create("N1", "COM3")
    paper = PageAlignment((25, 25), (185, 25), .05, 1.025)
    key = ("source-page", "左上挡边", paper)
    store.place(profile, *key, (42, 53), (0, 0), connection="before")
    legacy = store.place(profile, *key)
    assert store.placed_position(profile, legacy, connection="before", offset=(0, 0)) == (42, 53)
    assert store.placed_position(profile, legacy, connection="new", offset=(0, 0)) is None
    assert store.placed_position(profile, legacy, connection="before", offset=(0, 1)) is None

    datum = replace(DeviceDatum.create(profile, "纸角"), area=WorkArea(-5, -10, 190, 280), checkpoint=(25, 35))
    profile = replace(profile, datum=datum)
    store.save(profile)
    store.place(profile, *key, (42, 53), (0, 0), connection="before", datum_origin=(12, 8))
    reloaded = PlotterProfiles(tmp_path)
    device, = reloaded.devices()
    assert device == profile
    record = reloaded.place(device, *key)
    assert record["body_point"] == [30, 45] and record["datum_id"] == datum.id
    assert reloaded.placed_position(device, record, connection="after", offset=(0, 0)) is None
    assert reloaded.placed_position(device, record, connection=None, offset=(0, 0), datum_origin=(-4, 2)) is None
    assert reloaded.placed_position(device, record, connection="after", offset=(0, 0), datum_origin=(-4, 2)) == (26, 47)
    assert reloaded.placed_position(device, legacy, connection="before", offset=(0, 0), datum_origin=(-4, 2)) is None
    with pytest.raises(ValueError, match="找回机身基准"):
        reloaded.place(device, *key, (0, 0), (0, 0), connection="after")
    assert reloaded.place(device, *key) == record
    new_fixture = replace(profile, datum=DeviceDatum.create(profile, "另一个挡边"))
    assert reloaded.placed_position(new_fixture, record, connection="before", offset=(0, 0), datum_origin=(12, 8)) is None
    assert reloaded.place(new_fixture, *key) == legacy
    assert len(reloaded.read()["placements"]) == 2
    assert replace(device, axes=DeviceAxes(swap=True)).datum is None
    assert replace(device, id="other-device").datum is None


def test_legacy_device_profile_load_does_not_promote_range(tmp_path):
    store = PlotterProfiles(tmp_path)
    profile = DeviceProfile("old", "N1", "COM3", area=WorkArea(0, 0, 100, 100), offset=(0, 0))
    payload = asdict(profile)
    del payload["datum"]
    store.path.write_text(json.dumps({"devices": {"old": payload}, "placements": {}, "selected": "old"}), "utf-8")
    loaded, = store.devices()
    assert loaded.area == profile.area and loaded.datum is None
    assert DeviceDatum.create(loaded, "纸角").area is None
