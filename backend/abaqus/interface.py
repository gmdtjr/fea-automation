from abc import ABC, abstractmethod


class AbaqusInterface(ABC):

    @abstractmethod
    def run_mesh_case1(self, step_file: str, params: dict,
                       geometry_params: dict | None = None) -> dict:
        """
        Case 1: No geo cutting, Sweep + Map mesh generation.
        geometry_params: used by MockRunner for accurate T-shape VTK.
        Returns: { status, element_count, max_aspect_ratio,
                   min_jacobian, vtk_file, execution_time }
        """

    @abstractmethod
    def run_mesh_case2(self, step_file: str, params: dict, cut_planes: list[dict],
                       geometry_params: dict | None = None) -> dict:
        """
        Case 2: Partition then mixed mesh (Auto Tet + Map Hex).
        cut_planes: [{ axis, offset } | { axis:"branch", normal, point, ... }]
        geometry_params: used by MockRunner for accurate T-shape VTK.
        Returns: same structure as run_mesh_case1
        """

    @abstractmethod
    def apply_bc(self, inp_file: str, bc_params: dict) -> dict:
        """Apply material properties / boundary conditions / loads."""

    @abstractmethod
    def submit_job(
        self, inp_file: str,
        geometry_params: dict | None = None,
        bc_params: dict | None = None,
        case_type: str = "case1",
        mesh_result: dict | None = None,
        cut_planes: list[dict] | None = None,
    ) -> dict:
        """
        Run FEA job.
        geometry_params / bc_params: passed by orchestrator for mock calculations.
        Returns: { status, job_name, max_mises, max_displacement,
                   max_stress_location, allowable_stress, result_file }
        """
