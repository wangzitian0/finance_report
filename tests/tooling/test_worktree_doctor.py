'AC-testing.preflight.4'; from __future__ import annotations; import pytest; from common.testing.extension import worktree_doctor
def test_AC_testing_preflight_4_worktree_doctor_audit_and_prune():
    'AC-testing.preflight.4'; porcelain_output = 'worktree /repo/main\nHEAD 11111111\nbranch refs/heads/main\n\nworktree /repo/wt_merged\nHEAD 22222222\nbranch refs/heads/feature_merged\n\nworktree /repo/wt_active\nHEAD 33333333\nbranch refs/heads/feature_active\n'
    def fake_runner(cmd, cwd=None):
        cmd_str = ' '.join(cmd)
        if 'worktree list --porcelain' in cmd_str: return (0, porcelain_output)
        if 'status --porcelain' in cmd_str:
            if '/repo/main' in str(cwd): return (0, 'M  apps/frontend/src/lib/api-types.ts\nMM apps/backend/src/service.py\nA  apps/frontend/src/new.ts\n M docs/readme.md\n?? untracked.txt\n')
            return (0, '')
        if 'lsof' in cmd_str: return (0, '')
        if 'merge-base' in cmd_str:
            if '22222222' in cmd_str: return (0, '')
            return (1, '')
        if 'worktree remove' in cmd_str: return (0, '')
        return (0, '')
    def fake_pr_resolver(branch: str):
        if branch == 'feature_merged': return {'number': 101, 'state': 'MERGED'}
        if branch == 'feature_active': return {'number': 102, 'state': 'OPEN'}
        return None
    report = worktree_doctor.audit_worktrees(runner=fake_runner, pr_resolver=fake_pr_resolver, path_exists=lambda p: True, main_root='/repo/main'); expected_staged = ['M  apps/frontend/src/lib/api-types.ts', 'MM apps/backend/src/service.py', 'A  apps/frontend/src/new.ts']; assert report.staged_leakage == expected_staged; merged_wt = next((w for w in report.worktrees if w.path == '/repo/wt_merged')); assert merged_wt.is_orphan is True; assert merged_wt.safe_to_prune is True; assert merged_wt.locks_unknown is False; active_wt = next((w for w in report.worktrees if w.path == '/repo/wt_active')); assert active_wt.is_orphan is False; assert active_wt.safe_to_prune is False; removed = worktree_doctor.prune_worktrees(report, runner=fake_runner, dry_run=False); assert removed == ['/repo/wt_merged']
def test_AC_testing_preflight_4_lsof_error_blocks_prune():
    'AC-testing.preflight.4'; porcelain_output = 'worktree /repo/main\nHEAD 11111111\nbranch refs/heads/main\n\nworktree /repo/wt_merged\nHEAD 22222222\nbranch refs/heads/feature_merged\n'
    def fake_runner_lsof_fail(cmd, cwd=None):
        cmd_str = ' '.join(cmd)
        if 'worktree list --porcelain' in cmd_str: return (0, porcelain_output)
        if 'status --porcelain' in cmd_str: return (0, '')
        if 'lsof' in cmd_str: return (127, 'lsof: command not found')
        if 'merge-base' in cmd_str: return (0, '')
        return (0, '')
    report = worktree_doctor.audit_worktrees(runner=fake_runner_lsof_fail, pr_resolver=lambda b: {'number': 101, 'state': 'MERGED'}, path_exists=lambda p: True, main_root='/repo/main'); merged_wt = next((w for w in report.worktrees if w.path == '/repo/wt_merged')); assert merged_wt.locks_unknown is True; assert merged_wt.is_orphan is False; assert merged_wt.safe_to_prune is False
