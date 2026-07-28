/**
 * Auth gate — include synchronously in <head> before stylesheets when possible.
 * <html data-auth="require"> protected pages (dashboard, admin, checkout)
 * <html data-auth="guest">    login page (redirect if already signed in)
 */
(function () {
    'use strict';
    var LOGIN = '/login';
    var DASHBOARD = '/dashboard';
    var root = document.documentElement;
    var mode = root.getAttribute('data-auth');
    if (!mode) return;

    var token = localStorage.getItem('authToken') || localStorage.getItem('token');

    if (mode === 'require' && !token) {
        location.replace(LOGIN + location.search + location.hash);
        return;
    }

    if (mode === 'guest' && token) {
        location.replace(DASHBOARD);
        return;
    }

    root.classList.remove('auth-pending');
})();
