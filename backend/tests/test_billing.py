"""Tests for app.services.billing_service - Invoice calculation engine."""
import json
import math

import pytest

from app.schemas.invoice import InvoiceGenerateRequest
from app.services.billing_service import (
    calculate_fixed_price,
    calculate_invoice,
    calculate_tiered_price,
)

EVN_CONFIG = {
    "tiers": [
        {"min": 0, "max": 50, "price": 1984, "name": "Bậc 1"},
        {"min": 51, "max": 100, "price": 2050, "name": "Bậc 2"},
        {"min": 101, "max": 200, "price": 2380, "name": "Bậc 3"},
        {"min": 201, "max": 300, "price": 2998, "name": "Bậc 4"},
        {"min": 301, "max": 400, "price": 3350, "name": "Bậc 5"},
        {"min": 401, "max": None, "price": 3460, "name": "Bậc 6"},
    ],
    "vat": 0.08,
}

FIXED_CONFIG = {"price": 3500}
FIXED_CONFIG_WITH_VAT = {"price": 3500, "vat": 0.08}


class TestTieredPricing:
    def test_tier_1_only(self):
        """30 kWh - only tier 1"""
        result = calculate_tiered_price(30, EVN_CONFIG)
        assert len(result["tiers"]) == 1
        assert result["tiers"][0]["kwh"] == 30
        assert result["tiers"][0]["price"] == 1984
        expected_subtotal = 30 * 1984
        assert result["subtotal"] == expected_subtotal
        assert result["vat_rate"] == 0.08
        assert result["vat_amount"] == expected_subtotal * 0.08
        # Use pytest.approx() for float comparison to avoid precision issues
        assert result["total"] == pytest.approx(expected_subtotal * 1.08)

    def test_tier_1_and_2(self):
        """80 kWh - tier 1 (50) + tier 2 (30)"""
        result = calculate_tiered_price(80, EVN_CONFIG)
        assert len(result["tiers"]) == 2
        assert result["tiers"][0]["kwh"] == 50
        assert result["tiers"][1]["kwh"] == 30
        subtotal = 50 * 1984 + 30 * 2050
        assert result["subtotal"] == subtotal

    def test_150_kwh(self):
        """150 kWh - tier 1 (50) + tier 2 (50) + tier 3 (50)"""
        result = calculate_tiered_price(150, EVN_CONFIG)
        assert len(result["tiers"]) == 3
        assert result["tiers"][0]["kwh"] == 50
        assert result["tiers"][1]["kwh"] == 50
        assert result["tiers"][2]["kwh"] == 50
        subtotal = 50 * 1984 + 50 * 2050 + 50 * 2380
        assert result["subtotal"] == subtotal

    def test_all_tiers_500kwh(self):
        """500 kWh - all 6 tiers"""
        result = calculate_tiered_price(500, EVN_CONFIG)
        assert len(result["tiers"]) == 6
        assert result["tiers"][0]["kwh"] == 50   # Bậc 1
        assert result["tiers"][1]["kwh"] == 50   # Bậc 2
        assert result["tiers"][2]["kwh"] == 100  # Bậc 3
        assert result["tiers"][3]["kwh"] == 100  # Bậc 4
        assert result["tiers"][4]["kwh"] == 100  # Bậc 5
        assert result["tiers"][5]["kwh"] == 100  # Bậc 6

    def test_zero_consumption(self):
        """0 kWh"""
        result = calculate_tiered_price(0, EVN_CONFIG)
        assert result["subtotal"] == 0
        assert result["total"] == 0

    def test_exact_tier_boundary(self):
        """50 kWh exactly fills tier 1"""
        result = calculate_tiered_price(50, EVN_CONFIG)
        assert len(result["tiers"]) == 1
        assert result["tiers"][0]["kwh"] == 50

    def test_vat_calculation(self):
        """VAT should be 8% of subtotal"""
        result = calculate_tiered_price(100, EVN_CONFIG)
        subtotal = result["subtotal"]
        assert result["vat_amount"] == subtotal * 0.08
        assert result["total"] == subtotal + result["vat_amount"]


