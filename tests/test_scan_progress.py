from app.services.scan_progress import ScanProgressTracker


def test_scan_progress_tracker_phases_and_percent():
    tracker = ScanProgressTracker()
    tracker.reset()
    assert tracker.snapshot().phase == "prepare"
    assert tracker.snapshot().percent >= 1

    tracker.set_discover(completed=0, total=4, handle="aiko.uz")
    snap = tracker.snapshot()
    assert snap.phase == "discover"
    assert snap.current_handle == "aiko.uz"
    assert snap.percent == 8
    assert snap.done == 0
    assert snap.total == 4

    tracker.set_discover(completed=2, total=4, handle="aiko.uz")
    mid = tracker.snapshot().percent
    assert 8 < mid < 45

    tracker.set_comments(completed=0, total=4, handle="rotan")
    snap = tracker.snapshot()
    assert snap.phase == "comments"
    assert snap.percent >= mid  # монотонность
    assert snap.current_handle == "rotan"

    tracker.set_comments(completed=4, total=4, handle="rotan")
    assert tracker.snapshot().percent == 92

    tracker.update_stats(competitors_checked=2, comments_created=5, leads_created=1)
    tracker.set_done()
    snap = tracker.snapshot()
    assert snap.phase == "done"
    assert snap.percent == 100
    assert snap.competitors_checked == 2
    assert snap.comments_created == 5
    assert snap.leads_created == 1
    assert "phase" in snap.to_dict()


def test_scan_progress_percent_never_decreases():
    tracker = ScanProgressTracker()
    tracker.reset()
    tracker.set_discover(completed=4, total=4, handle="a")
    high = tracker.snapshot().percent
    tracker.set_prepare("не должно откатить")
    assert tracker.snapshot().percent >= high
