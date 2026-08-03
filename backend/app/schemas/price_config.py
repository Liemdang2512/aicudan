import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PricingType = Literal["fixed", "tiered"]
NonNegativeFiniteFloat = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False),
]
VatRate = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False),
]


class PriceTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=0)
    max: int | None = Field(default=None, ge=0)
    price: NonNegativeFiniteFloat
    name: str | None = None

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.max is not None and self.max < self.min:
            raise ValueError("Giới hạn trên của bậc giá phải lớn hơn hoặc bằng giới hạn dưới")
        return self


class FixedPriceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: NonNegativeFiniteFloat
    vat: VatRate | None = None


class TieredPriceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: list[PriceTier] = Field(min_length=1)
    vat: VatRate

    @model_validator(mode="after")
    def validate_tiers(self):
        if self.tiers[0].min != 0:
            raise ValueError("Bậc giá đầu tiên phải bắt đầu từ 0")

        for index, tier in enumerate(self.tiers):
            is_last = index == len(self.tiers) - 1
            if tier.max is None and not is_last:
                raise ValueError("Chỉ bậc giá cuối cùng được để trống giới hạn trên")
            if index > 0:
                previous_max = self.tiers[index - 1].max
                if previous_max is None or tier.min != previous_max + 1:
                    raise ValueError("Các bậc giá phải liên tục và không chồng lấn")

        if self.tiers[-1].max is not None:
            raise ValueError("Bậc giá cuối cùng phải có giới hạn trên để trống")
        return self


def validate_price_config(pricing_type: str, config_json: str | dict[str, Any]) -> str:
    """Validate canonical pricing JSON and return a stable serialized representation."""
    if pricing_type not in ("fixed", "tiered"):
        raise ValueError("Loại bảng giá phải là fixed hoặc tiered")

    try:
        raw_config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Cấu hình bảng giá phải là JSON hợp lệ") from exc

    if not isinstance(raw_config, dict):
        raise ValueError("Cấu hình bảng giá phải là một JSON object")

    model = FixedPriceConfig if pricing_type == "fixed" else TieredPriceConfig
    try:
        validated = model.model_validate(raw_config)
    except ValidationError as exc:
        raise ValueError("Cấu hình bảng giá chứa giá trị không hợp lệ") from exc
    if isinstance(validated, FixedPriceConfig):
        canonical = validated.model_dump(exclude_none=True)
    else:
        canonical = validated.model_dump()
        for tier in canonical["tiers"]:
            if tier["name"] is None:
                del tier["name"]
    return json.dumps(canonical, ensure_ascii=False)


def normalize_legacy_price_config(
    pricing_type: str, config_json: str | dict[str, Any]
) -> tuple[str, bool]:
    """Convert known legacy keys/VAT to canonical JSON without guessing invalid data."""
    try:
        raw_config = json.loads(config_json) if isinstance(config_json, str) else config_json
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Cấu hình bảng giá phải là JSON hợp lệ") from exc

    if not isinstance(raw_config, dict):
        raise ValueError("Cấu hình bảng giá phải là một JSON object")

    normalized = dict(raw_config)
    vat = normalized.get("vat")
    if isinstance(vat, (int, float)) and not isinstance(vat, bool) and 1 < vat <= 100:
        normalized["vat"] = vat / 100

    if pricing_type == "fixed":
        legacy_price = normalized.get("price_per_kwh")
        if "price" not in normalized and legacy_price is not None:
            normalized["price"] = legacy_price
        if "price_per_kwh" in normalized:
            if normalized.get("price") != legacy_price:
                raise ValueError("Giá canonical và legacy không khớp")
            del normalized["price_per_kwh"]
    elif pricing_type == "tiered":
        raw_tiers = normalized.get("tiers")
        if isinstance(raw_tiers, list):
            normalized_tiers = []
            for raw_tier in raw_tiers:
                if not isinstance(raw_tier, dict):
                    raise ValueError("Mỗi bậc giá phải là một JSON object")
                tier = dict(raw_tier)
                for legacy_key, canonical_key in (
                    ("from", "min"),
                    ("to", "max"),
                    ("price_per_kwh", "price"),
                ):
                    if legacy_key not in tier:
                        continue
                    if canonical_key in tier and tier[canonical_key] != tier[legacy_key]:
                        raise ValueError(f"Giá trị {canonical_key} canonical và legacy không khớp")
                    tier[canonical_key] = tier.pop(legacy_key)
                normalized_tiers.append(tier)
            normalized["tiers"] = normalized_tiers
    else:
        raise ValueError("Loại bảng giá phải là fixed hoặc tiered")

    canonical_json = validate_price_config(pricing_type, normalized)
    canonical_config = json.loads(canonical_json)
    changed = canonical_config != raw_config
    if not changed and isinstance(config_json, str):
        return config_json, False
    return canonical_json, changed


class PriceConfigCreate(BaseModel):
    config_name: str = Field(min_length=1, max_length=100)
    pricing_type: PricingType
    config_json: str
    is_default: bool = False

    @model_validator(mode="after")
    def validate_config(self):
        self.config_json = validate_price_config(self.pricing_type, self.config_json)
        return self


class PriceConfigUpdate(BaseModel):
    config_name: str | None = Field(default=None, min_length=1, max_length=100)
    pricing_type: PricingType | None = None
    config_json: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class PriceConfigResponse(BaseModel):
    id: int
    config_name: str
    pricing_type: PricingType
    config_json: str
    is_active: bool
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}
