/** Время офиса. Браузер может быть в любом часовом поясе, а брони считаются по Москве. */
export const OFFICE_TZ = "Europe/Moscow";

const dateFmt = new Intl.DateTimeFormat("en-CA", { timeZone: OFFICE_TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const timeFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: OFFICE_TZ, hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("ru-RU", { timeZone: OFFICE_TZ, day: "numeric", month: "long", weekday: "short" });

/** «2026-11-18» — сегодняшняя дата в офисе. */
export function officeToday(): string {
  return dateFmt.format(new Date());
}

export function addDays(day: string, days: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** Смещение офиса на указанную дату, например «+03:00». */
function officeOffset(day: string): string {
  const name = new Intl.DateTimeFormat("en-US", { timeZone: OFFICE_TZ, timeZoneName: "longOffset" })
    .formatToParts(new Date(`${day}T12:00:00Z`))
    .find((p) => p.type === "timeZoneName")?.value;
  const offset = name?.replace("GMT", "") ?? "";
  return offset === "" ? "+00:00" : offset;
}

/** Дата и время офиса → ISO со смещением: «2026-11-18T10:00:00+03:00». */
export function officeIso(day: string, hhmm: string): string {
  return `${day}T${hhmm}:00${officeOffset(day)}`;
}

export function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function formatDay(iso: string): string {
  return dayFmt.format(new Date(iso));
}

export function officeDate(iso: string): string {
  return dateFmt.format(new Date(iso));
}

/** Интервал брони по-человечески: «18 нояб., ср 10:00–11:00» или «18–20 нояб.» для мест. */
export function formatInterval(startIso: string, endIso: string, kind: "room" | "desk"): string {
  if (kind === "room") return `${formatDay(startIso)}, ${formatTime(startIso)}–${formatTime(endIso)}`;
  const last = new Date(new Date(endIso).getTime() - 1);
  const first = formatDay(startIso);
  const lastDay = formatDay(last.toISOString());
  return first === lastDay ? first : `${first} — ${lastDay}`;
}

/** Слоты по 30 минут с 08:00 до 21:00. */
export const SLOTS: string[] = Array.from({ length: 27 }, (_, i) => {
  const minutes = 8 * 60 + i * 30;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
});
