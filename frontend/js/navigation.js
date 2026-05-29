export function initialiseNavigation() {
  const path = window.location.pathname;
  let activeKey = "home";

  if (path.includes("dashboard")) {
    activeKey = "dashboard";
  } else if (path.includes("manual-call")) {
    activeKey = "manual-call";
  } else if (path.includes("campaigns")) {
    activeKey = "campaigns";
  } else if (path.includes("callbacks")) {
    activeKey = "callbacks";
  } else if (path.includes("summaries")) {
    activeKey = "summaries";
  }

  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.dataset.nav === activeKey) {
      link.classList.add("active");
    }
  });

  const footerYear = document.getElementById("footer-year");
  if (footerYear) {
    footerYear.textContent = `${new Date().getFullYear()}`;
  }
}
