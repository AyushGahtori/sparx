import { frontendConfig } from "./config.js";
import { getAuthError, getCurrentUser, isAuthEnabled, redirectAfterLogin, signInWithGoogle, waitForAuthReady } from "./services/auth.js";
import { escapeHtml } from "./utils/formatter.js";
import { showError } from "./utils/notifications.js";

const loginMessage = document.getElementById("login-message");
const signInButton = document.getElementById("google-sign-in-button");

function renderMessage(type, message) {
  loginMessage.innerHTML = `<div class="alert ${type}">${escapeHtml(message)}</div>`;
}

async function initialiseLoginPage() {
  await waitForAuthReady();

  if (!isAuthEnabled()) {
    signInButton.disabled = true;
    renderMessage(
      "error",
      "Firebase authentication is disabled in frontend/runtime-config.js. Configure Firebase before using the production sign-in flow.",
    );
    return;
  }

  if (getCurrentUser()) {
    redirectAfterLogin();
    return;
  }

  const authError = getAuthError();
  if (authError instanceof Error) {
    renderMessage("error", authError.message);
  } else if (frontendConfig.auth.required) {
    renderMessage("success", "Sign in with your Firebase operator account to continue.");
  }
}

signInButton.addEventListener("click", async () => {
  try {
    await signInWithGoogle();
    if (getCurrentUser()) {
      redirectAfterLogin();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unable to sign in with Firebase.";
    renderMessage("error", message);
    showError(message);
  }
});

initialiseLoginPage();
