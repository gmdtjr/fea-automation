import os
from abaqus.interface import AbaqusInterface
from abaqus.mock_runner import MockAbaqusRunner
from config import get_settings


def get_abaqus_runner() -> AbaqusInterface:
    settings = get_settings()
    if settings.abaqus_mode == "real":
        from abaqus.real_runner import RealAbaqusRunner
        return RealAbaqusRunner(
            abaqus_path=settings.abaqus_path,
            work_dir=settings.work_dir,
        )
    return MockAbaqusRunner(output_dir=settings.output_dir)
