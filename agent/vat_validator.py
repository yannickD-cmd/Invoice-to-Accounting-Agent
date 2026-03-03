"""VAT validator — cross-checks extracted VAT against expected rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from agent.constants import MIXED_VAT_GL_CODES, VAT_EXEMPT_GL_CODES
from agent.logging import get_logger
from agent.models.invoice import InvoiceData

logger = get_logger(__name__)

# Tolerance for rounding differences in VAT math checks
ROUNDING_TOLERANCE = Decimal("0.02")


@dataclass
class VATValidationResult:
    """Result of VAT validation checks."""

    math_ok: bool = True
    vat_rate_ok: bool = True
    flags: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.math_ok and self.vat_rate_ok

    @property
    def has_warnings(self) -> bool:
        return len(self.flags) > 0


def validate_vat(invoice: InvoiceData, gl_account: str | None = None) -> VATValidationResult:
    """Run VAT validation checks on an extracted invoice.

    Checks:
    1. Math integrity: sum(vat_lines.base) ≈ subtotal_ht
    2. Math integrity: subtotal_ht + total_vat ≈ total_ttc
    3. Insurance invoices (GL 616000): VAT should be 0%
    4. Food invoices (GL 607100): accept mixed 5.5%/10%, verify math
    5. All others: expected 20%, flag deviations
    """
    result = VATValidationResult()

    # ── 1. VAT line bases should sum to subtotal ───────────────────────
    if invoice.vat_lines:
        bases_sum = sum(v.base for v in invoice.vat_lines)
        base_diff = abs(bases_sum - invoice.subtotal_ht)

        if base_diff > ROUNDING_TOLERANCE:
            result.math_ok = False
            result.flags.append(
                f"VAT bases sum ({bases_sum}) ≠ subtotal HT ({invoice.subtotal_ht}), "
                f"diff = {base_diff}"
            )

    # ── 2. Subtotal + VAT should equal total ───────────────────────────
    computed_total = invoice.subtotal_ht + invoice.total_vat
    total_diff = abs(computed_total - invoice.total_ttc)

    if total_diff > ROUNDING_TOLERANCE:
        result.math_ok = False
        result.flags.append(
            f"HT ({invoice.subtotal_ht}) + TVA ({invoice.total_vat}) = "
            f"{computed_total} ≠ TTC ({invoice.total_ttc}), diff = {total_diff}"
        )

    # ── 3. GL-specific VAT rate checks ─────────────────────────────────
    if gl_account:
        # Insurance: should be exempt (0%)
        if gl_account in VAT_EXEMPT_GL_CODES:
            for vat_line in invoice.vat_lines:
                if vat_line.rate > Decimal("0"):
                    result.vat_rate_ok = False
                    result.flags.append(
                        f"Insurance invoice (GL {gl_account}) shows "
                        f"TVA at {vat_line.rate * 100}% — expected exempt (0%)"
                    )

        # Food: accept 5.5%, 10%, or mixed — just verify math
        elif gl_account in MIXED_VAT_GL_CODES:
            for vat_line in invoice.vat_lines:
                expected_amount = vat_line.base * vat_line.rate
                line_diff = abs(expected_amount - vat_line.amount)
                if line_diff > ROUNDING_TOLERANCE:
                    result.math_ok = False
                    result.flags.append(
                        f"Food VAT line: base {vat_line.base} × {vat_line.rate} = "
                        f"{expected_amount}, but amount is {vat_line.amount}"
                    )

        # Standard: expect 20%
        else:
            for vat_line in invoice.vat_lines:
                if vat_line.rate not in (Decimal("0.20"), Decimal("0.200"), Decimal("0.2")):
                    result.flags.append(
                        f"Non-standard VAT rate {vat_line.rate * 100}% for GL {gl_account} "
                        f"(expected 20%)"
                    )

    if result.flags:
        logger.info("vat_validation_flags", flags=result.flags)
    else:
        logger.info("vat_validation_passed")

    return result
