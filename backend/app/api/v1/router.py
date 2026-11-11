"""Aggregates all v1 routers — imported by main.py."""

from fastapi import APIRouter

from app.api.v1 import health, jobs

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health.router)
v1_router.include_router(jobs.router)
