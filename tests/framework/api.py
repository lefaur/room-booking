"""Тонкие клиенты сервисов: только пути и тела запросов. Проверки остаются в шагах."""
from requests import Response

from framework.http import ApiClient


class AuthApi:
    prefix = "/api/auth"

    def __init__(self, http: ApiClient):
        self.http = http

    def _call(self, method: str, path: str, **kwargs) -> Response:
        return self.http.request(method, self.prefix + path, **kwargs)

    def register(self, email: str, password: str, full_name: str) -> Response:
        return self._call("POST", "/register", json_body={"email": email, "password": password, "full_name": full_name})

    def login(self, email: str, password: str) -> Response:
        return self._call("POST", "/login", json_body={"email": email, "password": password})

    def refresh(self, refresh_token: str) -> Response:
        return self._call("POST", "/refresh", json_body={"refresh_token": refresh_token})

    def logout(self, refresh_token: str) -> Response:
        return self._call("POST", "/logout", json_body={"refresh_token": refresh_token})

    def me(self, token: str) -> Response:
        return self._call("GET", "/me", token=token)

    def list_users(self, token: str, **params) -> Response:
        return self._call("GET", "/users", token=token, params=params)

    def patch_user(self, token: str, user_id: int, **changes) -> Response:
        return self._call("PATCH", f"/users/{user_id}", token=token, json_body=changes)

    def forgot_password(self, email: str) -> Response:
        return self._call("POST", "/password/forgot", json_body={"email": email})

    def reset_password(self, token: str, new_password: str) -> Response:
        return self._call("POST", "/password/reset", json_body={"token": token, "new_password": new_password})


class BookingApi:
    prefix = "/api/booking"

    def __init__(self, http: ApiClient):
        self.http = http

    def _call(self, method: str, path: str, **kwargs) -> Response:
        return self.http.request(method, self.prefix + path, **kwargs)

    # этажи и ресурсы
    def create_floor(self, token: str, **body) -> Response:
        return self._call("POST", "/floors", token=token, json_body=body)

    def floor_map(self, token: str, floor_id: int, at: str | None = None) -> Response:
        return self._call("GET", f"/floors/{floor_id}/map", token=token, params={"at": at} if at else None)

    def create_resource(self, token: str, **body) -> Response:
        return self._call("POST", "/resources", token=token, json_body=body)

    def get_resource(self, token: str, resource_id: int) -> Response:
        return self._call("GET", f"/resources/{resource_id}", token=token)

    def list_resources(self, token: str, **params) -> Response:
        return self._call("GET", "/resources", token=token, params=params)

    def patch_resource(self, token: str, resource_id: int, **changes) -> Response:
        return self._call("PATCH", f"/resources/{resource_id}", token=token, json_body=changes)

    # брони
    def create_booking(self, token: str, **body) -> Response:
        return self._call("POST", "/bookings", token=token, json_body=body)

    def list_bookings(self, token: str, **params) -> Response:
        return self._call("GET", "/bookings", token=token, params=params)

    def get_booking(self, token: str, booking_id: int) -> Response:
        return self._call("GET", f"/bookings/{booking_id}", token=token)

    def confirm(self, token: str, booking_id: int) -> Response:
        return self._call("POST", f"/bookings/{booking_id}/confirm", token=token)

    def cancel(self, token: str, booking_id: int) -> Response:
        return self._call("POST", f"/bookings/{booking_id}/cancel", token=token)

    def check_in(self, token: str, booking_id: int) -> Response:
        return self._call("POST", f"/bookings/{booking_id}/check-in", token=token)

    def calendar(self, token: str, date_from: str, date_to: str) -> Response:
        return self._call("GET", "/calendar", token=token, params={"date_from": date_from, "date_to": date_to})

    # правила и джобы
    def get_settings(self, token: str) -> Response:
        return self._call("GET", "/settings", token=token)

    def put_settings(self, token: str, **values) -> Response:
        return self._call("PUT", "/settings", token=token, json_body=values)

    def run_expire_job(self, token: str) -> Response:
        return self._call("POST", "/jobs/expire-pending", token=token)


class TelegramLinkApi:
    prefix = "/api/tg"

    def __init__(self, http: ApiClient):
        self.http = http

    def create_code(self, token: str) -> Response:
        return self.http.request("POST", self.prefix + "/link-code", token=token)

    def get_link(self, token: str) -> Response:
        return self.http.request("GET", self.prefix + "/link", token=token)

    def unlink(self, token: str) -> Response:
        return self.http.request("DELETE", self.prefix + "/link", token=token)


class SchedulerApi:
    prefix = "/api/scheduler"

    def __init__(self, http: ApiClient):
        self.http = http

    def jobs(self, token: str) -> Response:
        return self.http.request("GET", self.prefix + "/jobs", token=token)

    def run(self, token: str, job: str) -> Response:
        return self.http.request("POST", f"{self.prefix}/jobs/{job}/run", token=token)
