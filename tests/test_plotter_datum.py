import json
from dataclasses import asdict, replace

import pytest

from inkstruct.plotter.physical import WorkArea
from inkstruct.plotter.profiles import DeviceAxes, DeviceDatum, DeviceProfile, PlotterProfiles


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


def test_reloaded_measurement_requires_compatible_device_and_dock(tmp_path):
    store = PlotterProfiles(tmp_path)
    profile = DeviceProfile.create("N1", "COM3")
    with pytest.raises(ValueError):
        store.save_sheet(profile, "source", (25, 25), (30, 45), 1)
    datum = replace(DeviceDatum.create(profile, "停靠点"), boot_mode="retained")
    profile = replace(profile, datum=datum)
    store.save(profile)
    store.save_sheet(profile, "source", (25, 25), datum.to_body((42, 53), (12, 8)), 1)
    reopened = PlotterProfiles(tmp_path)
    device, = reopened.devices()
    record = reopened.sheet(device, "source")
    assert device.accepts_sheet(record)
    assert device.datum.to_work(record["virtual"], (-4, 2)) == (26, 47)
    assert not replace(device, axes=DeviceAxes(swap=True)).accepts_sheet(record)
    assert not replace(device, id="other-device").accepts_sheet(record)
    assert reopened.exchange_checkpoint(device) is None


def test_legacy_device_profile_load_does_not_promote_range(tmp_path):
    store = PlotterProfiles(tmp_path)
    profile = DeviceProfile("old", "N1", "COM3", area=WorkArea(0, 0, 100, 100), offset=(0, 0))
    payload = asdict(profile)
    del payload["datum"]
    del payload["limit_area_enabled"]
    store.path.write_text(json.dumps({"devices": {"old": payload}, "placements": {}, "selected": "old"}), "utf-8")
    loaded, = store.devices()
    assert loaded.area == profile.area and loaded.datum is None
    assert loaded.limit_area_enabled and loaded.feed == 2500
    assert DeviceDatum.create(loaded, "纸角").area is None


def test_persist_motion_settings_without_discarding_calibration(tmp_path):
    store = PlotterProfiles(tmp_path)
    profile = DeviceProfile.create("N1", "COM3")
    assert not profile.limit_area_enabled and profile.feed == 2500
    body_area = WorkArea(-5, 0, 250, 220)
    datum = replace(DeviceDatum.create(profile, "A4 纸角"), area=body_area)
    payload = asdict(replace(profile, datum=datum, feed=200))
    del payload["limit_area_enabled"]
    archived = {"devices": {profile.id: payload}, "placements": {}, "selected": profile.id}
    store.path.write_text(json.dumps(archived), "utf-8")
    loaded, = store.devices()
    assert loaded.area is None and loaded.datum == datum
    assert loaded.limit_area_enabled and loaded.feed == 200
    updated = replace(loaded, limit_area_enabled=False)
    store.save(updated)
    second = DeviceProfile.create("另一个 N1", "COM4")
    store.save(replace(second, feed=60))
    reopened = {p.id: p for p in PlotterProfiles(tmp_path).devices()}
    assert reopened[profile.id] == updated and reopened[profile.id].feed == 200
    assert reopened[second.id].feed == 60 and not reopened[second.id].limit_area_enabled
    store.save(replace(updated, limit_area_enabled=True, feed=5000))
    assert {p.id: p for p in store.devices()}[profile.id].datum.area == body_area


def test_legacy_without_applicable_range_defaults_off():
    profile = DeviceProfile.create("N1", "COM3")
    legacy = asdict(profile)
    del legacy["limit_area_enabled"]
    assert not DeviceProfile.from_storage(legacy).limit_area_enabled
    legacy["datum"] = asdict(replace(DeviceDatum.create(profile, "纸角"), device_id="另一个设备",
                                    area=WorkArea(0, 0, 10, 10)))
    assert not DeviceProfile.from_storage(legacy).limit_area_enabled


@pytest.mark.parametrize("field,value", (("feed", 59), ("feed", 5001), ("feed", 100.5),
                                         ("limit_area_enabled", 1), ("limit_area_enabled", "false")))
def test_validate_motion_settings(field, value):
    profile = DeviceProfile.create("N1", "COM3")
    with pytest.raises(ValueError):
        replace(profile, **{field: value})


def test_changing_paper_stops_keeps_marks_but_requires_new_measurement(tmp_path):
    store = PlotterProfiles(tmp_path)
    p = DeviceProfile.create("N1", "COM3")
    p = replace(p, datum=replace(DeviceDatum.create(p, "停靠点"), boot_mode="zero"))
    store.save_sheet(p, "paper", (10, 20), (15, 28), 1)
    new = replace(p, stop_generation="changed")
    store.save(new)
    reopened = PlotterProfiles(tmp_path)
    record = reopened.sheet(new, "paper")
    assert record["mark"] == [10, 20] and not new.accepts_sheet(record)
    assert reopened.sheet(new, "other") is None
    reopened.save_sheet(new, "paper", record["mark"], (16, 30), 5)
    assert new.accepts_sheet(reopened.sheet(new, "paper"))