class TestFixedPricing:
    def test_basic(self):
        result = calculate_fixed_price(100, FIXED_CONFIG)
        assert result["price_per_kwh"] == 3500
        assert result["subtotal"] == 350000
        assert result["total"] == 350000

    def test_zero(self):
        result = calculate_fixed_price(0, FIXED_CONFIG)
        assert result["total"] == 0

    def test_large_consumption(self):
        result = calculate_fixed_price(1000, FIXED_CONFIG)
        assert result["total"] == 3500000

    def test_vat_calculation(self):
        result = calculate_fixed_price(100, FIXED_CONFIG_WITH_VAT)
        assert result["subtotal"] == 350000
        assert result["vat_amount"] == 28000
        assert result["total"] == 378000


class TestCalculateInvoice:
    def test_tiered_with_json_string(self):
        config_json = json.dumps(EVN_CONFIG)
        result = calculate_invoice(100, "tiered", config_json)
        assert result["consumption"] == 100
        assert "price_breakdown" in result
        assert result["electricity_amount"] > 0
        assert result["total_amount"] > 0

    def test_fixed_with_dict(self):
        result = calculate_invoice(100, "fixed", FIXED_CONFIG)
        assert result["consumption"] == 100
        assert result["electricity_amount"] == 350000

    def test_with_additional_fees(self):
        fees = {"garbage": 50000, "water": 100000}
        result = calculate_invoice(100, "fixed", FIXED_CONFIG, additional_fees=fees)
        assert result["additional_fees"] == fees
        assert result["total_amount"] == 350000 + 150000

    def test_no_additional_fees(self):
        result = calculate_invoice(50, "fixed", FIXED_CONFIG)
        assert result["additional_fees"] == {}
        assert result["total_amount"] == result["electricity_amount"]

    def test_legacy_fixed_config_is_normalized_before_calculation(self):
        legacy_config = json.dumps({"price_per_kwh": 3500, "vat": 8})
        result = calculate_invoice(100, "fixed", legacy_config)
        assert result["electricity_amount"] == 378000

    @pytest.mark.parametrize("invalid_fee", [-1, float("nan"), float("inf"), float("-inf")])
    def test_rejects_invalid_additional_fees(self, invalid_fee):
        with pytest.raises(ValueError):
            calculate_invoice(
                100,
                "fixed",
                FIXED_CONFIG,
                additional_fees={"service": invalid_fee},
            )

    def test_schema_rejects_non_finite_additional_fees(self):
        with pytest.raises(ValueError):
            InvoiceGenerateRequest.model_validate(
                {
                    "building_id": 1,
                    "invoice_month": "2025-01",
                    "price_config_id": 1,
                    "additional_fees": {"service": float("nan")},
                }
            )

    def test_billing_never_returns_non_finite_amounts(self):
        result = calculate_invoice(
            100,
            "fixed",
            FIXED_CONFIG_WITH_VAT,
            additional_fees={"service": 1000},
        )
        assert math.isfinite(result["electricity_amount"])
        assert math.isfinite(result["total_amount"])

    def test_billing_rejects_finite_input_that_would_overflow_float_output(self):
        with pytest.raises(ValueError, match="hữu hạn"):
            calculate_invoice(100, "fixed", {"price": 1e308})


@pytest.mark.parametrize(
    ("calculator", "config"),
    [
        (calculate_fixed_price, {"price": -1}),
        (calculate_fixed_price, {"price": 3500, "vat": float("nan")}),
        (
            calculate_tiered_price,
            {"tiers": [{"min": 0, "max": None, "price": float("inf")}], "vat": 0},
        ),
    ],
)
def test_pricing_calculators_reject_invalid_numeric_inputs(calculator, config):
    with pytest.raises(ValueError):
        calculator(100, config)
