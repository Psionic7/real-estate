import pytest

from scripts.import_juso_geocodes import validated_center


def test_coordinate_audit_accepts_one_compact_site():
    point, reason = validated_center([(37.32, 127.09), (37.3201, 127.0901)], "41465")
    assert point == pytest.approx((37.32005, 127.09005))
    assert reason == ""


def test_coordinate_audit_rejects_centroids_and_distant_candidates():
    assert validated_center([], "41465")[0] is None
    assert validated_center([(36.0, 127.0)], "41465")[0] is None
    assert validated_center([(37.32, 127.09), (37.34, 127.09)], "41465")[0] is None
