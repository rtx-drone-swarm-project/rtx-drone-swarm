// src/hooks/useSearchAreaSetup.ts

import { useCallback, useState } from "react";
import type { Bounds, PlacedHiker, SearchAreaCorners } from "../types/mission";
import { boundsToSearchAreaCorners, searchAreaCornersToBounds } from "../utils/geo";
import { parseCoordinate } from "../utils/validate";

type SearchAreaFields = {
  topLeftLat: string;
  topLeftLon: string;
  bottomRightLat: string;
  bottomRightLon: string;
};

type UseSearchAreaSetupArgs = {
  clearTemporaryRegionSelection: () => void;
  setMapCenter: React.Dispatch<React.SetStateAction<[number, number] | null>>;
  setPlacedHikers: React.Dispatch<React.SetStateAction<PlacedHiker[]>>;
  setIsPlacingHiker: React.Dispatch<React.SetStateAction<boolean>>;
};

function formatCornerValue(value: number): string {
  return value.toFixed(6);
}

function getBoundsCenter(bounds: Bounds): [number, number] {
  return [
    (bounds.min_lat + bounds.max_lat) / 2,
    (bounds.min_lon + bounds.max_lon) / 2,
  ];
}

function parseSearchAreaCorners(corners: SearchAreaFields): SearchAreaCorners | null {
  const topLeftLat = parseCoordinate(corners.topLeftLat, -90, 90);
  const topLeftLon = parseCoordinate(corners.topLeftLon, -180, 180);
  const bottomRightLat = parseCoordinate(corners.bottomRightLat, -90, 90);
  const bottomRightLon = parseCoordinate(corners.bottomRightLon, -180, 180);

  if (
    topLeftLat == null ||
    topLeftLon == null ||
    bottomRightLat == null ||
    bottomRightLon == null
  ) {
    return null;
  }

  return {
    topLeftLat,
    topLeftLon,
    bottomRightLat,
    bottomRightLon,
  };
}

function isValidSearchAreaDraft(corners: SearchAreaFields): boolean {
  const parsedCorners = parseSearchAreaCorners(corners);
  if (!parsedCorners) return false;

  const bounds = searchAreaCornersToBounds(parsedCorners);
  return bounds.min_lat !== bounds.max_lat && bounds.min_lon !== bounds.max_lon;
}

export function useSearchAreaSetup({
  clearTemporaryRegionSelection,
  setMapCenter,
  setPlacedHikers,
  setIsPlacingHiker,
}: UseSearchAreaSetupArgs) {
    const [topLeftLat, setTopLeftLat] = useState("");
    const [topLeftLon, setTopLeftLon] = useState("");
    const [bottomRightLat, setBottomRightLat] = useState("");
    const [bottomRightLon, setBottomRightLon] = useState("");
    const [isValidBounds, setIsValidBounds] = useState(false);
    const [selectedBounds, setSelectedBounds] = useState<Bounds | null>(null);

    const isPointInsideBounds = useCallback((lat: number, lon: number, bounds: Bounds) => {
        return lat >= bounds.min_lat && lat <= bounds.max_lat && lon >= bounds.min_lon && lon <= bounds.max_lon;
    }, []);

    const updateSearchAreaFields = useCallback((bounds: Bounds) => {
        const corners = boundsToSearchAreaCorners(bounds);

        setTopLeftLat(formatCornerValue(corners.topLeftLat));
        setTopLeftLon(formatCornerValue(corners.topLeftLon));
        setBottomRightLat(formatCornerValue(corners.bottomRightLat));
        setBottomRightLon(formatCornerValue(corners.bottomRightLon));
    }, []);

    const validateDraft = useCallback((nextFields: SearchAreaFields) => {
        setIsValidBounds(isValidSearchAreaDraft(nextFields));
    }, []);

    const onTopLeftLatChange = useCallback(
        (value: string) => {
        setTopLeftLat(value);
        validateDraft({
            topLeftLat: value,
            topLeftLon,
            bottomRightLat,
            bottomRightLon,
        });
        },
        [bottomRightLat, bottomRightLon, topLeftLon, validateDraft]
    );

    const onTopLeftLonChange = useCallback(
        (value: string) => {
        setTopLeftLon(value);
        validateDraft({
            topLeftLat,
            topLeftLon: value,
            bottomRightLat,
            bottomRightLon,
        });
        },
        [bottomRightLat, bottomRightLon, topLeftLat, validateDraft]
    );

    const onBottomRightLatChange = useCallback(
        (value: string) => {
        setBottomRightLat(value);
        validateDraft({
            topLeftLat,
            topLeftLon,
            bottomRightLat: value,
            bottomRightLon,
        });
        },
        [bottomRightLon, topLeftLat, topLeftLon, validateDraft]
    );

    const onBottomRightLonChange = useCallback(
        (value: string) => {
        setBottomRightLon(value);
        validateDraft({
            topLeftLat,
            topLeftLon,
            bottomRightLat,
            bottomRightLon: value,
        });
        },
        [bottomRightLat, topLeftLat, topLeftLon, validateDraft]
    );

    const onSelectArea = useCallback(
        (bounds: Bounds) => {
        clearTemporaryRegionSelection();

        setSelectedBounds(bounds);
        updateSearchAreaFields(bounds);
        setMapCenter(getBoundsCenter(bounds));
        setIsValidBounds(true);

        setPlacedHikers((prev) =>
            prev.filter((hiker) => isPointInsideBounds(hiker.lat, hiker.lon, bounds))
        );

        setIsPlacingHiker(false);
        },
        [
        clearTemporaryRegionSelection,
        setIsPlacingHiker,
        setMapCenter,
        setPlacedHikers,
        updateSearchAreaFields,
        ]
    );

    const onSetSearchArea = useCallback(() => {
        const parsedCorners = parseSearchAreaCorners({
        topLeftLat,
        topLeftLon,
        bottomRightLat,
        bottomRightLon,
        });

        if (!parsedCorners) {
        setIsValidBounds(false);
        return;
        }

        const bounds = searchAreaCornersToBounds(parsedCorners);

        if (bounds.min_lat === bounds.max_lat || bounds.min_lon === bounds.max_lon) {
        setIsValidBounds(false);
        return;
        }

        clearTemporaryRegionSelection();

        updateSearchAreaFields(bounds);
        setIsValidBounds(true);
        setSelectedBounds(bounds);
        setMapCenter(getBoundsCenter(bounds));
    }, [
        bottomRightLat,
        bottomRightLon,
        clearTemporaryRegionSelection,
        setMapCenter,
        topLeftLat,
        topLeftLon,
        updateSearchAreaFields,
    ]);

    return {
        selectedBounds,
        setSelectedBounds,
        topLeftLat,
        topLeftLon,
        bottomRightLat,
        bottomRightLon,
        isValidBounds,
        isPointInsideBounds,
        setIsValidBounds,
        updateSearchAreaFields,
        onTopLeftLatChange,
        onTopLeftLonChange,
        onBottomRightLatChange,
        onBottomRightLonChange,
        onSelectArea,
        onSetSearchArea,
    };
}
