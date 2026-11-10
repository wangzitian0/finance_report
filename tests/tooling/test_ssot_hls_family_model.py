'AC14.1.18 EPIC-014'; from __future__ import annotations; import re; from pathlib import Path; from common.meta.extension import governance_report; from common.meta.extension.check_manifest import load_computed_concepts; ROOT = Path(__file__).resolve().parents[2]; FR_EPIC = ROOT / 'docs/project/EPIC-014.ttd-transformation.md'; FR_MANIFEST = ROOT / 'common/meta/data/MANIFEST.yaml'; ISSUE_LINKS = ('/issues/821', '/issues/822', '/issues/823', '/issues/824'); FAMILY_SECTION_HEADING = '## SSOT HLS Family Model'; FAMILY_ROW = re.compile('^\\|\\s*`(?P<family>[a-z0-9_]+)`\\s*\\|')
def _read(path: Path) -> str:
    if not path.exists(): raise FileNotFoundError(f'Required SSOT file not found: {path}.')
    return path.read_text(encoding='utf-8')
def _family_section(text: str) -> str: assert FAMILY_SECTION_HEADING in text, f"missing '{FAMILY_SECTION_HEADING}' section"; after = text.split(FAMILY_SECTION_HEADING, 1)[1]; return after.split('\n## ', 1)[0]
def _declared_families(text: str) -> list[str]:
    section = _family_section(text); families: list[str] = []
    for line in section.splitlines(): match = FAMILY_ROW.match(line.strip()); families.append(match.group('family')) if match else None
    return families
def _entries_inferred_families(raw_entries: dict) -> set[str]:
    families: set[str] = set()
    for (key, raw) in raw_entries.items(): entry = governance_report.GovernanceEntry(key=str(key), owner=str(raw.get('owner') or ''), description=str(raw.get('description') or ''), cross_refs=(), proofs=(), family=str(raw['family']) if raw.get('family') else None, kind=str(raw['kind']) if raw.get('kind') else None, parent=None, authority=None); families.add(governance_report._infer_family(entry))
    return families
_backticked_tokens = lambda text: set(re.findall('`([a-z0-9_]+)`', text))
def _family_member_counts(section: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in section.splitlines():
        stripped = line.strip()
        if not FAMILY_ROW.match(stripped): continue
        cells = [cell.strip() for cell in stripped.strip('|').split('|')]; member_cell = cells[-1]
        for token in re.findall('`([a-z0-9_]+)`', member_cell): counts[token] = counts.get(token, 0) + 1
    return counts
def _family_map_coverage(section: str, inferred: set[str]) -> set[str]: counts = _family_member_counts(section); return {fam for fam in inferred if counts.get(fam, 0) != 1}
def test_AC14_1_18_fr_hls_family_model_is_documented_and_consistent() -> None:
    'AC-meta.ssot-governance.7 EPIC-014'; text = _read(FR_EPIC); families = _declared_families(text); assert 6 <= len(families) <= 8, f'FR HLS model must declare 6-8 families, found {len(families)}: {families}'; assert len(families) == len(set(families)), 'FR families must be unique'; section = _family_section(text); assert 'concept' in section.lower(), 'family model must state concept boundary'; assert 'clause' in section.lower(), 'family model must state clause boundary'; assert 'MANIFEST.yaml' in section, 'family model must reference MANIFEST.yaml'; inferred = _entries_inferred_families(load_computed_concepts(ROOT, FR_MANIFEST)); uncovered = _family_map_coverage(section, inferred); assert not uncovered, f'FR family map must bind each manifest-inferred family to exactly one declared family; offending (missing or duplicated): {sorted(uncovered)}'; 'AC14.1.18'; 'AC14.1.18'; _m1_text = _read(FR_EPIC)
    for _m1_link in ISSUE_LINKS: assert _m1_link in _m1_text, f'{FR_EPIC.name} must link {_m1_link}'
    'AC14.1.18'; 'AC14.1.18'; _m2_report = governance_report.build_report(ROOT, include_infra2=False); assert _m2_report['overall']['errors'] == []
