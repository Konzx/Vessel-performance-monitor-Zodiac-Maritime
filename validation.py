"""Shared field rules for the grid and transactional report updates."""
import math
import re
from datetime import datetime
from uuid import UUID


FIELD_RULES = {
    'IMO': {'type': 'integer', 'required': True, 'min': 1000000, 'max': 9999999},
    'Vessel_Name': {'type': 'text', 'required': True, 'maxLength': 120},
    'Report_ID': {'type': 'uuid', 'required': True},
    'To_Timestamp': {'type': 'datetime', 'required': True},
    'KPI': {'type': 'enum', 'required': True, 'values': ['Power', 'Speed']},
    'Voyage_Type': {'type': 'enum', 'required': True, 'values': ['CARGO', 'BALLAST']},
    'Report_Duration': {'type': 'number', 'required': True, 'min': 0, 'exclusiveMin': True},
    'SP_BSL_Start': {'type': 'datetime', 'required': True},
    'SP_BSL_End': {'type': 'datetime', 'required': True},
    'SP_BSL_Reports': {'type': 'integer', 'required': True, 'min': 1, 'max': 2147483647},
    'PWR_BSL_SAM': {'type': 'number', 'kpi': 'Power', 'min': 0, 'max': 250},
    'SPD_BSL_SAM': {'type': 'number', 'kpi': 'Speed', 'min': 0, 'max': 250},
    'SPD_BSL_OOS': {'type': 'number', 'kpi': 'Speed', 'min': 0, 'max': 250},
    'Power_ME': {'type': 'number', 'kpi': 'Power', 'min': 0},
    'Power_%': {'type': 'number', 'kpi': 'Power', 'min': 0, 'max': 250},
    'Power_Deviation': {'type': 'number', 'kpi': 'Power', 'min': -250, 'max': 250},
    'Speed_%': {'type': 'number', 'kpi': 'Speed', 'min': 0, 'max': 250},
    'Speed_Deviation': {'type': 'number', 'kpi': 'Speed', 'min': -250, 'max': 250},
    'ME_Running_Hours': {'type': 'number', 'required': True, 'min': 0},
    'Power_Filter_Flag': {'type': 'enum', 'kpi': 'Power', 'values': ['No', 'Yes']},
    'Speed_Filter': {'type': 'enum', 'kpi': 'Speed', 'values': ['No', 'Yes']},
    'Dual_Fuel_Mode_str': {'type': 'enum', 'required': True,
                           'values': ['Non Dual Fuel Only', 'Dual Fuel Capable']},
}


def missing(value):
    return value is None or (isinstance(value, str) and not value.strip()) or (
        isinstance(value, float) and math.isnan(value))


def same_value(left, right):
    if missing(left) or missing(right):
        return missing(left) and missing(right)
    return left == right


def parse_datetime(value):
    text = str(value).strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?| \d{2}:\d{2} [AP]M)?', text):
        raise ValueError('Use YYYY-MM-DD HH:mm.')
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        result = datetime.strptime(text, '%Y-%m-%d %I:%M %p')
    if result.tzinfo is not None:
        raise ValueError('Use a date/time without a timezone.')
    return result


def validate_field(field, raw, row):
    rule = FIELD_RULES[field]
    required = rule.get('required') or rule.get('kpi') == row.get('KPI')
    if missing(raw):
        if required:
            raise ValueError(f'{field} is required.')
        return None
    kind = rule['type']
    if kind in ('number', 'integer'):
        if isinstance(raw, bool):
            raise ValueError(f'{field} must be numeric.')
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f'{field} must be numeric.') from None
        if not math.isfinite(value):
            raise ValueError(f'{field} must be finite.')
        if kind == 'integer' and not value.is_integer():
            raise ValueError(f'{field} must be a whole number.')
        if 'min' in rule and (value < rule['min'] or (rule.get('exclusiveMin') and value == rule['min'])):
            comparison = 'greater than' if rule.get('exclusiveMin') else 'at least'
            raise ValueError(f"{field} must be {comparison} {rule['min']}.")
        if 'max' in rule and value > rule['max']:
            raise ValueError(f"{field} must be at most {rule['max']}.")
        return int(value) if kind == 'integer' else value
    if not isinstance(raw, str):
        raise ValueError(f'{field} must be text.')
    value = raw.strip()
    if any(ord(character) < 32 for character in value):
        raise ValueError(f'{field} cannot contain control characters.')
    if kind == 'enum' and value not in rule['values']:
        raise ValueError(f"{field} must be one of: {', '.join(rule['values'])}.")
    if kind == 'text' and len(value) > rule['maxLength']:
        raise ValueError(f"{field} must contain at most {rule['maxLength']} characters.")
    if kind == 'uuid':
        try:
            if not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value):
                raise ValueError('Invalid UUID')
            value = str(UUID(value))
        except ValueError:
            raise ValueError(f'{field} must be a valid UUID.') from None
    if kind == 'datetime':
        try:
            value = parse_datetime(value).isoformat(timespec='seconds')
        except (ValueError, OverflowError):
            raise ValueError(f'{field} must be a valid date/time, such as 2026-04-15 12:30.') from None
    return value


def validate_relationships(row, changed):
    if {'SP_BSL_Start', 'SP_BSL_End'} & changed:
        if parse_datetime(row['SP_BSL_Start']) > parse_datetime(row['SP_BSL_End']):
            raise ValueError('Baseline start must be on or before baseline end.')
    if {'ME_Running_Hours', 'Report_Duration'} & changed:
        if float(row['ME_Running_Hours']) > float(row['Report_Duration']):
            raise ValueError('ME_Running_Hours cannot exceed Report_Duration.')
    if 'KPI' in changed:
        # Switching KPI requires a complete set of fields for the new type.
        for field, rule in FIELD_RULES.items():
            if rule.get('kpi') == row['KPI']:
                row[field] = validate_field(field, row[field], row)
