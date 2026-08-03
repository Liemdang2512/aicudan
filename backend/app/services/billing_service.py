import json
from decimal import Decimal
from math import isfinite

from app.schemas.price_config import normalize_legacy_price_config


def _finite_float(value: Decimal, field_name: str) -> float:
    result = float(value)
    if not value.is_finite() or not isfinite(result):
        raise ValueError(f"{field_name} phải là số hữu hạn")
    return result


def _non_negative_decimal(value: object, field_name: str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field_name} phải là số hữu hạn không âm")
    return result


def calculate_tiered_price(consumption: int, config: dict) -> dict:
    tiers = config.get("tiers", [])
    vat_rate = _non_negative_decimal(config.get("vat", 0), "VAT")
    if vat_rate > 1:
        raise ValueError("VAT phải nằm trong khoảng từ 0 đến 1")
    breakdown = []
    total = Decimal(0)
    remaining = consumption

    for tier in tiers:
        if remaining <= 0:
            break

        tier_min = tier["min"]
        tier_max = tier.get("max")
        tier_price = _non_negative_decimal(tier["price"], "Đơn giá")

        if tier_max is not None:
            # Calculate tier capacity correctly
            if tier_min == 0:
                # Tier 1 (0-50): capacity = 50 kWh
                tier_range = tier_max
            else:
                # Tier 2+ (51-100): capacity = 100 - 51 + 1 = 50 kWh
                tier_range = tier_max - tier_min + 1
            tier_consumption = min(remaining, tier_range)
        else:
            tier_consumption = remaining

        tier_amount = tier_consumption * tier_price

        breakdown.append(
            {
                "name": tier.get("name", f"Bậc {len(breakdown) + 1}"),
                "kwh": tier_consumption,
                "price": _finite_float(tier_price, "Đơn giá"),
                "amount": _finite_float(tier_amount, "Thành tiền"),
            }
        )

        total += tier_amount
        remaining -= tier_consumption

    vat_amount = total * vat_rate
    total_with_vat = total + vat_amount

    return {
        "tiers": breakdown,
        "subtotal": _finite_float(total, "Tiền trước VAT"),
        "vat_rate": _finite_float(vat_rate, "VAT"),
        "vat_amount": _finite_float(vat_amount, "Tiền VAT"),
        "total": _finite_float(total_with_vat, "Tổng tiền điện"),
    }


def calculate_fixed_price(consumption: int, config: dict) -> dict:
    price = _non_negative_decimal(config["price"], "Đơn giá")
    vat_rate = _non_negative_decimal(config.get("vat", 0), "VAT")
    if vat_rate > 1:
        raise ValueError("VAT phải nằm trong khoảng từ 0 đến 1")
    subtotal = consumption * price
    vat_amount = subtotal * vat_rate
    total = subtotal + vat_amount

    return {
        "price_per_kwh": _finite_float(price, "Đơn giá"),
        "subtotal": _finite_float(subtotal, "Tiền trước VAT"),
        "vat_rate": _finite_float(vat_rate, "VAT"),
        "vat_amount": _finite_float(vat_amount, "Tiền VAT"),
        "total": _finite_float(total, "Tổng tiền điện"),
    }


def calculate_invoice(
    consumption: int,
    pricing_type: str,
    config_json: str,
    additional_fees: dict[str, float] | None = None,
) -> dict:
    canonical_json, _ = normalize_legacy_price_config(pricing_type, config_json)
    config = json.loads(canonical_json)

    if pricing_type == "tiered":
        price_breakdown = calculate_tiered_price(consumption, config)
    elif pricing_type == "fixed":
        price_breakdown = calculate_fixed_price(consumption, config)
    else:
        raise ValueError("Loại bảng giá phải là fixed hoặc tiered")

    electricity_amount = price_breakdown["total"]

    fees_total = Decimal(0)
    if additional_fees:
        for fee_name, fee_value in additional_fees.items():
            fee = _non_negative_decimal(fee_value, f"Phụ phí {fee_name}")
            fees_total += fee

    total_amount = _finite_float(
        Decimal(str(electricity_amount)) + fees_total,
        "Tổng hóa đơn",
    )

    return {
        "consumption": consumption,
        "price_breakdown": price_breakdown,
        "electricity_amount": electricity_amount,
        "additional_fees": additional_fees or {},
        "total_amount": total_amount,
    }
