const form = document.querySelector("#login-form");
const alertNode = document.querySelector("#login-alert");
const submitButton = document.querySelector("#login-submit");
const usernameInput = document.querySelector("#username");
const passwordInput = document.querySelector("#password");
const quickLoginButton = document.querySelector("#quick-login-button");
const quickLoginDivider = document.querySelector("#quick-login-divider");

function showError(message) {
  alertNode.textContent = message;
  alertNode.hidden = false;
}

function safeNextPath() {
  const value = new URLSearchParams(location.search).get("next") || "/research/";
  if (!value.startsWith("/research/") || value.startsWith("/research/login")) return "/research/";
  return value;
}

async function readResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

async function checkSession() {
  try {
    const session = await readResponse(await fetch("/api/research/session", { cache: "no-store" }));
    if (session.authenticated) {
      location.replace(safeNextPath());
      return;
    }
    if (!session.configured) {
      showError("尚未配置研究工作台账号，请联系站点管理员完成服务端配置。");
      form.querySelectorAll("input, button").forEach((control) => { control.disabled = true; });
    }
    if (session.quickLoginEnabled && quickLoginButton && quickLoginDivider) {
      quickLoginButton.hidden = false;
      quickLoginDivider.hidden = false;
    }
  } catch (error) {
    showError(error.message);
    form.querySelectorAll("input, button").forEach((control) => { control.disabled = true; });
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  alertNode.hidden = true;
  submitButton.disabled = true;
  submitButton.textContent = "正在登录";
  try {
    await readResponse(await fetch("/api/research/login", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: usernameInput.value.trim(), password: passwordInput.value })
    }));
    const session = await readResponse(await fetch("/api/research/session", { cache: "no-store" }));
    if (!session.authenticated) throw new Error("登录状态尚未生效，请重试");
    location.replace(safeNextPath());
  } catch (error) {
    passwordInput.value = "";
    passwordInput.focus();
    showError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "登录";
  }
});

quickLoginButton?.addEventListener("click", async () => {
  alertNode.hidden = true;
  quickLoginButton.disabled = true;
  quickLoginButton.textContent = "正在登录研究工作台";
  try {
    await readResponse(await fetch("/api/research/quick-login", {
      method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: "{}"
    }));
    location.replace(safeNextPath());
  } catch (error) {
    showError(error.message);
    quickLoginButton.disabled = false;
    quickLoginButton.innerHTML = "一键登录研究工作台 <span aria-hidden=\"true\">↗</span>";
  }
});

document.querySelector("#toggle-password").addEventListener("click", (event) => {
  const visible = passwordInput.type === "text";
  passwordInput.type = visible ? "password" : "text";
  event.currentTarget.textContent = visible ? "显示" : "隐藏";
  event.currentTarget.setAttribute("aria-pressed", String(!visible));
});

checkSession();
