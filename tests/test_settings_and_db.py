# tests/test_settings_and_db.py
from pathlib import Path

import pytest

from garud360.config import defaults as cfg
from garud360.config import settings_schema as sc
from garud360.core.models import Camera, Space
from garud360.db.repositories import RepoError


def test_every_default_is_valid_and_documented():
    for s in sc.SETTINGS:
        assert sc.coerce(s.key, s.default) == s.default, s.key
        assert s.help and (s.increase or s.decrease or s.kind == "str"), s.key
    assert sc.defaults()["person_conf"] == 0.40
    assert sc.defaults()["trigger_frames"] == 3
    assert sc.defaults()["release_frames"] == 15
    assert len({s.key for s in sc.SETTINGS}) == len(sc.SETTINGS)


def test_coerce_rejects_out_of_range_and_garbage():
    with pytest.raises(ValueError):
        sc.coerce("person_conf", 1.5)
    with pytest.raises(ValueError):
        sc.coerce("trigger_frames", 0)
    with pytest.raises(ValueError):
        sc.coerce("person_conf", "abc")
    with pytest.raises(ValueError):
        sc.coerce("person_conf", float("nan"))
    with pytest.raises(ValueError):
        sc.coerce("model_task", "bogus")
    with pytest.raises(ValueError):
        sc.coerce("nope", 1)
    assert sc.coerce("latch_until_reset", "yes") is True
    assert sc.coerce("inference_device", "cuda:2") == "cuda:2"   # editable choice


def test_settings_guide_file_in_sync():
    path = Path(__file__).resolve().parent.parent / "docs" / "SETTINGS_GUIDE.md"
    assert path.read_text(encoding="utf-8").strip() == sc.guide_markdown().strip(), \
        "Run: python scripts/generate_settings_guide.py"


def test_settings_store_roundtrip_and_overrides(repos):
    st = repos["settings"]
    assert st.all()["person_conf"] == 0.40
    st.update({"person_conf": 0.55})
    assert st.all()["person_conf"] == 0.55
    assert st.effective({"person_conf": 0.30})["person_conf"] == 0.30
    assert st.effective({"image_size": 320})["image_size"] == 640      # not overridable per space
    with pytest.raises(RepoError):
        st.update({"person_conf": 5})
    with pytest.raises(RepoError):
        st.update({"siren_low_hz": 3000, "siren_high_hz": 1000})
    st.reset_all()
    assert st.all()["person_conf"] == 0.40


def _cam(name, ip="192.168.1.5"):
    return Camera(0, 0, name, "droidcam", {"ip": ip, "port": 4747})


def test_space_crud_limits_and_validation(repos):
    sp = repos["spaces"]
    s = sp.save(Space(0, "Bay 1", cameras=[_cam("A"), _cam("B")], plc_config={"type": "simulated"},
                      overrides={"person_conf": 0.5}))
    assert s.id and [c.name for c in s.cameras] == ["A", "B"] and s.overrides["person_conf"] == 0.5
    with pytest.raises(RepoError):
        sp.save(Space(0, "bay 1"))                                  # duplicate (case-insensitive)
    with pytest.raises(RepoError):
        sp.save(Space(0, "X", cameras=[_cam(f"c{i}") for i in range(11)]))   # > 10 cameras
    with pytest.raises(RepoError):
        sp.save(Space(0, "X", cameras=[_cam("a"), _cam("A")]))      # duplicate camera
    with pytest.raises(RepoError):
        sp.save(Space(0, "X", cameras=[Camera(0, 0, "a", "droidcam", {"ip": "", "port": 4747})]))
    with pytest.raises(RepoError):
        sp.save(Space(0, "X", overrides={"image_size": 320}))      # global-only setting
    # update: remove one camera, keep other id
    keep = s.cameras[1]
    s.cameras = [keep]
    s2 = sp.save(s)
    assert [c.id for c in s2.cameras] == [keep.id]
    sp.delete(s.id)
    assert sp.count() == 0


def test_max_50_spaces(repos):
    sp = repos["spaces"]
    for i in range(cfg.MAX_SPACES):
        sp.save(Space(0, f"S{i}"))
    with pytest.raises(RepoError, match="maximum of 50"):
        sp.save(Space(0, "one too many"))


def test_events_and_daily_summary(repos):
    ev = repos["events"]
    ev.add("person_violation", "p", space_id=1, space_name="A", snapshot_path="x.jpg")
    ev.add("camera_fault", "c", space_id=1, space_name="A")
    ev.add("crane_released", "r", space_id=1, space_name="A")
    summary = ev.daily_summary(7)
    assert len(summary) == 7 and summary[-1]["person"] == 1 and summary[-1]["camera"] == 1
    assert len(ev.search(kinds=["person_violation"])) == 1
    assert len(ev.search(with_snapshot=True)) == 1
    assert ev.per_space_today() == {1: 1}
    assert ev.purge_older_than(1) == 0
