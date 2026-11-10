'EPIC-023'; from __future__ import annotations; import src.llm.extension.factory as factory
def test_usage_meter_is_a_process_singleton() -> None: 'AC-llm.4.7'; factory._usage_meter = None; first = factory.get_usage_meter(); second = factory.get_usage_meter(); assert first is second
