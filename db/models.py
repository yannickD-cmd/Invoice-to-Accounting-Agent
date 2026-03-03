"""SQLAlchemy ORM models — source of truth for the database schema."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class VendorRow(Base):
    __tablename__ = "vendors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_name = Column(Text, nullable=False)
    aliases = Column(ARRAY(Text), default=list)
    siret = Column(Text, unique=True, nullable=True)
    default_gl = Column(Text, nullable=True)
    default_vat = Column(Numeric(5, 4), nullable=True)
    cost_centers = Column(ARRAY(Text), default=list)
    payment_terms = Column(Numeric, nullable=True)  # days
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    last_corrected_by = Column(Text, nullable=True)
    last_corrected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoices = relationship("ProcessedInvoiceRow", back_populates="vendor")


class JobRow(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gmail_message_id = Column(Text, unique=True, nullable=True)
    raw_drive_id = Column(Text, nullable=True)
    raw_filename = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="RECEIVED")
    exception_type = Column(Text, nullable=True)
    exception_note = Column(Text, nullable=True)
    extracted_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    invoice = relationship("ProcessedInvoiceRow", back_populates="job", uselist=False)
    approval = relationship("ApprovalRequestRow", back_populates="job", uselist=False)
    audit_entries = relationship("AuditLogRow", back_populates="job", order_by="AuditLogRow.created_at")


class ProcessedInvoiceRow(Base):
    __tablename__ = "processed_invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("vendors.id"), nullable=True)
    invoice_number = Column(Text, nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=True)
    cost_center = Column(Text, nullable=True)
    pennylane_entity = Column(Text, nullable=True)
    gl_account = Column(Text, nullable=True)
    subtotal_ht = Column(Numeric(12, 2), nullable=False)
    vat_amount = Column(Numeric(12, 2), nullable=False)
    total_ttc = Column(Numeric(12, 2), nullable=False)
    currency = Column(Text, default="EUR")
    pennylane_id = Column(Text, nullable=True)
    drive_file_id = Column(Text, nullable=True)
    drive_path = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="COMPLETED")
    payment_confirmed = Column(Boolean, default=False)
    payment_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    payment_confirmed_by = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("JobRow", back_populates="invoice")
    vendor = relationship("VendorRow", back_populates="invoices")


class ApprovalRequestRow(Base):
    __tablename__ = "approval_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    approvers = Column(ARRAY(Text), nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=False)
    escalated = Column(Boolean, default=False)
    status = Column(Text, nullable=False, default="PENDING")
    approved_by = Column(Text, nullable=True)
    rejected_by = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    slack_message_ts = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("JobRow", back_populates="approval")


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    action = Column(Text, nullable=False)
    actor = Column(Text, nullable=False, default="system")
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("JobRow", back_populates="audit_entries")
