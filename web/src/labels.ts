import type { BookingStatus } from "./types";

export const STATUS_LABELS: Record<BookingStatus, string> = {
  pending: "Ждёт подтверждения",
  confirmed: "Подтверждена",
  checked_in: "Вы на месте",
  cancelled: "Отменена",
  expired: "Не подтверждена вовремя",
  no_show: "Неявка",
};

export const ACTIVE_STATUSES: BookingStatus[] = ["pending", "confirmed", "checked_in"];

export const EQUIPMENT_LABELS: Record<string, string> = {
  projector: "проектор",
  whiteboard: "доска",
  tv: "телевизор",
  videoconf: "видеосвязь",
};

export const ROLE_LABELS: Record<string, string> = {
  employee: "Сотрудник",
  manager: "Руководитель",
  facility: "АХО",
  admin: "Администратор",
};

export const SETTING_LABELS: Record<string, string> = {
  max_active_bookings_per_user: "Активных броней на сотрудника",
  confirm_timeout_minutes: "Время на подтверждение, мин",
  max_booking_hours: "Максимум часов на переговорку",
  max_desk_days: "Максимум дней на рабочее место",
  booking_horizon_days: "Бронировать вперёд, дней",
  reminder_minutes_before: "Напоминание до начала, мин",
  checkin_open_minutes_before: "Отметка открывается до начала, мин",
  no_show_grace_minutes: "Ждём опоздавших, мин",
};
