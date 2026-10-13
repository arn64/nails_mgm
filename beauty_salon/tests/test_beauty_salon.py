from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestBeautySalon(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({"name": "Clienta de prueba"})
        self.technician = self.env["beauty.technician"].create({"name": "Técnica de prueba"})
        self.service = self.env["beauty.service"].create({
            "name": "Manicura de prueba",
            "service_type": "nails",
            "list_price": 25.0,
            "duration": 1.0,
        })

    def _appointment(self, start, **extra):
        values = {
            "partner_id": self.partner.id,
            "technician_id": self.technician.id,
            "service_ids": [(6, 0, self.service.ids)],
            "start_datetime": start,
            "duration": 1.0,
        }
        values.update(extra)
        return self.env["beauty.appointment"].create(values)

    def test_schedule_blocks_overlap_and_allows_adjacent_booking(self):
        first = self._appointment("2030-05-01 14:00:00")
        first.action_confirm()
        second = self._appointment("2030-05-01 14:30:00")
        with self.assertRaises(ValidationError), self.cr.savepoint():
            second.action_confirm()
        adjacent = self._appointment("2030-05-01 15:00:00")
        adjacent.action_confirm()
        first.action_cancel()
        second.action_confirm()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            adjacent.write({"start_datetime": "2030-05-01 14:45:00"})

    def test_amount_and_last_visit_follow_realized_service(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        self.assertEqual(appointment.amount_total, 25.0)
        self.assertFalse(self.partner.beauty_last_visit)
        self.service.list_price = 30.0
        self.assertEqual(appointment.amount_total, 30.0)
        appointment.action_confirm()
        appointment.action_done()
        self.assertEqual(self.partner.beauty_last_visit, appointment.start_datetime)
        self.technician.commission_rate = 10
        self.assertEqual(self.technician.done_amount_total, 30.0)
        self.assertEqual(self.technician.commission_amount, 3.0)

    def test_sale_order_has_service_product_and_is_reused(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        with self.assertRaises(UserError):
            appointment.action_create_sale_order()
        appointment.action_confirm()
        action = appointment.action_create_sale_order()
        order = appointment.sale_order_id
        self.assertEqual(action["res_id"], order.id)
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id.type, "service")
        self.assertEqual(order.order_line.price_unit, 25.0)
        self.assertEqual(appointment.action_create_sale_order()["res_id"], order.id)
        self.assertEqual(self.service.product_id, order.order_line.product_id)

    def test_invalid_prices_durations_and_commissions(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.service.duration = 0
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.service.list_price = -1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.technician.commission_rate = 101
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._appointment("2030-05-01 14:00:00", duration=0)
