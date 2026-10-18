// Modals sluiten (Annuleren, klik naast de modal, Escape) en serverfouten tonen.
function closeModal() {
  document.getElementById("modal").innerHTML = "";
}

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-close-modal]");
  if (el && (el.tagName === "BUTTON" || event.target === el)) {
    event.preventDefault();
    closeModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
});

document.addEventListener("htmx:responseError", (event) => {
  const flash = document.getElementById("flash");
  if (flash) {
    const div = document.createElement("div");
    div.className = "banner bad";
    div.textContent = "Er ging iets mis (" + event.detail.xhr.status + "). Vernieuw de pagina en probeer het opnieuw.";
    flash.replaceChildren(div);
  }
});
