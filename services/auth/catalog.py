"""Каталог прав и ролей. При старте сервиса досоздаётся в БД; токен несёт список прав роли."""

PERMISSIONS = {
    "bookings.create": "Создавать свои брони",
    "bookings.read_all": "Видеть брони всех сотрудников",
    "bookings.cancel_any": "Отменять чужие брони",
    "floors.write": "Создавать и менять этажи",
    "resources.write": "Создавать и менять переговорки и рабочие места",
    "settings.write": "Менять правила бронирования",
    "jobs.run": "Запускать служебные джобы",
    "users.manage": "Управлять пользователями и ролями",
}

ROLES = {
    "employee": ("Сотрудник", ["bookings.create"]),
    "manager": ("Руководитель", ["bookings.create", "bookings.read_all", "bookings.cancel_any"]),
    "facility": ("АХО", ["bookings.create", "floors.write", "resources.write", "settings.write"]),
    "admin": ("Администратор", list(PERMISSIONS)),
}

DEFAULT_ROLE = "employee"
