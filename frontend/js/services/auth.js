import { frontendConfig } from "../config.js";

const state = {
  auth: null,
  authReadyPromise: null,
  currentUser: null,
  firebase: null,
  provider: null,
  initialised: false,
  lastError: null,
};

function getFirebaseErrorCode(error) {
  if (!error || typeof error !== "object") {
    return "";
  }
  return typeof error.code === "string" ? error.code : "";
}

function createFriendlyAuthError(error) {
  const code = getFirebaseErrorCode(error);
  let message = error instanceof Error ? error.message : "Unable to sign in with Firebase.";

  switch (code) {
    case "auth/configuration-not-found":
    case "auth/operation-not-allowed":
      message =
        "Firebase Google sign-in is not configured for this project. In Firebase Console -> Authentication -> Sign-in method, enable Google and save the provider.";
      break;
    case "auth/unauthorized-domain":
      message =
        "This frontend domain is not authorized in Firebase Auth. Add localhost and 127.0.0.1 to Firebase Console -> Authentication -> Settings -> Authorized domains.";
      break;
    case "auth/invalid-api-key":
      message =
        "The Firebase web API key in frontend/runtime-config.js is invalid or belongs to a different Firebase project.";
      break;
    case "auth/network-request-failed":
      message =
        "Firebase could not be reached from the browser. Check your network connection, firewall, and whether Firebase Authentication is available for this project.";
      break;
    case "auth/popup-blocked":
      message =
        "The browser blocked the Google sign-in popup. SPARX will switch to redirect-based sign-in instead.";
      break;
    case "auth/popup-closed-by-user":
      message = "The Google sign-in popup was closed before authentication completed.";
      break;
    default:
      break;
  }

  const friendlyError = new Error(message);
  if (code) {
    friendlyError.code = code;
  }
  return friendlyError;
}

function shouldFallbackToRedirect(error) {
  return new Set([
    "auth/popup-blocked",
    "auth/web-storage-unsupported",
    "auth/operation-not-supported-in-this-environment",
  ]).has(getFirebaseErrorCode(error));
}

function isFirebaseConfigured() {
  const config = frontendConfig.auth.firebaseConfig;
  return Boolean(config.apiKey && config.authDomain && config.projectId && config.appId);
}

function isLoginPage() {
  const path = window.location.pathname.replace(/\\/g, "/");
  return path.endsWith("/login.html") || path === "/login.html";
}

function getLoginHref() {
  return window.location.pathname.replace(/\\/g, "/").includes("/pages/") ? "../login.html" : "./login.html";
}

function getHomeHref() {
  return "./index.html";
}

function getReturnToUrl() {
  return `${window.location.pathname}${window.location.search}`;
}

function buildUserLabel(user) {
  return user?.displayName || user?.email || "Operator";
}

function buildUserInitials(user) {
  const label = buildUserLabel(user).trim();
  if (!label) {
    return "OP";
  }
  const parts = label.split(/\s+/).filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
}

function renderAuthShell() {
  const slot = document.getElementById("auth-status-slot");
  if (!slot) {
    return;
  }

  if (!frontendConfig.auth.enabled) {
    slot.innerHTML = `<span class="topbar-badge optional">Auth Off</span>`;
    return;
  }

  if (!isFirebaseConfigured()) {
    slot.innerHTML = `<span class="topbar-badge optional">Auth Config Missing</span>`;
    return;
  }

  if (state.currentUser) {
    slot.innerHTML = `
      <button id="auth-sign-out-button" class="button ghost small" type="button">Sign Out</button>
      <span class="user-chip"><span class="user-avatar">${buildUserInitials(state.currentUser)}</span><span>${buildUserLabel(state.currentUser)}</span></span>
    `;
    document.getElementById("auth-sign-out-button")?.addEventListener("click", async () => {
      await signOutCurrentUser();
    });
    return;
  }

  slot.innerHTML = `
    <a id="auth-sign-in-link" class="button secondary small" href="${getLoginHref()}">Sign In</a>
  `;
}

