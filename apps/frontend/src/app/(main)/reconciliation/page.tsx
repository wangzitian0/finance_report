import ReconciliationWorkbench from "@/components/reconciliation/Workbench";
import { AuditBackLink } from "@/components/ui/SmartBackLink";

export default function ReconciliationPage() {
  return (
    <>
      <div className="px-6 pt-6">
        <AuditBackLink />
      </div>
      <ReconciliationWorkbench />
    </>
  );
}
