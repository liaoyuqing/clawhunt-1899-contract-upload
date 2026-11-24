"""HTTP layer for the contract document service."""

from .contracts import router as contracts_router

__all__ = ["contracts_router"]
