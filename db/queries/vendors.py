"""Database queries for vendor operations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import VendorRow


async def get_vendor_by_id(session: AsyncSession, vendor_id: UUID) -> VendorRow | None:
    result = await session.execute(select(VendorRow).where(VendorRow.id == vendor_id))
    return result.scalar_one_or_none()


async def get_vendor_by_siret(session: AsyncSession, siret: str) -> VendorRow | None:
    result = await session.execute(
        select(VendorRow).where(VendorRow.siret == siret, VendorRow.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_vendor_by_name(session: AsyncSession, name: str) -> VendorRow | None:
    """Exact case-insensitive name match."""
    result = await session.execute(
        select(VendorRow).where(
            VendorRow.vendor_name.ilike(name),
            VendorRow.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_all_active_vendors(session: AsyncSession) -> list[VendorRow]:
    result = await session.execute(
        select(VendorRow).where(VendorRow.is_active.is_(True)).order_by(VendorRow.vendor_name)
    )
    return list(result.scalars().all())


async def create_vendor(session: AsyncSession, **kwargs) -> VendorRow:
    vendor = VendorRow(**kwargs)
    session.add(vendor)
    await session.commit()
    await session.refresh(vendor)
    return vendor


async def update_vendor_defaults(
    session: AsyncSession,
    vendor_id: UUID,
    *,
    default_gl: str | None = None,
    default_vat: float | None = None,
    cost_centers: list[str] | None = None,
    corrected_by: str | None = None,
) -> None:
    """Update a vendor's default GL/VAT/CC after a human correction."""
    values: dict = {
        "last_corrected_at": datetime.utcnow(),
    }
    if default_gl is not None:
        values["default_gl"] = default_gl
    if default_vat is not None:
        values["default_vat"] = default_vat
    if cost_centers is not None:
        values["cost_centers"] = cost_centers
    if corrected_by is not None:
        values["last_corrected_by"] = corrected_by

    await session.execute(update(VendorRow).where(VendorRow.id == vendor_id).values(**values))
    await session.commit()


async def add_vendor_alias(session: AsyncSession, vendor_id: UUID, alias: str) -> None:
    vendor = await get_vendor_by_id(session, vendor_id)
    if vendor and alias not in (vendor.aliases or []):
        current = list(vendor.aliases or [])
        current.append(alias)
        await session.execute(
            update(VendorRow).where(VendorRow.id == vendor_id).values(aliases=current)
        )
        await session.commit()
