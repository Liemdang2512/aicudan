from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.price_config import PriceConfig
from app.models.user import User
from app.schemas.price_config import (
    PriceConfigCreate,
    PriceConfigResponse,
    PriceConfigUpdate,
    validate_price_config,
)

router = APIRouter(prefix="/price-configs", tags=["Price Configs"])


@router.get("", response_model=list[PriceConfigResponse])
async def list_price_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PriceConfig)
        .where(PriceConfig.is_active == True, PriceConfig.owner_id == current_user.id)  # noqa: E712
        .order_by(PriceConfig.is_default.desc())
    )
    configs = result.scalars().all()
    return [PriceConfigResponse.model_validate(c) for c in configs]


@router.post("", response_model=PriceConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_price_config(
    body: PriceConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # If this is default, unset other defaults for this user
    if body.is_default:
        result = await db.execute(
            select(PriceConfig).where(
                PriceConfig.is_default == True,  # noqa: E712
                PriceConfig.owner_id == current_user.id,
            )
        )
        for config in result.scalars().all():
            config.is_default = False

    config = PriceConfig(owner_id=current_user.id, **body.model_dump())
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return PriceConfigResponse.model_validate(config)


@router.patch("/{config_id}", response_model=PriceConfigResponse)
async def update_price_config(
    config_id: int,
    body: PriceConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PriceConfig).where(PriceConfig.id == config_id, PriceConfig.owner_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bảng giá không tồn tại")

    update_data = body.model_dump(exclude_unset=True)

    candidate_pricing_type = update_data.get("pricing_type", config.pricing_type)
    candidate_config_json = update_data.get("config_json", config.config_json)
    try:
        update_data["config_json"] = validate_price_config(
            candidate_pricing_type, candidate_config_json
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if update_data.get("is_default"):
        others = await db.execute(
            select(PriceConfig).where(
                PriceConfig.is_default == True,  # noqa: E712
                PriceConfig.owner_id == current_user.id,
            )
        )
        for c in others.scalars().all():
            c.is_default = False

    for field, value in update_data.items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return PriceConfigResponse.model_validate(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PriceConfig).where(PriceConfig.id == config_id, PriceConfig.owner_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bảng giá không tồn tại")

    config.is_active = False
    await db.commit()