async function loadFirebaseRuntime() {
  if (state.firebase) {
    return state.firebase;
  }

  const [firebaseAppModule, firebaseAuthModule] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js"),
  ]);

  const app = firebaseAppModule.getApps().length
    ? firebaseAppModule.getApp()
    : firebaseAppModule.initializeApp(frontendConfig.auth.firebaseConfig);

  state.firebase = {
    app,
    authModule: firebaseAuthModule,
  };
  state.auth = firebaseAuthModule.getAuth(app);
  state.provider = new firebaseAuthModule.GoogleAuthProvider();
  state.provider.setCustomParameters({ prompt: "select_account" });
  return state.firebase;
}

export async function waitForAuthReady() {
  if (state.authReadyPromise) {
    return state.authReadyPromise;
  }

  state.authReadyPromise = (async () => {
    if (!frontendConfig.auth.enabled) {
      renderAuthShell();
      return null;
    }
    if (!isFirebaseConfigured()) {
      state.lastError = new Error("Firebase web configuration is missing from frontend/runtime-config.js.");
      renderAuthShell();
      if (frontendConfig.auth.required && !isLoginPage()) {
        redirectToLogin();
      }
      return null;
    }

    await loadFirebaseRuntime();
    const { authModule } = state.firebase;
    await authModule.setPersistence(state.auth, authModule.browserLocalPersistence);
    try {
      await authModule.getRedirectResult(state.auth);
    } catch (error) {
      state.lastError = createFriendlyAuthError(error);
    }

    await new Promise((resolve) => {
      const unsubscribe = authModule.onIdTokenChanged(state.auth, (user) => {
        state.currentUser = user;
        state.initialised = true;
        renderAuthShell();
        if (!user && frontendConfig.auth.required && !isLoginPage()) {
          redirectToLogin();
        }
        unsubscribe();
        resolve(undefined);
      });
    });

    return state.currentUser;
  })();

  return state.authReadyPromise;
}

export function getCurrentUser() {
  return state.currentUser;
}

export function getAuthError() {
  return state.lastError;
}

export function isAuthEnabled() {
  return frontendConfig.auth.enabled;
}

export async function getFirebaseIdToken() {
  await waitForAuthReady();
  const user = state.currentUser || state.auth?.currentUser || null;
  if (!user) {
    return null;
  }
  state.currentUser = user;
  return user.getIdToken();
}

export function redirectToLogin() {
  if (isLoginPage()) {
    return;
  }
  const target = `${getLoginHref()}?returnTo=${encodeURIComponent(getReturnToUrl())}`;
  window.location.replace(target);
}

export function redirectAfterLogin() {
  const params = new URLSearchParams(window.location.search);
  const returnTo = params.get("returnTo");
  window.location.replace(returnTo || getHomeHref());
}

export async function signInWithGoogle() {
  await waitForAuthReady();
  if (!state.auth || !state.provider || !state.firebase) {
    throw state.lastError || new Error("Firebase authentication is not configured.");
  }
  const { authModule } = state.firebase;
  try {
    await authModule.signInWithPopup(state.auth, state.provider);
    state.currentUser = state.auth.currentUser;
    state.lastError = null;
    renderAuthShell();
  } catch (error) {
    const friendlyError = createFriendlyAuthError(error);
    state.lastError = friendlyError;
    if (shouldFallbackToRedirect(error)) {
      await authModule.signInWithRedirect(state.auth, state.provider);
      return;
    }
    throw friendlyError;
  }
}

export async function signOutCurrentUser() {
  await waitForAuthReady();
  if (!state.auth || !state.firebase) {
    return;
  }
  await state.firebase.authModule.signOut(state.auth);
  state.currentUser = null;
  renderAuthShell();
  if (frontendConfig.auth.required) {
    redirectToLogin();
  }
}

export async function initialiseAuthShell() {
  await waitForAuthReady();
  renderAuthShell();
}
