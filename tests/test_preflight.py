from activeperception import preflight

MEM = "The system has 51539607552 (3145728 pages).\n...\nSystem-wide memory free percentage: 61%\n"
GPU = (
    '"PerformanceStatistics" = {"Tiler Utilization %"=7,"Renderer Utilization %"=94,'
    '"Device Utilization %"=98,"x"=1}'
)


def _snap(**kw):
    base = {"load1": 2.0, "ncpu": 12, "mem_free_pct": 60.0, "gpu_util_pct": 10.0, "lock": None}
    return base | kw


def test_parsers():
    assert preflight.parse_mem_free(MEM) == 61.0
    assert preflight.parse_gpu_util(GPU) == 98.0
    assert preflight.parse_mem_free("") is None and preflight.parse_gpu_util("") is None


def test_problems():
    assert preflight.problems(_snap()) == []
    assert preflight.problems(_snap(gpu_util_pct=98.0)) == []  # GPU only matters with --gpu
    assert preflight.problems(_snap(gpu_util_pct=98.0), gpu=True)[0].startswith("Apple GPU busy")
    assert preflight.problems(_snap(load1=7.0))[0].startswith("CPU busy")
    assert preflight.problems(_snap(mem_free_pct=20.0))[0].startswith("memory low")
    assert preflight.problems(_snap(lock="pid=1"))[0].startswith("Mac heavy lock held")
    assert preflight.problems(_snap(mem_free_pct=None, gpu_util_pct=None), gpu=True) == []


def test_snapshot_runs_on_this_machine():
    s = preflight.snapshot()
    assert s["ncpu"] >= 1 and s["load1"] >= 0 and isinstance(s["top"], list)
