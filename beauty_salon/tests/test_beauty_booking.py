from datetime import date, datetime, timedelta

import pytz

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def havana_utc(year, month, day, hour, minute=0):
    """UTC naive desde hora local de La Habana (respeta DST)."""
    tz = pytz.timezone("America/Havana")
    return tz.localize(datetime(year, month, day, hour, minute)).astimezone(
        pytz.utc
    ).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


class TestBeautyBooking(TransactionCase):
    def setUp(self):
        super().setUp()
        self.technician = self.env["beauty.technician"].create({"name": "Técnica web"})
        self.service = self.env["beauty.service"].create({
            "name": "Servicio web",
            "service_type": "nails",
            "list_price": 20.0,
            "duration": 1.0,
        })
        self.Appointment = self.env["beauty.appointment"]

    def _next_workday(self):
        day = self.Appointment._booking_tz().localize(
            __import__("datetime").datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        )
        # Avanza hasta el próximo Lun-Vie con huecos.
        for _ in range(10):
            day += timedelta(days=1)
            if day.weekday() < 5:
                slots = self.Appointment.get_booking_day_slots(
                    day.date(), self.service.ids
                )
                if slots:
                    return day.date(), slots
        self.fail("Sin días laborables con huecos para el test")

    def test_day_slots_respect_hours_and_overlap(self):
        day, slots = self._next_workday()
        self.assertTrue(slots)
        # Etiquetas en hora normal con am/pm y dentro de las ventanas.
        def in_morning(label):
            return label in ("10:00 am", "10:30 am")  # servicio de 1h

        def in_afternoon(label):
            return label in (
                "1:00 pm", "1:30 pm", "2:00 pm", "2:30 pm", "3:00 pm", "3:30 pm", "4:00 pm",
            )
        for slot in slots:
            self.assertTrue(
                in_morning(slot["label"]) or in_afternoon(slot["label"]),
                slot["label"],
            )
        # La pausa del mediodía no ofrece huecos de 1h.
        self.assertNotIn("12:00 pm", [s["label"] for s in slots])
        self.assertNotIn("9:00 am", [s["label"] for s in slots])
        # Reservar el primer hueco bloquea ese hueco.
        first = slots[0]
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=first["start_utc"],
            technician_id=first["technician_id"],
        )
        self.assertEqual(appt.state, "to_confirm")
        self.assertTrue(appt.price_locked)
        self.service.list_price = 30.0
        self.assertEqual(appt.amount_total, 20.0)
        appt.action_confirm()
        self.assertEqual(appt.state, "confirmed")
        remaining = self.Appointment.get_booking_day_slots(
            day, self.service.ids, technician_id=first["technician_id"]
        )
        self.assertNotIn(first["start_utc"], [s["start_utc"] for s in remaining])

    def test_public_booking_validates_data(self):
        day, slots = self._next_workday()
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="", phone="600111222", email="",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="12", email="",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="600111222", email="no-es-email",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
            )

    def test_weekend_slots_are_available_and_require_confirmation(self):
        today = datetime.now(self.Appointment._booking_tz()).date()
        days = self.Appointment.get_booking_available_days(
            self.service.ids, technician_id=self.technician.id
        )
        self.assertTrue(days)
        for entry in days:
            self.assertEqual(
                entry["is_weekend"], date.fromisoformat(entry["date"]).weekday() >= 5
            )
        for weekday in (5, 6):
            weekend = next(
                today + timedelta(days=i)
                for i in range(1, 8)
                if (today + timedelta(days=i)).weekday() == weekday
            )
            entry = next(d for d in days if d["date"] == weekend.isoformat())
            self.assertTrue(entry["is_weekend"])
            slots = self.Appointment.get_booking_day_slots(
                weekend, self.service.ids, technician_id=self.technician.id
            )
            self.assertTrue(slots)
            appointment = self.Appointment.create_public_booking(
                name="Ana", phone="600111222", email="",
                service_ids=self.service.ids,
                start_utc_str=slots[0]["start_utc"],
                technician_id=self.technician.id,
            )
            self.assertEqual(appointment.state, "to_confirm")

    def test_booking_outside_windows_is_rejected(self):
        day, slots = self._next_workday()
        tz = self.Appointment._booking_tz()
        noon_local = tz.localize(
            __import__("datetime").datetime(
                day.year, day.month, day.day, 12, 0, 0
            )
        )
        noon_utc = noon_local.astimezone(__import__("pytz").utc).replace(tzinfo=None)
        with self.assertRaises(ValidationError):
            self.Appointment.create_public_booking(
                name="Ana", phone="600111222", email="",
                service_ids=self.service.ids,
                start_utc_str=noon_utc.strftime("%Y-%m-%d %H:%M:%S"),
            )

    def test_confirm_notifies_technician_by_email(self):
        self.technician.email = "tecnica@test.local"
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="ana@test.local",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.state, "to_confirm")
        self.assertIn("Servicio web", appt.service_names_display)
        mail = self.env["mail.mail"].search([
            ("model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertTrue(mail, "Debe encolarse el aviso a la técnica")
        self.assertIn("tecnica@test.local", mail.email_to)

    def test_confirm_posts_note_and_schedules_activity(self):
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.state, "to_confirm")
        # Solo la técnica confirma: ahí se publica el aviso y la actividad.
        appt.action_confirm()
        self.assertEqual(appt.state, "confirmed")
        message = self.env["mail.message"].search([
            ("model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
            ("body", "ilike", "Cita confirmada"),
        ], limit=1)
        self.assertTrue(message, "Debe publicarse el aviso en el chatter")
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertTrue(activity, "Debe crearse la actividad de la cita")
        self.assertIn(appt.name, activity.summary)

    def test_slots_follow_service_schedule(self):
        morning_service = self.env["beauty.service"].create({
            "name": "Servicio de mañana",
            "service_type": "nails",
            "list_price": 10.0,
            "duration": 0.5,
            "schedule": "morning",
        })
        afternoon_service = self.env["beauty.service"].create({
            "name": "Servicio de tarde",
            "service_type": "brows",
            "list_price": 10.0,
            "duration": 0.5,
            "schedule": "afternoon",
        })
        day, _ = self._next_workday()
        morning_slots = self.Appointment.get_booking_day_slots(
            day, morning_service.ids
        )
        self.assertTrue(morning_slots)
        for slot in morning_slots:
            self.assertTrue(slot["label"].endswith("am"), slot["label"])
        afternoon_slots = self.Appointment.get_booking_day_slots(
            day, afternoon_service.ids
        )
        self.assertTrue(afternoon_slots)
        for slot in afternoon_slots:
            self.assertTrue(slot["label"].endswith("pm"), slot["label"])

    def test_slots_use_technician_timezone(self):
        self.technician.tz = "America/New_York"
        tz = pytz.timezone("America/New_York")
        day = datetime.now(tz).date() + timedelta(days=3)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        slots = self.Appointment.get_booking_day_slots(
            day, self.service.ids, technician_id=self.technician.id
        )
        self.assertTrue(slots)
        # Ventanas 10:00-11:30 am y 1:00-5:00 pm en hora de Nueva York (servicio 1h).
        allowed = {
            (10, 0), (10, 30),
            (13, 0), (13, 30), (14, 0), (14, 30), (15, 0), (15, 30), (16, 0),
        }
        for slot in slots:
            utc = datetime.strptime(
                slot["start_utc"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=pytz.utc)
            local = utc.astimezone(tz)
            self.assertIn((local.hour, local.minute), allowed, slot)
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.state, "to_confirm")
        # Sin sufijo de zona (app solo Cuba): verifica la hora local de NY.
        self.assertTrue(
            appt.booking_local_display.startswith(
                day.strftime("%d/%m/%Y") + " 10:00 am"
            ),
            appt.booking_local_display,
        )

    def test_cron_marks_past_confirmed_as_done(self):
        past = self.env["beauty.appointment"].create({
            "partner_id": self.env["res.partner"].create({"name": "Ayer"}).id,
            "technician_id": self.technician.id,
            "service_ids": [(6, 0, self.service.ids)],
            "start_datetime": havana_utc(2020, 1, 6, 10),
            "duration": 1.0,
        })
        past.action_confirm()
        future = self.env["beauty.appointment"].create({
            "partner_id": past.partner_id.id,
            "technician_id": self.technician.id,
            "service_ids": [(6, 0, self.service.ids)],
            "start_datetime": havana_utc(2030, 6, 1, 10),
            "duration": 1.0,
        })
        future.action_confirm()
        done = self.Appointment.cron_mark_past_done()
        self.assertIn(past, done)
        self.assertEqual(past.state, "done")
        self.assertEqual(future.state, "confirmed")

    def test_technician_view_fields_load(self):
        # Reproduce fields_get de la vista (fallaba _tz_selection sin arg).
        desc = self.env["beauty.technician"].fields_get(["tz"])
        self.assertTrue(desc["tz"]["selection"])
        self.env["beauty.service"].fields_get(["schedule"])

    def test_request_then_confirm_flow_and_whatsapp(self):
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.state, "to_confirm")
        # La técnica confirma y puede escribir por WhatsApp a la clienta.
        appt.action_confirm()
        self.assertEqual(appt.state, "confirmed")
        action = appt.action_open_whatsapp()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("https://wa.me/600111222?text=", action["url"])

    def test_request_notifies_and_confirm_sends_whatsapp(self):
        from unittest.mock import patch

        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="51234567", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        # Al crear (por confirmar): nota interna, sin actividad aún.
        note = self.env["mail.message"].search([
            ("model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
            ("body", "ilike", "Nueva solicitud de reserva"),
        ], limit=1)
        self.assertTrue(note, "Debe avisar en el chatter al crear la cita")
        self.assertFalse(
            self.env["mail.activity"].search([
                ("res_model", "=", "beauty.appointment"),
                ("res_id", "=", appt.id),
            ]),
            "Aún no debe haber actividad antes de confirmar",
        )
        # Sin configurar Meta: confirmar no falla ni envía nada.
        appt.action_confirm()
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertTrue(activity, "Debe crear la actividad al confirmar")
        # Configurado: llama a la API de Meta con el móvil cubano completo.
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("beauty_salon.whatsapp_token", "TESTTOKEN")
        params.set_param("beauty_salon.whatsapp_phone_id", "12345")
        try:
            with patch("odoo.addons.beauty_salon.models.beauty_appointment.requests.post") as post:
                post.return_value.status_code = 200
                post.return_value.text = "{}"
                appt._send_whatsapp_confirmation()
            self.assertTrue(post.called)
            url = post.call_args[0][0]
            payload = post.call_args[1]["json"]
            self.assertIn("/12345/messages", url)
            self.assertEqual(payload["to"], "5351234567")
            self.assertIn(appt.name, payload["text"]["body"])
        finally:
            params.set_param("beauty_salon.whatsapp_token", "")
            params.set_param("beauty_salon.whatsapp_phone_id", "")

    def test_same_phone_other_name_creates_new_partner(self):
        day, slots = self._next_workday()
        first = self.Appointment.create_public_booking(
            name="Ana Pérez", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        second = self.Appointment.create_public_booking(
            name="María Gómez", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[1]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertNotEqual(first.partner_id, second.partner_id)
        self.assertEqual(first.partner_id.name, "Ana Pérez")
        self.assertEqual(second.partner_id.name, "María Gómez")

    def test_appointments_ordered_by_creation_desc(self):
        day, slots = self._next_workday()
        first = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        second = self.Appointment.create_public_booking(
            name="Ana", phone="600111333", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[1]["start_utc"],
            technician_id=self.technician.id,
        )
        found = self.Appointment.search([
            ("id", "in", (first + second).ids),
        ])
        self.assertEqual([a.id for a in found], [second.id, first.id])

    def test_linked_user_gets_notification_and_activity(self):
        user = self.env["res.users"].create({
            "name": "Técnica Real",
            "login": "tecnica.real@test.local",
            "email": "tecnica.real@test.local",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.technician.user_id = user
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        appt.action_confirm()
        self.assertIn(
            user.partner_id, appt.message_partner_ids,
            "La técnica debe quedar suscrita para recibir la notificación",
        )
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertEqual(activity.user_id, user)

    def test_email_falls_back_to_linked_user(self):
        user = self.env["res.users"].create({
            "name": "Técnica Mail",
            "login": "tecnica.mail@test.local",
            "email": "usuario@test.local",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.technician.email = False
        self.technician.user_id = user
        day, slots = self._next_workday()
        appt = self.Appointment.create_public_booking(
            name="Ana", phone="600111222", email="",
            service_ids=self.service.ids,
            start_utc_str=slots[0]["start_utc"],
            technician_id=self.technician.id,
        )
        self.assertEqual(appt.technician_notify_email, "usuario@test.local")
        mail = self.env["mail.mail"].search([
            ("model", "=", "beauty.appointment"),
            ("res_id", "=", appt.id),
        ], limit=1)
        self.assertTrue(mail, "Debe encolarse el aviso al usuario vinculado")
        addressed = (
            "usuario@test.local" in (mail.email_to or "")
            or user.partner_id in mail.recipient_ids
        )
        self.assertTrue(addressed, "Debe ir dirigido al usuario vinculado")

    def test_manual_booking_outside_hours_is_rejected(self):
        partner = self.env["res.partner"].create({"name": "Manual"})
        # 3:00 am La Habana: ni manual se permite.
        with self.assertRaises(ValidationError):
            self.env["beauty.appointment"].create({
                "partner_id": partner.id,
                "technician_id": self.technician.id,
                "service_ids": [(6, 0, self.service.ids)],
                "start_datetime": havana_utc(2030, 6, 2, 3),
                "duration": 1.0,
            })
        # 10:00 am La Habana: válido.
        ok = self.env["beauty.appointment"].create({
            "partner_id": partner.id,
            "technician_id": self.technician.id,
            "service_ids": [(6, 0, self.service.ids)],
            "start_datetime": havana_utc(2030, 6, 2, 10),
            "duration": 1.0,
        })
        self.assertTrue(ok)
