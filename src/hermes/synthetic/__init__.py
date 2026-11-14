"""Deterministic synthetic world: documents, emails, bank statements, GST fixtures, ground truth."""

from hermes.synthetic.generate import generate
from hermes.synthetic.gstin import gstin_checksum, is_valid_gstin

__all__ = ["generate", "gstin_checksum", "is_valid_gstin"]
