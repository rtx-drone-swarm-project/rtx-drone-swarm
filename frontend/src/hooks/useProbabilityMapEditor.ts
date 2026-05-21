// src/hooks/useProbabilityMapEditor.ts

import { useCallback, useEffect, useState } from "react";
import type {
  Bounds,
  MissionRecord,
  MissionState,
  ProbabilityGridCell,
  ProbabilityRegionLabel,
} from "../types/mission";
import type { MissionApiClient } from "../api/missionClient";

const EMPTY_TEMPORARY_REGION_CELLS: ProbabilityGridCell[] = [];

type UseProbabilityMapEditorArgs = {
  apiClient: MissionApiClient;
  mission: MissionState;
  setMission: React.Dispatch<React.SetStateAction<MissionState>>;
};

export function useProbabilityMapEditor({
  apiClient,
  mission,
  setMission,
}: UseProbabilityMapEditorArgs) {
  const [temporaryRegionBounds, setTemporaryRegionBounds] = useState<Bounds | null>(null);
  const [temporaryRegionCells, setTemporaryRegionCells] = useState<ProbabilityGridCell[]>(
    EMPTY_TEMPORARY_REGION_CELLS
  );
  const [temporaryRegionLabel, setTemporaryRegionLabel] = useState<ProbabilityRegionLabel | "">("");

  const probabilityMapMode = mission?.search_area_confirmed === true;

  const clearTemporaryRegionSelection = useCallback(() => {
    setTemporaryRegionBounds(null);
    setTemporaryRegionCells(EMPTY_TEMPORARY_REGION_CELLS);
    setTemporaryRegionLabel("");
  }, []);

  useEffect(() => {
    if (!probabilityMapMode) {
      clearTemporaryRegionSelection();
    }
  }, [clearTemporaryRegionSelection, probabilityMapMode]);

  const onSelectTemporaryRegion = useCallback(
    async (bounds: Bounds) => {
      if (!probabilityMapMode || !mission?.id) return;

      setTemporaryRegionBounds(bounds);
      setTemporaryRegionLabel("");

      try {
        const preview = await apiClient.previewProbabilityRegion(mission.id, {
          rect_bounds: bounds,
        });

        setTemporaryRegionCells(
          Array.isArray(preview.cells) ? preview.cells : EMPTY_TEMPORARY_REGION_CELLS
        );
      } catch (err) {
        setTemporaryRegionCells(EMPTY_TEMPORARY_REGION_CELLS);
        console.warn(
          `Preview probability region failed: ${err instanceof Error ? err.message : String(err)}`
        );
      }
    },
    [apiClient, mission?.id, probabilityMapMode]
  );

  const onApplyTemporaryRegion = useCallback(async () => {
    if (!mission?.id || !temporaryRegionBounds || temporaryRegionLabel === "") return;

    try {
      const appliedRegion = await apiClient.applyProbabilityRegion(mission.id, {
        label: temporaryRegionLabel,
        rect_bounds: temporaryRegionBounds,
      });

      setMission((current) =>
        current
          ? {
              ...current,
              operator_label_grid: appliedRegion.operator_label_grid,
              probability_grid: appliedRegion.probability_grid,
              probability_grid_confirmed: false,
            }
          : current
      );

      clearTemporaryRegionSelection();
    } catch (err) {
      console.warn(
        `Apply probability region failed: ${err instanceof Error ? err.message : String(err)}`
      );
    }
  }, [
    apiClient,
    clearTemporaryRegionSelection,
    mission?.id,
    setMission,
    temporaryRegionBounds,
    temporaryRegionLabel,
  ]);

  const onConfirmLabelledRegions = useCallback(async (): Promise<MissionRecord | null> => {
    if (!mission?.id) return null;

    try {
      const confirmedMission = await apiClient.confirmProbabilityGrid(mission.id);
      clearTemporaryRegionSelection();
      setMission((current) =>
        current
          ? {
              ...current,
              ...confirmedMission,
              operator_label_grid: confirmedMission.operator_label_grid ?? current.operator_label_grid,
            }
          : confirmedMission
      );
      return confirmedMission;
    } catch (err) {
      console.warn(
        `Confirm labelled regions failed: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }
  }, [apiClient, clearTemporaryRegionSelection, mission?.id, setMission]);

  const onReopenProbabilityGrid = useCallback(async (): Promise<MissionRecord | null> => {
    if (!mission?.id) return null;

    try {
      const reopenedMission = await apiClient.reopenProbabilityGrid(mission.id);
      clearTemporaryRegionSelection();
      setMission((current) =>
        current
          ? {
              ...current,
              ...reopenedMission,
              operator_label_grid: reopenedMission.operator_label_grid ?? current.operator_label_grid,
            }
          : reopenedMission
      );
      return reopenedMission;
    } catch (err) {
      console.warn(
        `Reopen probability grid failed: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }
  }, [apiClient, clearTemporaryRegionSelection, mission?.id, setMission]);

  return {
    probabilityMapMode,
    temporaryRegionBounds,
    temporaryRegionCells,
    temporaryRegionLabel,
    setTemporaryRegionLabel,
    clearTemporaryRegionSelection,
    onSelectTemporaryRegion,
    onApplyTemporaryRegion,
    onConfirmLabelledRegions,
    onReopenProbabilityGrid,
  };
}
