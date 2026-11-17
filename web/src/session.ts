/** Сессия пользователя: токены в localStorage, роль и права — из claims access-токена. */
import { reactive } from "vue";

import type { User } from "./types";

const ACCESS_KEY = "officespace.access";
const REFRESH_KEY = "officespace.refresh";

interface Claims {
  sub: string;
  email: string;
  role: string;
  perms: string[];
}

function decode(token: string | null): Claims | null {
  if (!token) return null;
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(part)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join(""),
    );
    return JSON.parse(json) as Claims;
  } catch {
    return null;
  }
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* приватный режим: сессия живёт до перезагрузки */
  }
}

export const session = reactive({
  accessToken: read(ACCESS_KEY),
  refreshToken: read(REFRESH_KEY),
  user: null as User | null,

  get claims(): Claims | null {
    return decode(this.accessToken);
  },
  get loggedIn(): boolean {
    return this.accessToken !== null;
  },
  get role(): string {
    return this.claims?.role ?? "";
  },
  can(perm: string): boolean {
    return this.claims?.perms.includes(perm) ?? false;
  },
  setTokens(access: string, refresh: string): void {
    this.accessToken = access;
    this.refreshToken = refresh;
    write(ACCESS_KEY, access);
    write(REFRESH_KEY, refresh);
  },
  clear(): void {
    this.accessToken = null;
    this.refreshToken = null;
    this.user = null;
    write(ACCESS_KEY, null);
    write(REFRESH_KEY, null);
  },
});
