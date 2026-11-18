from __future__ import annotations; import src.llm.extension.factory as factory
def test_usage_meter_is_a_process_singleton() -> None: factory._usage_meter = None; first = factory.get_usage_meter(); second = factory.get_usage_meter(); assert first is second
