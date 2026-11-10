'AC25.5.1 EPIC-025'; from __future__ import annotations; import ast; from pathlib import Path; ROUTERS_DIR = Path(__file__).resolve().parents[2] / 'src' / 'routers'; _router_module_files = lambda: sorted((p for p in ROUTERS_DIR.glob('*.py') if p.name != '__init__.py'))
def test_AC25_5_1_no_router_imports_another_router() -> None:
    'AC-meta.router.1'; offenders: list[str] = []
    for path in _router_module_files(): tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path)); [((offenders.append(f'{path.name}:{node.lineno} -> from {node.module} import ...') if node.module != 'src.routers' else None) if node.module == 'src.routers' or node.module.startswith('src.routers.') else None) if isinstance(node, ast.ImportFrom) and node.module else None for node in ast.walk(tree)]
    assert not offenders, 'router-to-router imports must not exist:\n' + '\n'.join(offenders)
