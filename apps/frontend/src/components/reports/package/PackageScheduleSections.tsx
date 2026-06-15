import type {
  AnnualizedIncomeScheduleResponse,
  FrameworkPolicyResult,
  PersonalReportPackageContractResponse,
  PersonalReportPackageNotesResponse,
} from "@/lib/types";

import { formatScheduleCurrency, sectionAnchorId } from "./shared";

export function PackageSectionCards({
  sections,
}: {
  sections: PersonalReportPackageContractResponse["sections"];
}) {
  return (
    <div className="grid lg:grid-cols-2 gap-4 mb-6">
      {sections.map((section) => (
        <section
          key={section.section_id}
          id={sectionAnchorId(section.section_id)}
          className="card p-5"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold">{section.label}</h2>
            </div>
            <span className="badge badge-muted">{section.status}</span>
          </div>
          <dl className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Owner</dt>
              <dd className="font-medium">{section.owner_epic}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Endpoint</dt>
              <dd className="font-mono text-xs text-right">
                {section.source_endpoint}
              </dd>
            </div>
            {section.blocking_issue ? (
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Follow-up</dt>
                <dd className="font-medium">{section.blocking_issue}</dd>
              </div>
            ) : null}
          </dl>
        </section>
      ))}
    </div>
  );
}

export function PackageAnnualizedScheduleSection({
  schedule,
}: {
  schedule: AnnualizedIncomeScheduleResponse;
}) {
  return (
    <section id="package-annualized-income-detail" className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Annualized Income Schedule</h2>
        </div>
        <span className="badge badge-muted">
          {schedule.trailing_period_days} days
        </span>
      </div>
      <div className="mt-4 grid md:grid-cols-4 gap-3">
        <div>
          <p className="text-xs text-muted">Total</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_total,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Salary</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_salary,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Bonus</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_bonus,
              schedule.income.currency,
            )}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Dividend</p>
          <p className="mt-1 font-semibold">
            {formatScheduleCurrency(
              schedule.income.annualized_dividend,
              schedule.income.currency,
            )}
          </p>
        </div>
      </div>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        <div>
          <h3 className="text-sm font-semibold">Restricted Holdings</h3>
          <div className="mt-3 space-y-2">
            {schedule.restricted_holdings.map((holding) => (
              <div
                key={`${holding.compensation_type}:${holding.ticker}`}
                className="border border-[var(--border)] rounded p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{holding.ticker}</p>
                    <p className="text-xs text-muted">
                      {holding.compensation_type}
                    </p>
                  </div>
                  <p className="font-semibold">
                    {formatScheduleCurrency(
                      holding.fair_value,
                      holding.currency,
                    )}
                  </p>
                </div>
                <dl className="mt-3 space-y-1 text-xs">
                  {holding.vesting_schedule ? (
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted">Vesting</dt>
                      <dd>{holding.vesting_schedule}</dd>
                    </div>
                  ) : null}
                  {holding.unlock_date ? (
                    <div className="flex justify-between gap-3">
                      <dt className="text-muted">Unlock</dt>
                      <dd>{holding.unlock_date}</dd>
                    </div>
                  ) : null}
                </dl>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Net Worth Treatment</h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Liquid Default</dt>
              <dd className="font-mono text-xs text-right">
                {schedule.net_worth_treatment.liquid_net_worth_default}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Restricted Basis</dt>
              <dd className="font-mono text-xs text-right">
                {schedule.net_worth_treatment.restricted_wealth_basis}
              </dd>
            </div>
          </dl>
          <ul className="mt-4 space-y-1 text-sm text-muted">
            {schedule.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function PackageNotesSection({
  notes,
}: {
  notes: PersonalReportPackageNotesResponse;
}) {
  return (
    <section id="package-notes-detail" className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{notes.label}</h2>
        </div>
        <span className="badge badge-muted">{notes.status}</span>
      </div>
      <p className="mt-4 text-sm text-muted">
        {notes.non_compliance_statement}
      </p>
      <div className="mt-5 grid lg:grid-cols-2 gap-4">
        {notes.notes.map((note) => (
          <article
            key={note.note_id}
            className="border border-[var(--border)] rounded p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{note.label}</p>
                <p className="text-xs font-mono text-muted mt-1">
                  {note.note_id}
                </p>
              </div>
              <span className="badge badge-muted">{note.owner_epic}</span>
            </div>
            <p className="mt-3 text-sm text-muted">{note.disclosure}</p>
            <dl className="mt-3 space-y-1 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Basis</dt>
                <dd className="font-mono text-right">{note.basis}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Source</dt>
                <dd className="font-mono text-right">{note.source_state}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}

export function PackageExportContractSection({
  contract,
  policy,
  evidenceReferences,
}: {
  contract: PersonalReportPackageContractResponse;
  policy: FrameworkPolicyResult;
  evidenceReferences: string[];
}) {
  return (
    <section id="package-export-contract" className="card p-5">
      <h2 className="font-semibold">Export Contract</h2>
      <dl className="mt-4 space-y-2 text-sm">
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Formats</dt>
          <dd className="font-medium">
            {contract.export_contract.formats.join(", ")}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">CSV Columns</dt>
          <dd className="font-mono text-xs text-right">
            {contract.export_contract.csv_columns.join(", ")}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Decimal Serialization</dt>
          <dd className="font-medium">
            {contract.period_semantics.decimal_serialization}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Framework Policy Result</dt>
          <dd className="max-w-md break-words font-mono text-xs text-right">
            {policy.result_id}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Framework Policy Matrix Version</dt>
          <dd className="font-medium">{policy.matrix_version}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted">Evidence Bundle References</dt>
          <dd className="max-w-md break-words font-mono text-xs text-right">
            {evidenceReferences.join(", ") || "none"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
