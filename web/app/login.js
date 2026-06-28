import { getSupabase, getSession } from "./lib.js";

const email = document.getElementById("email");
const password = document.getElementById("password");
const err = document.getElementById("login-error");
const signInBtn = document.getElementById("sign-in");
const signUpBtn = document.getElementById("sign-up");

getSession().then((s) => {
  if (s) window.location.href = "./index.html";
});

function showError(message) {
  err.textContent = message;
  err.classList.remove("hidden");
}

async function auth(mode) {
  err.classList.add("hidden");
  const sb = await getSupabase();
  const creds = { email: email.value.trim(), password: password.value };
  const { error } =
    mode === "signin"
      ? await sb.auth.signInWithPassword(creds)
      : await sb.auth.signUp(creds);
  if (error) {
    showError(error.message);
    return;
  }
  window.location.href = "./index.html";
}

signInBtn.addEventListener("click", () => auth("signin"));
signUpBtn.addEventListener("click", () => auth("signup"));