def test_AC_testing_preflight_4_doctor_report_properties_and_porcelain_parsing(): 'AC-testing.preflight.4'; raw = 'worktree /repo/bare\nbare\n\nworktree /repo/detached\nHEAD dddddddd\ndetached\n\n'; parsed = worktree_doctor.parse_worktree_porcelain(raw); assert len(parsed) == 2; assert parsed[0].get('bare') == 'true'; assert parsed[1].get('branch') == 'detached'; report = worktree_doctor.DoctorReport(worktrees=[worktree_doctor.WorktreeInfo(path='/p1', head='h1', branch='b1', is_orphan=True), worktree_doctor.WorktreeInfo(path='/p2', head='h2', branch='b2', is_orphan=False)]); assert len(report.orphans) == 1; assert len(report.active) == 1
def test_AC_testing_preflight_4_cli_flags_and_formatting(capsys):
    'AC-testing.preflight.4'; import tools.worktree_doctor as tools_shim; porcelain_output = 'worktree /repo/main\nHEAD 11111111\nbranch refs/heads/main\n\nworktree /repo/wt_merged\nHEAD 22222222\nbranch refs/heads/feature_merged\n'
    def fake_runner(cmd, cwd=None):
        cmd_str = ' '.join(cmd)
        if 'worktree list --porcelain' in cmd_str: return (0, porcelain_output)
        if 'status --porcelain' in cmd_str: return (0, '')
        if 'lsof' in cmd_str: return (1, '')
        if 'merge-base' in cmd_str: return (0, '')
        if 'worktree remove' in cmd_str: return (0, '')
        return (0, '')
    fake_pr = lambda b: {'number': 101, 'state': 'MERGED'}; rc = worktree_doctor.run_doctor(['--json'], runner=fake_runner, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 0; out_json = capsys.readouterr().out; assert out_json.find('"safe_to_prune": true') != -1; rc = worktree_doctor.run_doctor([], runner=fake_runner, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 0; out_text = capsys.readouterr().out; assert out_text.find('=== Worktree Doctor Audit ===') != -1; assert out_text.find('[ORPHAN]') != -1; rc = worktree_doctor.run_doctor(['--dry-run'], runner=fake_runner, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 0; out_dry = capsys.readouterr().out; assert out_dry.find('Would prune 1 orphan worktree(s)') != -1; rc = worktree_doctor.run_doctor(['--prune'], runner=fake_runner, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 0; out_prune = capsys.readouterr().out; assert out_prune.find('Pruned 1 orphan worktree(s)') != -1; rc = worktree_doctor.run_doctor(['--check'], runner=fake_runner, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 1
    def fake_runner_with_leak(cmd, cwd=None):
        cmd_str = ' '.join(cmd)
        if 'status --porcelain' in cmd_str and '/repo/main' in str(cwd): return (0, 'M  apps/frontend/src/lib/api-types.ts\n')
        return fake_runner(cmd, cwd)
    rc = worktree_doctor.run_doctor([], runner=fake_runner_with_leak, pr_resolver=fake_pr, path_exists=lambda p: True); assert rc == 0; out_leak = capsys.readouterr().out; assert out_leak.find('STAGED INDEX LEAKAGE DETECTED IN MAIN') != -1
    with pytest.raises(SystemExit) as exc: worktree_doctor.main(['--help'])
    assert exc.value.code == 0; assert tools_shim.main is worktree_doctor.main
def test_AC_testing_preflight_4_runner_and_pr_resolver_edge_cases(monkeypatch):
    'AC-testing.preflight.4'; import runpy; monkeypatch.setattr(worktree_doctor, 'main', lambda argv=None: 0)
    with pytest.raises(SystemExit) as exc: runpy.run_path('tools/worktree_doctor.py', run_name='__main__')
    assert exc.value.code == 0; rc, out = worktree_doctor._default_runner(['nonexistent-command-xyz-987']); assert rc == 127; assert worktree_doctor._default_pr_resolver('main') is None; assert worktree_doctor._default_pr_resolver('refs/heads/main') is None; assert worktree_doctor._default_pr_resolver('detached') is None; assert worktree_doctor._default_pr_resolver('HEAD') is None
def test_AC_testing_preflight_5_worktree_doctor_recognizes_squash_merged_prs():
    'AC-testing.preflight.5'; porcelain_output = 'worktree /repo/main\nHEAD 11111111\nbranch refs/heads/main\n\nworktree /repo/wt_squash_merged\nHEAD 33333333\nbranch refs/heads/feature_squash_merged\n'
    def fake_runner_squash(cmd, cwd=None):
        cmd_str = ' '.join(cmd)
        if 'worktree list --porcelain' in cmd_str: return (0, porcelain_output)
        if 'status --porcelain' in cmd_str: return (0, '')
        if 'lsof' in cmd_str: return (1, '')
        if 'merge-base' in cmd_str: return (1, '')
        if 'worktree remove' in cmd_str: return (0, '')
        if 'branch -D' in cmd_str: return (0, '')
        return (0, '')
    report = worktree_doctor.audit_worktrees(runner=fake_runner_squash, pr_resolver=lambda b: {'number': 105, 'state': 'MERGED'}, path_exists=lambda p: True, main_root='/repo/main'); squash_wt = next((w for w in report.worktrees if w.path == '/repo/wt_squash_merged')); assert squash_wt.is_orphan is True; assert squash_wt.safe_to_prune is True; removed = worktree_doctor.prune_worktrees(report, runner=fake_runner_squash, dry_run=False); assert removed == ['/repo/wt_squash_merged']
