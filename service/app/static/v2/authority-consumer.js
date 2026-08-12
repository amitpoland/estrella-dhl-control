/**
 * RBAC Slice 1 — consume /auth/me authority in the V2 shell.
 * Plain JS only. No permission catalogue. No role→permission matrix.
 * Backend PAGE_VIEW_PERMISSION / allowed_pages remain the sole authority.
 */
(function (global) {
  "use strict";

  var PAGE_ALIASES = { detail: "shipments", proforma_detail: "proforma", proforma_search: "proforma" };

  function canonPageId(pageId) {
    return PAGE_ALIASES[pageId] || pageId;
  }

  function pageIsAllowed(pageId, allowedPages) {
    var canon = canonPageId(pageId);
    if (!canon) return false;
    return Array.isArray(allowedPages) && allowedPages.indexOf(canon) >= 0;
  }

  function sanitizePage(page) {
    return String(page || "").replace(/[^a-z0-9_]/gi, "") || "dashboard";
  }

  function landingPathFromAuthority(me) {
    var surface = String((me && me.default_surface) || "v2").toLowerCase();
    var page = sanitizePage(me && me.default_page);
    if (surface === "v1") return "/dashboard/dashboard.html";
    return "/v2/" + page;
  }

  function normalizeAuthority(me) {
    me = me || {};
    var allowed = Array.isArray(me.allowed_pages) ? me.allowed_pages.slice() : [];
    var perms = Array.isArray(me.permissions) ? me.permissions.slice() : [];
    var role = me.role || "";
    var malformed = !allowed.length && !perms.length && !role;
    var defaultPage = sanitizePage(me.default_page);
    var defaultSurface = String(me.default_surface || "v2").toLowerCase();
    if (malformed) {
      defaultPage = "dashboard";
      defaultSurface = "v2";
    }
    return {
      malformed: malformed,
      allowed_pages: allowed,
      permissions: perms,
      default_page: defaultPage,
      default_surface: defaultSurface,
      role: role,
    };
  }

  function fetchAuthMe() {
    return fetch("/auth/me", { credentials: "include" }).then(function (r) {
      if (r.status === 401 || r.status === 403) {
        var err = new Error("unauthorized");
        err.status = r.status;
        throw err;
      }
      if (!r.ok) {
        var e2 = new Error("auth_me_http_" + r.status);
        e2.status = r.status;
        throw e2;
      }
      return r.json();
    });
  }

  function resolveGateTarget(auth, loc, opts) {
    opts = opts || {};
    var allowed = auth.allowed_pages || [];
    var defaultPage = auth.default_page || "dashboard";
    var want = loc.bare ? defaultPage : (loc.page || defaultPage);

    // Fail closed: malformed or empty allow-list never unlocks a requested page.
    if (auth.malformed || !allowed.length) {
      if (allowed.length && allowed.indexOf(defaultPage) >= 0) return defaultPage;
      if (allowed.length) return allowed[0];
      return ""; // empty → shell must not render a protected page
    }

    if (opts.detailBatchId && (want === "detail" || want === "shipments")) {
      if (!pageIsAllowed("shipments", allowed)) {
        return pageIsAllowed(defaultPage, allowed) ? defaultPage : allowed[0];
      }
      return "detail";
    }
    if (!pageIsAllowed(want, allowed)) {
      return pageIsAllowed(defaultPage, allowed) ? defaultPage : allowed[0];
    }
    return want;
  }

  /** Clear session then land on /login so authenticated /login bounce cannot reopen V2. */
  function failClosedToLogin() {
    return fetch("/auth/logout", { method: "POST", credentials: "include" })
      .catch(function () { /* still bounce */ })
      .then(function () {
        window.location.href = "/login";
      });
  }

  global.AuthorityConsumer = {
    PAGE_ALIASES: PAGE_ALIASES,
    canonPageId: canonPageId,
    pageIsAllowed: pageIsAllowed,
    landingPathFromAuthority: landingPathFromAuthority,
    normalizeAuthority: normalizeAuthority,
    fetchAuthMe: fetchAuthMe,
    resolveGateTarget: resolveGateTarget,
    failClosedToLogin: failClosedToLogin,
  };
})(typeof window !== "undefined" ? window : this);
