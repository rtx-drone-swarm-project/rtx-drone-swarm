import numpy as np

from app.probability_grid import (
    REGION_LABEL_CODES,
    apply_operator_label_grid,
    build_probability_grid,
    create_operator_label_grid,
    create_searchable_mask,
    normalize_probability_grid,
    rectangle_bounds_to_grid_mask,
    smooth_probability_grid,
)


def test_normal_grid_with_all_normal_labels_normalizes_to_one():
    operator_label_grid = create_operator_label_grid(4, 4)
    searchable_mask = create_searchable_mask(4, 4)

    probability_grid, resulting_mask = build_probability_grid(
        (4, 4),
        operator_label_grid=operator_label_grid,
        searchable_mask=searchable_mask,
        smoothing_iterations=1,
    )

    assert probability_grid.shape == (4, 4)
    assert resulting_mask.shape == (4, 4)
    assert np.isclose(probability_grid.sum(), 1.0)


def test_excluded_cells_become_probability_zero():
    operator_label_grid = create_operator_label_grid(3, 3)
    operator_label_grid[1, 1] = REGION_LABEL_CODES["excluded"]

    probability_grid, searchable_mask = build_probability_grid(
        (3, 3),
        operator_label_grid=operator_label_grid,
        smoothing_iterations=1,
    )

    assert searchable_mask[1, 1] == np.False_
    assert probability_grid[1, 1] == 0.0


def test_likely_cells_have_higher_probability_than_normal_cells_without_smoothing():
    operator_label_grid = create_operator_label_grid(3, 3)
    operator_label_grid[1, 1] = REGION_LABEL_CODES["likely"]

    probability_grid, _ = build_probability_grid(
        (3, 3),
        operator_label_grid=operator_label_grid,
        smoothing_iterations=0,
    )

    assert probability_grid[1, 1] > probability_grid[1, 0]
    assert probability_grid[1, 1] > probability_grid[0, 1]


def test_smoothing_zero_preserves_exact_multiplier_ratios_after_normalization():
    operator_label_grid = create_operator_label_grid(1, 3)
    operator_label_grid[0, 0] = REGION_LABEL_CODES["very_unlikely"]
    operator_label_grid[0, 1] = REGION_LABEL_CODES["normal"]
    operator_label_grid[0, 2] = REGION_LABEL_CODES["very_likely"]

    probability_grid, _ = build_probability_grid(
        (1, 3),
        operator_label_grid=operator_label_grid,
        smoothing_iterations=0,
    )

    expected = np.array([[0.25, 1.0, 4.0]], dtype=float)
    expected /= expected.sum()
    assert np.allclose(probability_grid, expected)


def test_smoothing_preserves_shape():
    score_grid = np.ones((4, 5), dtype=float)
    searchable_mask = np.ones((4, 5), dtype=bool)

    smoothed_grid = smooth_probability_grid(score_grid, searchable_mask, iterations=2)

    assert smoothed_grid.shape == (4, 5)


def test_smoothing_does_not_put_probability_into_excluded_cells():
    operator_label_grid = create_operator_label_grid(4, 5)
    operator_label_grid[0, 0] = REGION_LABEL_CODES["excluded"]
    operator_label_grid[2, 3] = REGION_LABEL_CODES["excluded"]

    score_grid = np.ones((4, 5), dtype=float)
    searchable_mask = create_searchable_mask(4, 5)
    adjusted_scores, adjusted_mask = apply_operator_label_grid(
        score_grid,
        searchable_mask,
        operator_label_grid,
    )
    smoothed_grid = smooth_probability_grid(adjusted_scores, adjusted_mask, iterations=2)
    probability_grid = normalize_probability_grid(smoothed_grid, adjusted_mask)

    assert smoothed_grid[0, 0] == 0.0
    assert smoothed_grid[2, 3] == 0.0
    assert probability_grid[0, 0] == 0.0
    assert probability_grid[2, 3] == 0.0


