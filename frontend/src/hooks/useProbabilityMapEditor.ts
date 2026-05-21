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
  probabilityRegionEditingEnabled: boolean;
};

export function useProbabilityMapEditor({
  apiClient,
  mission,
  setMission,
  probabilityRegionEditingEnabled,
}: UseProbabilityMapEditorArgs) {
  const [temporaryRegionBounds, setTemporaryRegionBounds] = useState<Bounds | null>(null);
  const [temporaryRegionCells, setTemporaryRegionCells] = useState<ProbabilityGridCell[]>(
    EMPTY_TEMPORARY_REGION_CELLS
  );
  const [temporaryRegionLabel, setTemporaryRegionLabel] = useState<ProbabilityRegionLabel | "">("");

  const clearTemporaryRegionSelection = useCallback(() => {
    setTemporaryRegionBounds(null);
    setTemporaryRegionCells(EMPTY_TEMPORARY_REGION_CELLS);
    setTemporaryRegionLabel("");
  }, []);

  useEffect(() => {
    if (!probabilityRegionEditingEnabled) {
      clearTemporaryRegionSelection();
    }
  }, [clearTemporaryRegionSelection, probabilityRegionEditingEnabled]);

  const onSelectTemporaryRegion = useCallback(
    async (bounds: Bounds) => {
      if (!probabilityRegionEditingEnabled || !mission?.id) return;

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
    [apiClient, mission?.id, probabilityRegionEditingEnabled]
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

  const onResetProbabilityGrid = useCallback(async (): Promise<MissionRecord | null> => {
    if (!mission?.id) return null;

    try {
      const resetMission = await apiClient.resetProbabilityGrid(mission.id);
      clearTemporaryRegionSelection();
      setMission((current) =>
        current
          ? {
              ...current,
              ...resetMission,
            }
          : resetMission
      );
      return resetMission;
    } catch (err) {
      console.warn(
        `Reset probability grid failed: ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }
  }, [apiClient, clearTemporaryRegionSelection, mission?.id, setMission]);

  return {
    temporaryRegionBounds,
    temporaryRegionCells,
    temporaryRegionLabel,
    setTemporaryRegionLabel,
    clearTemporaryRegionSelection,
    onSelectTemporaryRegion,
    onApplyTemporaryRegion,
    onConfirmLabelledRegions,
    onReopenProbabilityGrid,
    onResetProbabilityGrid,
  };
}
