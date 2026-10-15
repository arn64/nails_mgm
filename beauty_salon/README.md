# Salón de Belleza (Odoo 19)

El módulo gestiona servicios de uñas y cejas, clientas, técnicas y citas desde el menú **Salón de Belleza**.

## Flujo de trabajo

1. Revise precios y duraciones en **Servicios** y registre las técnicas y su porcentaje de comisión.
2. Cree una cita con clienta, técnica, fecha y uno o más servicios. La duración se propone desde el catálogo y se puede ajustar.
3. Confirme la cita. Odoo rechaza otra cita confirmada o realizada de la misma técnica que se solape en horario. Las citas consecutivas son válidas.
4. Marque la cita como realizada o cancélela. El historial de la clienta y las estadísticas de la técnica se actualizan.
5. Si necesita crear un pedido mediante Ventas, pulse **Crear pedido** en una cita confirmada o realizada. Cada servicio genera una línea con su precio acordado. Un servicio sin producto vinculado crea automáticamente un producto de tipo servicio; el pedido queda enlazado a la cita. La creación del pedido requiere permisos de Ventas.

Mientras una cita sigue en borrador, su subtotal usa los precios actuales del catálogo. Al solicitar la confirmación o confirmar directamente, se guardan el nombre y el precio acordado de cada servicio; los cambios posteriores en el catálogo no alteran esa cita. Los servicios de una cita con precio fijado no se editan; para pactar otros servicios, cree otra cita. El pedido de venta creado desde la cita usa los precios acordados. Los impuestos y descuentos se gestionan en el pedido de venta.

En una actualización, las citas que ya estaban por confirmar, confirmadas, realizadas o canceladas reciben como referencia los precios disponibles en ese momento. Si el catálogo cambió desde la reserva original, el módulo no puede reconstruir automáticamente el precio histórico.

## Informes de citas

En **Salón de Belleza > Informes > Totales de citas** se muestran la cantidad de citas y la suma de sus importes, agrupadas por estado. Puede cambiar a gráfico, filtrar por fecha o estado y agrupar por técnica, día o mes. La lista de **Citas** también muestra al pie de la columna la suma de las citas visibles en la página; para el total de todas las citas filtradas, use el informe.

El importe de las citas **realizadas** representa el valor de los servicios prestados. La tabla dinámica también permite comparar ese importe con el **cobrado neto** por estado.

## Cobros y devoluciones

En una cita confirmada o realizada, pulse **Registrar cobro** e indique importe, fecha, método y referencia opcional. Puede registrar pagos parciales hasta completar el precio acordado. **Registrar devolución** anota un reembolso real y reduce el cobrado neto; no permite devolver más de lo recibido. Si un movimiento se registró por error, ábralo y pulse **Anular registro**: queda visible en la cita, deja de contar en los informes y conserva quién lo anuló y cuándo. Una cita cancelada muestra el saldo cobrado que no se ha devuelto, sin imponer una política de reembolso.

**Salón de Belleza > Informes > Cobros de citas** muestra el cobrado neto por fecha de pago y estado actual de la cita. Las devoluciones se restan. Estos registros son un control operativo del salón: no crean asientos contables ni concilian facturas de Odoo.

La reserva web está disponible todos los días de 10:00 a 11:30 am y de 1:00 a 5:00 pm. Los sábados y domingos aparecen en amarillo y las solicitudes quedan pendientes de confirmación de la técnica.

## Verificación

Con PostgreSQL disponible, desde la carpeta raíz del proyecto:

```bash
/Volumes/ExtWorkPro/Work/odoo/odoo_19/odoo/venv_19/bin/python \
  /Volumes/ExtWorkPro/Work/odoo/odoo_19/odoo/odoo-bin \
  -c odoo.conf -d nails_mgm_19 -i beauty_salon \
  --test-enable --test-tags /beauty_salon --stop-after-init --no-http
```

Para una base que ya tenga el módulo instalado, sustituya `-i` por `-u`.
