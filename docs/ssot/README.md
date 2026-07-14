# SSOT Index (retired)

Every prose and gate-data document formerly here moved into its owning
package (`common/<pkg>/` for prose, `common/<pkg>/data/` for machine-read
JSON/YAML) per [#1822](https://github.com/wangzitian0/finance_report/issues/1822)
(SSOT dissolution, Package-ization 3/4) — the concept-ownership registry,
[MANIFEST.yaml](./MANIFEST.yaml), still lists every concept's current owner
and is the place to look up where a fact now lives.
[epic-residue-baseline.json](./epic-residue-baseline.json) is the only other
file that still lives here; it retires with the EPIC tables themselves in
[#1823](https://github.com/wangzitian0/finance_report/issues/1823), at which
point this directory and `MANIFEST.yaml` are removed too.
