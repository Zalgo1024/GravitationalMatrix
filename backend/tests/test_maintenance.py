"""即时导出物磁盘回收（maintenance）测试。"""
import os
import time

import pytest

from app import maintenance
from app.maintenance import cleanup_stale_exports, maybe_cleanup


def _make_dir(path: str, *, age_days: float) -> str:
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "sample.txt"), "w", encoding="utf-8") as fh:
        fh.write("x")
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))
    return path


@pytest.fixture()
def generated_dir(monkeypatch):
    """独立的临时 generated 目录（不动全局 conftest 的隔离目录）。"""
    import tempfile
    from pathlib import Path

    from app.settings import settings

    base = Path(tempfile.mkdtemp(prefix="maint_test_"))
    monkeypatch.setattr(settings, "generated_dir", str(base))
    yield str(base)


def test_stale_bundle_and_pptx_removed(generated_dir):
    stale_bundle = _make_dir(os.path.join(generated_dir, "bundle_taskA"), age_days=8)
    stale_pptx = _make_dir(os.path.join(generated_dir, "pptx_taskB"), age_days=8)
    fresh_bundle = _make_dir(os.path.join(generated_dir, "bundle_taskC"), age_days=1)

    removed = cleanup_stale_exports()

    assert removed == 2
    assert not os.path.exists(stale_bundle)
    assert not os.path.exists(stale_pptx)
    assert os.path.exists(fresh_bundle)


def test_engine_outputs_never_touched(generated_dir):
    """引擎主产物目录（非 bundle_/pptx_ 前缀）即使超龄也绝不动。"""
    engine_out = _make_dir(os.path.join(generated_dir, "某事件报告_20260916"), age_days=30)
    stray_file = os.path.join(generated_dir, "bundle_stale.zip")
    with open(stray_file, "w", encoding="utf-8") as fh:
        fh.write("x")
    old = time.time() - 30 * 86400
    os.utime(stray_file, (old, old))

    removed = cleanup_stale_exports()

    assert removed == 0
    assert os.path.exists(engine_out)  # 目录：主产物，不碰
    assert os.path.exists(stray_file)  # 文件：不在清理范围（只清目录）


def test_maybe_cleanup_throttled(generated_dir, monkeypatch):
    _make_dir(os.path.join(generated_dir, "bundle_taskD"), age_days=8)
    monkeypatch.setattr(maintenance, "_last_cleanup_at", None)

    assert maybe_cleanup() == 1  # 首次执行
    _make_dir(os.path.join(generated_dir, "bundle_taskE"), age_days=8)
    assert maybe_cleanup() == 0  # 24h 内节流跳过

    monkeypatch.setattr(maintenance, "_last_cleanup_at", None)
    assert maybe_cleanup() == 1  # 重置节流后再次执行
