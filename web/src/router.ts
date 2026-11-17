import { createRouter, createWebHistory } from "vue-router";

import { session } from "./session";

declare module "vue-router" {
  interface RouteMeta {
    public?: boolean;
    perm?: string;
    title?: string;
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true, title: "Вход" } },
    { path: "/register", component: () => import("./views/RegisterView.vue"), meta: { public: true, title: "Регистрация" } },
    { path: "/forgot-password", component: () => import("./views/ForgotView.vue"), meta: { public: true, title: "Восстановление пароля" } },
    { path: "/reset-password", component: () => import("./views/ResetView.vue"), meta: { public: true, title: "Новый пароль" } },
    { path: "/", component: () => import("./views/MapView.vue"), meta: { title: "Карта офиса" } },
    { path: "/bookings", component: () => import("./views/BookingsView.vue"), meta: { title: "Брони" } },
    { path: "/bookings/:id", component: () => import("./views/BookingView.vue"), meta: { title: "Бронь" } },
    { path: "/profile", component: () => import("./views/ProfileView.vue"), meta: { title: "Профиль" } },
    { path: "/admin/editor", component: () => import("./views/admin/EditorView.vue"), meta: { perm: "floors.write", title: "Редактор этажей" } },
    { path: "/admin/users", component: () => import("./views/admin/UsersView.vue"), meta: { perm: "users.manage", title: "Пользователи" } },
    { path: "/admin/settings", component: () => import("./views/admin/SettingsView.vue"), meta: { perm: "settings.write", title: "Правила" } },
    { path: "/admin/jobs", component: () => import("./views/admin/JobsView.vue"), meta: { perm: "jobs.run", title: "Джобы" } },
    { path: "/forbidden", component: () => import("./views/ForbiddenView.vue"), meta: { title: "Нет доступа" } },
    { path: "/:rest(.*)*", component: () => import("./views/NotFoundView.vue"), meta: { public: true, title: "Не найдено" } },
  ],
});

router.beforeEach((to) => {
  if (!to.meta.public && !session.loggedIn) {
    return { path: "/login", query: to.fullPath === "/" ? {} : { next: to.fullPath } };
  }
  if (to.meta.perm && !session.can(to.meta.perm)) return { path: "/forbidden" };
  if ((to.path === "/login" || to.path === "/register") && session.loggedIn) return { path: "/" };
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · OfficeSpace` : "OfficeSpace";
});
