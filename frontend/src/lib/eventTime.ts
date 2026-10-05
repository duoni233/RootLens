const DEMO_DATE = "2026-09-01";

function validTime(hour: string, minute: string): string | null {
  const h = Number(hour);
  const m = Number(minute);
  if (h > 23 || m > 59) return null;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function suggestDemoEventTime(message: string): string {
  const dates = [
    ...new Set(
      [...message.matchAll(/(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/g)].map(
        ([, year, month, day]) =>
          `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`,
      ),
    ),
  ];
  if (dates.length > 1) return "";

  const timePatterns = [
    /(?:从|自)\s*(\d{1,2}):(\d{2})\s*(?:开始|起|出现)?/g,
    /(\d{1,2}):(\d{2})\s*(?:开始|出现|发生)/g,
    /(\d{1,2}):(\d{2})/g,
  ];
  for (const pattern of timePatterns) {
    const times = [
      ...new Set(
        [...message.matchAll(pattern)]
          .map(([, hour, minute]) => validTime(hour, minute))
          .filter((value): value is string => value !== null),
      ),
    ];
    if (times.length === 1) return `${dates[0] ?? DEMO_DATE}T${times[0]}`;
    if (times.length > 1) return "";
  }
  return "";
}
