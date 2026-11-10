'AC-llm.banned-models.1'; import re; import subprocess; from pathlib import Path; ROOT = Path(__file__).resolve().parents[2]; BANNED = re.compile('glm-?4\\.?6v', re.IGNORECASE); RECORDED_DATA = 'common/testing/fixtures/llm_cassettes/ground_truth/'; THIS_FILE = 'tests/tooling/test_banned_models.py'; TEXT_SUFFIXES = {'.py', '.md', '.yml', '.yaml', '.json', '.toml', '.txt', '.sh', '.ts', '.tsx', '.js', '.mjs', '.example', '.ctmpl', '.hcl'}
def _tracked_text_files() -> list[str]: out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True, text=True).stdout; return [p for p in out.split('\x00') if p and (Path(p).suffix in TEXT_SUFFIXES or p.endswith('.env.example')) and (p != THIS_FILE)]
def _hits() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for rel in _tracked_text_files():
        try: lines = (ROOT / rel).read_text(encoding='utf-8').splitlines()
        except (UnicodeDecodeError, OSError): continue
        numbers = [n for n, line in enumerate(lines, 1) if BANNED.search(line)]
        if numbers: found[rel] = numbers
    return found
def test_AC_llm_banned_models_1_no_tracked_file_names_glm_4_6v():
    hits = {p: n for p, n in _hits().items() if not p.startswith(RECORDED_DATA)}; assert not hits, f'glm-4.6v is banned; remove it from: {hits}'; _m1_exempt = {_m1_p for _m1_p in _hits() if _m1_p.startswith(RECORDED_DATA)}; assert all((_m1_p.endswith('.truth.json') for _m1_p in _m1_exempt)), sorted(_m1_exempt); _m2_files = _tracked_text_files(); assert len(_m2_files) > 500, len(_m2_files)
    for _m2_expected in ('common/extraction/record_hf_cassettes.py', 'apps/backend/src/config.py', '.github/workflows/ci.yml'): assert _m2_expected in _m2_files, _m2_expected
    for _m3_spelling in ('glm-4.6v', 'GLM-4.6V', 'glm-4.6V', 'glm4.6v', 'zai/glm-4.6v', 'openai/GLM-4.6V'): assert BANNED.search(_m3_spelling), _m3_spelling
    for _m3_other in ('glm-4.5v', 'glm-5.3-flash', 'glm-5.2', 'glm-4.6', 'test-vision-model', 'gpt-4o'): assert not BANNED.search(_m3_other), _m3_other
