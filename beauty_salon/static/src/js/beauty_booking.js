/** Reserva web beauty_salon: calendario sencillo sin dependencias. */
(function () {
    "use strict";
    function selectedServices() {
        return Array.from(document.querySelectorAll(".booking-service:checked")).map((el) => el.value);
    }
    function technician() {
        const sel = document.getElementById("booking_technician");
        return sel ? sel.value || null : null;
    }
    function paintDays(days, currentDay) {
        const box = document.getElementById("booking_days");
        if (!box) return;
        box.innerHTML = "";
        if (!days.length) {
            box.innerHTML = '<p class="text-muted mb-0">No hay días disponibles. Prueba con otro servicio o avisa al salón.</p>';
            return;
        }
        days.forEach((d) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.dataset.date = d.date;
            btn.className = "btn btn-day " + (d.date === currentDay ? "btn-primary" : "btn-outline-primary");
            btn.innerHTML = d.weekday + "<br/><strong>" + d.label + "</strong>";
            btn.addEventListener("click", () => chooseDay(d.date));
            box.appendChild(btn);
        });
    }
    function paintSlots(slots, currentStart) {
        const box = document.getElementById("booking_slots");
        const empty = document.getElementById("booking_no_slots");
        if (!box) return;
        box.innerHTML = "";
        (slots || []).forEach((s) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.dataset.start = s.start_utc;
            btn.className = "btn btn-slot " + (s.start_utc === currentStart ? "btn-success" : "btn-outline-success");
            btn.textContent = s.label + (s.technician_name ? " (" + s.technician_name.split(" ")[0] + ")" : "");
            btn.title = s.technician_name || "";
            btn.addEventListener("click", () => chooseSlot(s.start_utc));
            box.appendChild(btn);
        });
        if (empty) empty.style.display = (slots && slots.length) ? "none" : "";
    }
    async function refresh(day) {
        const services = selectedServices();
        if (!services.length) {
            paintDays([], null);
            paintSlots([], null);
            return;
        }
        const tech = technician();
        const techId = tech ? parseInt(tech, 10) : null;
        try {
            const res = await fetch("/reservar/huecos", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { service_ids: services, technician_id: techId, day: day || null },
                }),
            });
            const data = await res.json();
            const result = data.result || {};
            const currentDay = result.day || day || (result.days[0] && result.days[0].date);
            document.getElementById("booking_day").value = currentDay || "";
            paintDays(result.days || [], currentDay);
            paintSlots(result.slots || [], document.getElementById("booking_start_utc").value);
        } catch (e) {
            console.warn("No se pudieron cargar los huecos", e);
        }
    }
    function chooseDay(date) {
        document.getElementById("booking_day").value = date;
        document.getElementById("booking_start_utc").value = "";
        refresh(date);
    }
    function chooseSlot(start) {
        document.getElementById("booking_start_utc").value = start;
        document.querySelectorAll("#booking_slots .btn-slot").forEach((b) => {
            const active = b.dataset.start === start;
            b.classList.toggle("btn-success", active);
            b.classList.toggle("btn-outline-success", !active);
        });
    }
    function bind() {
        // Las clientas (y el personal que pruebe la página) ven la reserva
        // sin la barra de Odoo: se quita el acceso rápido al backend/editor,
        // que Odoo solo muestra a usuarios internos.
        const backendNav = document.querySelector(".o_frontend_to_backend_nav");
        if (backendNav) backendNav.remove();
        document.querySelectorAll(".booking-service").forEach((el) =>
            el.addEventListener("change", () => {
                document.getElementById("booking_start_utc").value = "";
                refresh(document.getElementById("booking_day").value || null);
            })
        );
        const tech = document.getElementById("booking_technician");
        if (tech) tech.addEventListener("change", () => refresh(document.getElementById("booking_day").value || null));
        document.querySelectorAll("#booking_days .btn-day").forEach((b) =>
            b.addEventListener("click", () => chooseDay(b.dataset.date))
        );
        document.querySelectorAll("#booking_slots .btn-slot").forEach((b) =>
            b.addEventListener("click", () => chooseSlot(b.dataset.start))
        );
        const form = document.getElementById("beauty_booking_form");
        if (form) {
            form.addEventListener("submit", (ev) => {
                const start = document.getElementById("booking_start_utc").value;
                if (!start) {
                    ev.preventDefault();
                    alert("Elige un día y una hora disponibles.");
                }
            });
        }
    }
    document.addEventListener("DOMContentLoaded", bind);
})();
