import { displayStatus } from "../lib/format";

export function StatusBadge({
  status,
  text,
}: {
  status: string;
  text?: string;
}) {
  const tone =
    status === "success" || status === "ok" || status === "saved"
      ? "good"
      : status === "failed" || status.endsWith("_failed")
        ? "bad"
        : status === "degraded" || status === "empty"
          ? "warn"
          : "muted";
  return (
    <span className={`status-badge status-${tone}`}>
      {text ?? displayStatus(status)}
    </span>
  );
}