def test_all_excluded_cells_return_all_zeros():
    operator_label_grid = np.full((2, 3), REGION_LABEL_CODES["excluded"], dtype=np.uint8)

    probability_grid, searchable_mask = build_probability_grid(
        (2, 3),
        operator_label_grid=operator_label_grid,
        smoothing_iterations=1,
    )

    assert not np.any(searchable_mask)
    assert np.array_equal(probability_grid, np.zeros((2, 3), dtype=float))


def test_all_excluded_cells_remain_zero_without_smoothing():
    operator_label_grid = np.full((2, 2), REGION_LABEL_CODES["excluded"], dtype=np.uint8)

    probability_grid, searchable_mask = build_probability_grid(
        (2, 2),
        operator_label_grid=operator_label_grid,
        smoothing_iterations=0,
    )

    assert not np.any(searchable_mask)
    assert np.array_equal(probability_grid, np.zeros((2, 2), dtype=float))


def test_rectangle_covering_whole_bounds_selects_all_cells():
    search_grid = np.array([
        [2.0, 10.0], [2.0, 20.0],
        [1.0, 10.0], [1.0, 20.0],
    ], dtype=float)

    mask = rectangle_bounds_to_grid_mask(
        search_grid,
        [2, 2],
        {"min_lat": 1.0, "max_lat": 2.0, "min_lon": 10.0, "max_lon": 20.0},
    )

    assert mask.shape == (2, 2)
    assert np.array_equal(mask, np.ones((2, 2), dtype=bool))


def test_small_rectangle_around_one_grid_point_selects_that_cell():
    search_grid = np.array([
        [2.0, 10.0], [2.0, 20.0],
        [1.0, 10.0], [1.0, 20.0],
    ], dtype=float)

    mask = rectangle_bounds_to_grid_mask(
        search_grid,
        [2, 2],
        {"min_lat": 1.9, "max_lat": 2.1, "min_lon": 9.9, "max_lon": 10.1},
    )

    expected = np.array([
        [True, False],
        [False, False],
    ], dtype=bool)
    assert np.array_equal(mask, expected)


def test_rectangle_between_grid_points_selects_nearest_cell_fallback():
    search_grid = np.array([
        [2.0, 10.0], [2.0, 20.0],
        [1.0, 10.0], [1.0, 20.0],
    ], dtype=float)

    mask = rectangle_bounds_to_grid_mask(
        search_grid,
        [2, 2],
        {"min_lat": 1.4, "max_lat": 1.6, "min_lon": 14.9, "max_lon": 15.1},
    )

    assert mask.shape == (2, 2)
    assert int(mask.sum()) == 1
    assert mask[1, 0] or mask[1, 1]


def test_out_of_bounds_rectangle_uses_in_bounds_matches_or_nearest_fallback():
    search_grid = np.array([
        [2.0, 10.0], [2.0, 20.0], [2.0, 30.0],
        [1.0, 10.0], [1.0, 20.0], [1.0, 30.0],
    ], dtype=float)

    mask = rectangle_bounds_to_grid_mask(
        search_grid,
        [2, 3],
        {"min_lat": 1.5, "max_lat": 2.5, "min_lon": 25.0, "max_lon": 35.0},
    )

    expected = np.array([
        [False, False, True],
        [False, False, False],
    ], dtype=bool)
    assert np.array_equal(mask, expected)


def test_rectangle_mask_returns_shape_matching_grid_shape():
    search_grid = np.array([
        [3.0, 10.0], [3.0, 20.0], [3.0, 30.0],
        [2.0, 10.0], [2.0, 20.0], [2.0, 30.0],
    ], dtype=float)

    mask = rectangle_bounds_to_grid_mask(
        search_grid,
        [2, 3],
        {"min_lat": 100.0, "max_lat": 101.0, "min_lon": 100.0, "max_lon": 101.0},
    )

    assert mask.shape == (2, 3)
    assert int(mask.sum()) == 1
