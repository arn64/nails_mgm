/** Muestra siempre am/pm en fechas-horas del backend.
 *
 * El formato de solo lectura de Odoo (Luxon según locale) puede omitir el
 * meridiano. Este parche añade "am"/"pm" cuando falta, tanto en campos
 * (formulario) como en celdas de lista. No toca la edición ni el picker.
 */
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import { formatDate } from "@web/views/fields/formatters";

/** Convierte una hora 24h al final del texto a 12h con am/pm. */
function to12h(text) {
    if (!text) {
        return text;
    }
    return text.replace(/(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$/, (match, h, m, s) => {
        const hour = parseInt(h, 10);
        const suffix = hour < 12 ? "am" : "pm";
        const h12 = hour % 12 || 12;
        return `${h12}:${m}${s ? `:${s}` : ""} ${suffix}`;
    });
}

function hasMeridiem(text) {
    return /(am|pm|a\.\s?m\.|p\.\s?m\.)\s*$/i.test(text || "");
}

patch(DateTimeField.prototype, {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        if (numeric) {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const values = this.values;
        const value = values[valueIndex];
        if (!value || this.field.type === "date") {
            return super.getFormattedValue(valueIndex, numeric);
        }
        const { showSeconds, showTime } = this.props;
        const showDate =
            !showTime || valueIndex !== 1 || !values[0] || !values[0].hasSame(value, "day");
        const parts = [];
        if (showDate) {
            parts.push(formatDate(value, {}));
        }
        if (showTime !== false) {
            parts.push(value.toFormat(showSeconds ? "h:mm:ss a" : "h:mm a"));
        }
        return parts.join(", ");
    },
});

const formatters = registry.category("formatters");
const datetimeFormatter = formatters.get("datetime");
function beautyDatetimeFormatter(value, options) {
    const text = datetimeFormatter(value, options);
    if (!value || (options && options.showTime === false) || hasMeridiem(text)) {
        return text;
    }
    return to12h(text);
}
beautyDatetimeFormatter.extractOptions = datetimeFormatter.extractOptions;
formatters.add("datetime", beautyDatetimeFormatter, { force: true });
