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
        self.assertTrue(appointment.price_locked)
        self.assertEqual(appointment.price_line_ids.price_unit, 30.0)
        self.service.list_price = 40.0
        self.assertEqual(appointment.amount_total, 30.0)
        with self.assertRaises(UserError):
            appointment.write({"service_ids": [(5, 0, 0)]})
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
        self.service.list_price = 35.0
        action = appointment.action_create_sale_order()
        order = appointment.sale_order_id
        self.assertEqual(action["res_id"], order.id)
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id.type, "service")
        self.assertEqual(order.order_line.price_unit, 25.0)
        self.assertEqual(appointment.action_create_sale_order()["res_id"], order.id)
        self.assertEqual(self.service.product_id, order.order_line.product_id)

    def test_partial_payments_refunds_and_outstanding_amounts(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        Payment = self.env["beauty.appointment.payment"]
        with self.assertRaises(UserError), self.cr.savepoint():
            Payment.create({"appointment_id": appointment.id, "amount": 5.0})

        appointment.action_confirm()
        self.assertEqual(appointment.amount_due, 25.0)
        first = Payment.create({
            "appointment_id": appointment.id, "amount": 10.0,
            "payment_date": "2030-05-01", "method": "cash",
        })
        self.assertEqual(first.signed_amount, 10.0)
        self.assertEqual(appointment.amount_paid, 10.0)
        self.assertEqual(appointment.amount_due, 15.0)
        Payment.create({"appointment_id": appointment.id, "amount": 16.0})
        self.assertEqual(appointment.amount_total, 25.0)
        self.assertEqual(appointment.amount_paid, 26.0)
        self.assertEqual(appointment.amount_due, 0.0)

        appointment.action_cancel()
        self.assertEqual(appointment.amount_due, 0.0)
        self.assertEqual(appointment.amount_not_refunded, 26.0)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Payment.create({
                "appointment_id": appointment.id, "kind": "refund", "amount": 27.0,
            })
        refund = Payment.with_context(
            default_appointment_id=appointment.id, default_kind="refund"
        ).create({
            "amount": 26.0,
            "payment_date": "2030-05-02", "method": "cash",
        })
        self.assertEqual(refund.signed_amount, -26.0)
        self.assertEqual(appointment.amount_paid, 0.0)
        self.assertEqual(appointment.amount_not_refunded, 0.0)

    def test_payment_report_and_batch_over_subtotal(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        appointment.action_confirm()
        action = appointment.action_register_payment()
        self.assertEqual(action["context"]["default_amount"], 25.0)
        self.assertEqual(action["res_model"], "beauty.appointment.payment")
        self.assertTrue(self.env.ref("beauty_salon.view_beauty_appointment_payment_pivot"))
        self.env["beauty.appointment.payment"].create([
            {"appointment_id": appointment.id, "amount": 15.0},
            {"appointment_id": appointment.id, "amount": 15.0},
        ])
        self.assertEqual(appointment.amount_paid, 30.0)
        self.assertEqual(appointment.amount_due, 0.0)
        extra_action = appointment.action_register_payment()
        self.assertEqual(extra_action["context"]["default_amount"], 0.0)

    def test_void_payment_keeps_audit_and_restores_balance(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        appointment.action_confirm()
        payment = self.env["beauty.appointment.payment"].create({
            "appointment_id": appointment.id, "amount": 10.0,
        })
        payment.action_void()
        self.assertEqual(payment.state, "void")
        self.assertEqual(payment.signed_amount, 0.0)
        self.assertEqual(payment.void_user_id, self.env.user)
        self.assertTrue(payment.void_date)
        self.assertEqual(appointment.amount_paid, 0.0)
        self.assertEqual(appointment.amount_due, 25.0)
        with self.assertRaises(UserError):
            payment.action_void()

    def test_void_cannot_leave_unbacked_refund(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        appointment.action_confirm()
        Payment = self.env["beauty.appointment.payment"]
        payment = Payment.create({"appointment_id": appointment.id, "amount": 10.0})
        Payment.create({
            "appointment_id": appointment.id, "kind": "refund", "amount": 10.0,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            payment.action_void()
        self.assertEqual(payment.state, "posted")

    def test_void_refund_can_restore_balance_above_subtotal(self):
        appointment = self._appointment("2030-05-01 14:00:00")
        appointment.action_confirm()
        Payment = self.env["beauty.appointment.payment"]
        Payment.create({"appointment_id": appointment.id, "amount": 35.0})
        refund = Payment.create({
            "appointment_id": appointment.id, "kind": "refund", "amount": 10.0,
        })
        self.assertEqual(appointment.amount_paid, 25.0)
        refund.action_void()
        self.assertEqual(appointment.amount_paid, 35.0)
        self.assertEqual(appointment.amount_due, 0.0)

    def test_directly_created_confirmed_appointment_fixes_price(self):
        appointment = self._appointment("2030-05-01 14:00:00", state="confirmed")
        self.assertTrue(appointment.price_locked)
        self.service.list_price = 50.0
        self.assertEqual(appointment.amount_total, 25.0)

    def test_invalid_prices_durations_and_commissions(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.service.duration = 0
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.service.list_price = -1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.technician.commission_rate = 101
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._appointment("2030-05-01 14:00:00", duration=0)
