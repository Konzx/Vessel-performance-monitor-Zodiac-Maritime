var dagfuncs = window.dashAgGridFunctions = window.dashAgGridFunctions || {};

dagfuncs.parseReportDate = function (raw) {
    let text = String(raw).trim();
    const source = text.match(/^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}) (AM|PM)$/);
    if (source) {
        const hour = Number(source[2]);
        if (hour < 1 || hour > 12) return null;
        text = source[1] + " " + String(hour % 12 + (source[4] === "PM" ? 12 : 0)).padStart(2, "0") + ":" + source[3];
    }
    const parts = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$/);
    if (!parts) return null;
    const [year, month, day, hour, minute, second] = parts.slice(1).map(value => Number(value || 0));
    const date = new Date(0);
    date.setUTCFullYear(year, month - 1, day);
    date.setUTCHours(hour, minute, second, 0);
    if (year < 1 || date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 ||
        date.getUTCDate() !== day || date.getUTCHours() !== hour ||
        date.getUTCMinutes() !== minute || date.getUTCSeconds() !== second) return null;
    return date;
};

dagfuncs.validateReportField = function (field, raw, row, rule) {
    const blank = raw === null || raw === undefined || String(raw).trim() === "";
    if (blank) {
        return rule.required || rule.kpi === row.KPI ? {error: field + " is required."} : {value: null};
    }
    if (rule.type === "number" || rule.type === "integer") {
        const value = Number(raw);
        if (typeof raw === "boolean" || !Number.isFinite(value)) return {error: field + " must be a finite number."};
        if (rule.type === "integer" && !Number.isInteger(value)) return {error: field + " must be a whole number."};
        if (rule.min !== undefined && (value < rule.min || (rule.exclusiveMin && value === rule.min))) {
            return {error: field + " must be " + (rule.exclusiveMin ? "greater than " : "at least ") + rule.min + "."};
        }
        if (rule.max !== undefined && value > rule.max) return {error: field + " must be at most " + rule.max + "."};
        return {value: value};
    }
    const value = String(raw).trim();
    if (/[\x00-\x1f]/.test(value)) return {error: field + " cannot contain control characters."};
    if (rule.type === "text" && value.length > rule.maxLength) return {error: field + " must contain at most " + rule.maxLength + " characters."};
    if (rule.type === "enum" && !rule.values.includes(value)) return {error: field + " must be one of: " + rule.values.join(", ") + "."};
    if (rule.type === "uuid" && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) {
        return {error: field + " must be a valid UUID."};
    }
    if (rule.type === "datetime") {
        const date = dagfuncs.parseReportDate(value);
        if (!date) return {error: field + " must be a valid date/time, such as 2026-04-15 12:30."};
        return {value: date.toISOString().slice(0, 19)};
    }
    return {value: rule.type === "uuid" ? value.toLowerCase() : value};
};

dagfuncs.setReportValue = function (params) {
    const field = params.colDef.field;
    if (params.newValue === params.oldValue) return false;
    const result = dagfuncs.validateReportField(field, params.newValue, params.data, params.colDef.context.validation);
    const candidate = Object.assign({}, params.data, {[field]: result.value});
    if (!result.error && (field === "SP_BSL_Start" || field === "SP_BSL_End")) {
        const start = dagfuncs.parseReportDate(candidate.SP_BSL_Start), end = dagfuncs.parseReportDate(candidate.SP_BSL_End);
        if (start && end && start > end) result.error = "Baseline start must be on or before baseline end.";
    }
    if (!result.error && (field === "ME_Running_Hours" || field === "Report_Duration") &&
        Number(candidate.ME_Running_Hours) > Number(candidate.Report_Duration)) {
        result.error = "ME_Running_Hours cannot exceed Report_Duration.";
    }
    if (result.error) {
        window.dash_clientside.set_props("validation-message", {children: result.error + " Edit rejected; previous value kept."});
        return false;
    }
    window.dash_clientside.set_props("validation-message", {children: ""});
    params.data[field] = result.value;
    return true;
};

dagfuncs.reportCellStyle = function (params) {
    const normal = {backgroundColor: "transparent", color: "#334155", fontWeight: "normal"};
    const rule = params.colDef.context.validation;
    const result = dagfuncs.validateReportField(params.colDef.field, params.value, params.data, rule);
    if (result.error) return Object.assign({}, normal, {backgroundColor: "#ffe6e6", color: "#9e1010"});
    if (params.colDef.field.endsWith("_Deviation") && params.value !== null && params.value < 0) {
        return {backgroundColor: "#ffe2e2", color: "#9e1010", fontWeight: "bold"};
    }
    return normal;
};

dagfuncs.reportTooltip = function (params) {
    const result = dagfuncs.validateReportField(params.colDef.field, params.value, params.data, params.colDef.context.validation);
    return result.error || String(params.value === null || params.value === undefined ? "" : params.value);
};
