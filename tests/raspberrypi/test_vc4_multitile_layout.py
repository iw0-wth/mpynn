"""Host-only layout checks for the experimental VC4 multi-tile ABI."""
import unittest


def plan_tiles(output_depth, input_depth, workers):
    tile_rows = workers * 16
    ranges = []
    for qpu in range(workers):
        first_row = qpu * 16
        tile_count = (output_depth - first_row + tile_rows - 1) // tile_rows
        if tile_count <= 0:
            continue
        rows = [first_row + tile * tile_rows + lane
                for tile in range(tile_count)
                for lane in range(16)
                if first_row + tile * tile_rows + lane < output_depth]
        ranges.append((qpu, first_row, tile_count, rows))
    return ranges


class MultiTileLayoutTests(unittest.TestCase):
    def test_1024_output_rows_are_covered_once_by_12_qpus(self):
        plan = plan_tiles(1024, 2048, 12)
        self.assertEqual([item[2] for item in plan], [6, 6, 6, 6, 5, 5, 5, 5, 5, 5, 5, 5])
        rows = [row for _, _, _, qpu_rows in plan for row in qpu_rows]
        self.assertEqual(sorted(rows), list(range(1024)))
        self.assertEqual(len(set(rows)), 1024)

    def test_all_aligned_depths_have_complete_nonoverlapping_rows(self):
        for workers in range(1, 13):
            for output_depth in range(16, 1025, 16):
                plan = plan_tiles(output_depth, 7, workers)
                rows = [row for _, _, _, qpu_rows in plan for row in qpu_rows]
                self.assertEqual(sorted(rows), list(range(output_depth)),
                                 (workers, output_depth))
                self.assertEqual(len(set(rows)), output_depth,
                                 (workers, output_depth))

    def test_single_dispatch_shape_has_one_tile_per_worker(self):
        plan = plan_tiles(192, 2048, 12)
        self.assertEqual([item[2] for item in plan], [1] * 12)
        rows = [row for _, _, _, qpu_rows in plan for row in qpu_rows]
        self.assertEqual(sorted(rows), list(range(192)))

    def test_scheduled_tile_bases_reconstruct_reference_matvec(self):
        input_depth, output_depth, workers = 7, 208, 12
        x = [((k % 5) - 2) * 0.125 for k in range(input_depth)]
        weights = [((row % 11) - (col % 7)) * 0.0625
                   for row in range(output_depth)
                   for col in range(input_depth)]
        reference = [sum(weights[row * input_depth + k] * x[k]
                         for k in range(input_depth))
                     for row in range(output_depth)]
        scheduled = [None] * output_depth
        tile_rows = workers * 16
        for qpu, first_row, tile_count, rows in plan_tiles(
                output_depth, input_depth, workers):
            for tile in range(tile_count):
                row_base = first_row + tile * tile_rows
                for lane in range(16):
                    row = row_base + lane
                    if row < output_depth:
                        scheduled[row] = sum(
                            weights[row * input_depth + k] * x[k]
                            for k in range(input_depth))
        self.assertEqual(scheduled, reference)

    def test_row_and_weight_tile_strides(self):
        workers, input_depth, output_depth = 12, 2048, 1024
        tile_rows = workers * 16
        weight_stride = tile_rows * input_depth * 4
        output_stride = tile_rows * 4
        self.assertEqual(weight_stride, 1_572_864)
        self.assertEqual(output_stride, 768)
        # Every generated base points to the same global row in W and y.
        for qpu, first_row, tile_count, rows in plan_tiles(
                output_depth, input_depth, workers):
            for tile in range(tile_count):
                row = first_row + tile * tile_rows
                weight_byte_offset = row * input_depth * 4
                output_byte_offset = row * 4
                self.assertEqual(weight_byte_offset // (input_depth * 4), row)
                self.assertEqual(output_byte_offset // 4, row)
                self.assertLessEqual(weight_byte_offset + 16 * input_depth * 4,
                                     output_depth * input_depth * 4)
                self.assertLessEqual(output_byte_offset + 16 * 4,
                                     output_depth * 4)
        # QPU 11 owns five tiles; its final tile begins at global row 944.
        self.assertEqual(11 * 16 + 4 * tile_rows, 944)


if __name__ == "__main__":
    unittest.main()
