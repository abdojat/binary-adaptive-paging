from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import matplotlib.pyplot as plt


# ============================================================
# Simulator v3: workload-aware simulation for Binary Adaptive Paging
# ============================================================
#
# This version extends Simulator v2 by adding workload-sensitive metrics:
#
#   1. touched_pages
#      Number of unique base pages touched by a workload.
#
#   2. touched_mappings
#      Number of mappings that contain at least one touched page.
#
#   3. loaded_pages_no_split
#      How many base pages would be loaded if touching one page in a mapping
#      requires loading/activating the whole mapping.
#
#   4. fault_amplification_no_split
#      loaded_pages_no_split / touched_pages.
#
#   5. adaptive_split_added_entries
#      Approximate number of extra mapping entries needed if sparse touched
#      parts are isolated from large mappings.
#
#   6. loaded_pages_after_adaptive_split
#      Loaded pages after a simple adaptive split policy.
#
#   7. fault_amplification_after_adaptive_split
#      loaded_pages_after_adaptive_split / touched_pages.
#
#   8. permission_refined_mapping_count
#      Mapping count after forcing mappings not to cross synthetic permission
#      boundaries.
#
# This is still a simulator, not an OS implementation. It intentionally does
# not model real hardware page walkers, OS-specific TLB behavior, real physical
# contiguity, swapping, NUMA, or kernel page table formats.


# ============================================================
# Data structures
# ============================================================

@dataclass(frozen=True)
class Mapping:
    strategy: str
    region_start_page: int
    region_size_pages: int
    virtual_start_page: int
    size_pages: int

    @property
    def virtual_end_page(self) -> int:
        return self.virtual_start_page + self.size_pages

    @property
    def relative_start_page(self) -> int:
        return self.virtual_start_page - self.region_start_page

    @property
    def relative_end_page(self) -> int:
        return self.relative_start_page + self.size_pages


@dataclass(frozen=True)
class WorkloadResult:
    strategy: str
    workload: str
    region_start_page: int
    region_size_pages: int
    mapping_count: int
    largest_mapping_pages: int
    estimated_tlb_reach_pages: int
    touched_pages: int
    touched_mappings: int
    loaded_pages_no_split: int
    fault_amplification_no_split: float
    adaptive_mapping_count: int
    adaptive_split_added_entries: int
    loaded_pages_after_adaptive_split: int
    fault_amplification_after_adaptive_split: float
    permission_refined_mapping_count: int
    permission_split_added_entries: int


# ============================================================
# Utilities
# ============================================================

def msb_position(x: int) -> int:
    if x <= 0:
        raise ValueError("msb_position is defined only for positive integers.")
    return x.bit_length() - 1


def binary_decomposition(size_pages: int) -> List[int]:
    if size_pages <= 0:
        raise ValueError("Region size must be positive.")

    chunks: List[int] = []
    for k in range(msb_position(size_pages), -1, -1):
        if size_pages & (1 << k):
            chunks.append(1 << k)
    return chunks


def descending_powers_of_two(max_size_pages: int) -> List[int]:
    if max_size_pages <= 0 or (max_size_pages & (max_size_pages - 1)) != 0:
        raise ValueError("max_size_pages must be a positive power of two.")

    values = []
    current = max_size_pages
    while current >= 1:
        values.append(current)
        current //= 2
    return values


def split_chunk_by_cap(chunk_size: int, cap: int) -> List[int]:
    if cap <= 0:
        raise ValueError("Cap must be positive.")

    if chunk_size <= cap:
        return [chunk_size]

    count, remainder = divmod(chunk_size, cap)
    parts = [cap] * count

    if remainder:
        parts.extend(binary_decomposition(remainder))

    return parts


# ============================================================
# Mapping strategies
# ============================================================

def fixed_paging(region_start_page: int, region_size_pages: int) -> List[Mapping]:
    return [
        Mapping(
            strategy="fixed",
            region_start_page=region_start_page,
            region_size_pages=region_size_pages,
            virtual_start_page=region_start_page + i,
            size_pages=1,
        )
        for i in range(region_size_pages)
    ]


def huge_page_mixed(
    region_start_page: int,
    region_size_pages: int,
    huge_page_size_pages: int,
) -> List[Mapping]:
    mappings: List[Mapping] = []
    cursor = 0

    while region_size_pages - cursor >= huge_page_size_pages:
        mappings.append(
            Mapping(
                strategy="huge_mixed",
                region_start_page=region_start_page,
                region_size_pages=region_size_pages,
                virtual_start_page=region_start_page + cursor,
                size_pages=huge_page_size_pages,
            )
        )
        cursor += huge_page_size_pages

    while cursor < region_size_pages:
        mappings.append(
            Mapping(
                strategy="huge_mixed",
                region_start_page=region_start_page,
                region_size_pages=region_size_pages,
                virtual_start_page=region_start_page + cursor,
                size_pages=1,
            )
        )
        cursor += 1

    return mappings


def multi_size_unaligned(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
) -> List[Mapping]:
    mappings: List[Mapping] = []
    cursor = 0

    while cursor < region_size_pages:
        remaining = region_size_pages - cursor
        chosen = None

        for size in allowed_sizes:
            if size <= remaining:
                chosen = size
                break

        if chosen is None:
            raise RuntimeError("No allowed page size can cover the remaining region.")

        mappings.append(
            Mapping(
                strategy="multi_size_unaligned",
                region_start_page=region_start_page,
                region_size_pages=region_size_pages,
                virtual_start_page=region_start_page + cursor,
                size_pages=chosen,
            )
        )
        cursor += chosen

    return mappings


def multi_size_aligned(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
) -> List[Mapping]:
    mappings: List[Mapping] = []
    cursor = 0

    while cursor < region_size_pages:
        absolute_start = region_start_page + cursor
        remaining = region_size_pages - cursor
        chosen = None

        for size in allowed_sizes:
            if size <= remaining and absolute_start % size == 0:
                chosen = size
                break

        if chosen is None:
            raise RuntimeError("No aligned page size can cover the remaining region.")

        mappings.append(
            Mapping(
                strategy="multi_size_aligned",
                region_start_page=region_start_page,
                region_size_pages=region_size_pages,
                virtual_start_page=absolute_start,
                size_pages=chosen,
            )
        )
        cursor += chosen

    return mappings


def binary_adaptive_unbounded(
    region_start_page: int,
    region_size_pages: int,
) -> List[Mapping]:
    mappings: List[Mapping] = []
    cursor = 0

    for chunk_size in binary_decomposition(region_size_pages):
        mappings.append(
            Mapping(
                strategy="binary_adaptive_unbounded",
                region_start_page=region_start_page,
                region_size_pages=region_size_pages,
                virtual_start_page=region_start_page + cursor,
                size_pages=chunk_size,
            )
        )
        cursor += chunk_size

    assert cursor == region_size_pages
    return mappings


def binary_adaptive_limited(
    region_start_page: int,
    region_size_pages: int,
    max_bap_chunk_pages: int,
) -> List[Mapping]:
    mappings: List[Mapping] = []
    cursor = 0

    for logical_chunk in binary_decomposition(region_size_pages):
        for physical_chunk in split_chunk_by_cap(logical_chunk, max_bap_chunk_pages):
            mappings.append(
                Mapping(
                    strategy="binary_adaptive_limited",
                    region_start_page=region_start_page,
                    region_size_pages=region_size_pages,
                    virtual_start_page=region_start_page + cursor,
                    size_pages=physical_chunk,
                )
            )
            cursor += physical_chunk

    assert cursor == region_size_pages
    return mappings


def build_mappings(
    region_start_page: int,
    region_size_pages: int,
    max_page_size_pages: int,
    max_bap_chunk_pages: int,
    huge_page_size_pages: int,
) -> Dict[str, List[Mapping]]:
    allowed_sizes = descending_powers_of_two(max_page_size_pages)

    return {
        "fixed": fixed_paging(region_start_page, region_size_pages),
        "huge_mixed": huge_page_mixed(
            region_start_page,
            region_size_pages,
            huge_page_size_pages=huge_page_size_pages,
        ),
        "multi_size_unaligned": multi_size_unaligned(
            region_start_page,
            region_size_pages,
            allowed_sizes=allowed_sizes,
        ),
        "multi_size_aligned": multi_size_aligned(
            region_start_page,
            region_size_pages,
            allowed_sizes=allowed_sizes,
        ),
        "binary_adaptive_limited": binary_adaptive_limited(
            region_start_page,
            region_size_pages,
            max_bap_chunk_pages=max_bap_chunk_pages,
        ),
        "binary_adaptive_unbounded": binary_adaptive_unbounded(
            region_start_page,
            region_size_pages,
        ),
    }


# ============================================================
# BAP lookup validation
# ============================================================

def bap_lookup(region_size_pages: int, address_offset_page: int) -> Tuple[int, int, int]:
    S = region_size_pages
    a = address_offset_page

    if S <= 0:
        raise ValueError("Region size must be positive.")
    if not (0 <= a < S):
        raise ValueError("Address offset must satisfy 0 <= a < S.")

    x = a ^ S
    k = msb_position(x)
    chunk_size = 1 << k
    chunk_base = S & ~((1 << (k + 1)) - 1)

    return chunk_base, chunk_size, k


def naive_find_chunk(mappings: List[Mapping], address_offset_page: int) -> Mapping:
    for mapping in mappings:
        if mapping.relative_start_page <= address_offset_page < mapping.relative_end_page:
            return mapping
    raise ValueError("Address is not covered by any mapping.")


def validate_bap_lookup(max_region_size_pages: int) -> None:
    for S in range(1, max_region_size_pages + 1):
        mappings = binary_adaptive_unbounded(region_start_page=0, region_size_pages=S)
        for a in range(S):
            base, size, _k = bap_lookup(S, a)
            ref = naive_find_chunk(mappings, a)

            assert base == ref.relative_start_page, (
                f"Base mismatch: S={S}, a={a}, lookup={base}, ref={ref.relative_start_page}"
            )
            assert size == ref.size_pages, (
                f"Size mismatch: S={S}, a={a}, lookup={size}, ref={ref.size_pages}"
            )

    print(f"[OK] BAP XOR/MSB lookup validated for region sizes 1..{max_region_size_pages}.")


# ============================================================
# Workload generation
# ============================================================

def workload_dense_sequential(region_size_pages: int, rng: random.Random) -> Set[int]:
    return set(range(region_size_pages))


def workload_sparse_random(region_size_pages: int, rng: random.Random) -> Set[int]:
    count = max(1, math.ceil(region_size_pages * 0.02))
    return set(rng.sample(range(region_size_pages), count))


def workload_very_sparse_random(region_size_pages: int, rng: random.Random) -> Set[int]:
    count = max(1, math.ceil(region_size_pages * 0.002))
    return set(rng.sample(range(region_size_pages), count))


def workload_hot_cold_clustered(region_size_pages: int, rng: random.Random) -> Set[int]:
    hot_size = min(region_size_pages, max(8, region_size_pages // 20))
    hot_start = max(0, region_size_pages // 3)
    hot_end = min(region_size_pages, hot_start + hot_size)

    touched = set(range(hot_start, hot_end))

    cold_count = max(1, region_size_pages // 200)
    cold_candidates = [i for i in range(region_size_pages) if i not in touched]

    if cold_candidates:
        touched.update(rng.sample(cold_candidates, min(cold_count, len(cold_candidates))))

    return touched


def workload_boundary_sparse(region_size_pages: int, rng: random.Random) -> Set[int]:
    touched = {0, region_size_pages - 1}

    cursor = 0
    for chunk in binary_decomposition(region_size_pages):
        touched.add(cursor)
        touched.add(cursor + chunk - 1)
        cursor += chunk

    return {p for p in touched if 0 <= p < region_size_pages}


def workload_cow_burst(region_size_pages: int, rng: random.Random) -> Set[int]:
    """
    Approximate a COW-like burst by writing a small contiguous cluster in
    the middle of the region.
    """
    burst_size = min(region_size_pages, max(4, region_size_pages // 100))
    start = max(0, region_size_pages // 2 - burst_size // 2)
    return set(range(start, min(region_size_pages, start + burst_size)))


def workload_mixed_permissions(region_size_pages: int, rng: random.Random) -> Set[int]:
    """
    Dense touch. The permission-specific effect is measured separately by
    permission boundary refinement.
    """
    return set(range(region_size_pages))


WORKLOADS = {
    "dense_sequential": workload_dense_sequential,
    "sparse_random": workload_sparse_random,
    "very_sparse_random": workload_very_sparse_random,
    "hot_cold_clustered": workload_hot_cold_clustered,
    "boundary_sparse": workload_boundary_sparse,
    "cow_burst": workload_cow_burst,
    "mixed_permissions": workload_mixed_permissions,
}


# ============================================================
# Workload-sensitive metrics
# ============================================================

def mapping_touched_pages(mapping: Mapping, touched_pages: Set[int]) -> List[int]:
    return [
        p for p in touched_pages
        if mapping.relative_start_page <= p < mapping.relative_end_page
    ]


def count_segments_after_isolating_touched_pages(mapping: Mapping, touched: List[int]) -> int:
    """
    Approximate mapping-entry count after isolating touched pages inside one mapping.

    Example:
        mapping covers pages [0, 8)
        touched = [2, 6]

    Segments:
        [0,2) untouched
        [2,3) touched
        [3,6) untouched
        [6,7) touched
        [7,8) untouched

    Count = 5

    This is a conservative approximation of split pressure. It is not meant
    to be an optimal buddy-tree split algorithm.
    """
    if not touched:
        return 1

    touched_sorted = sorted(set(touched))
    start = mapping.relative_start_page
    end = mapping.relative_end_page

    segments = 0
    cursor = start

    for page in touched_sorted:
        if cursor < page:
            segments += 1  # untouched interval
        segments += 1      # touched base page
        cursor = page + 1

    if cursor < end:
        segments += 1      # trailing untouched interval

    return segments


def adaptive_split_metrics(
    mappings: List[Mapping],
    touched_pages: Set[int],
    split_density_threshold: float,
) -> Tuple[int, int, int]:
    """
    Returns:
        adaptive_mapping_count
        split_added_entries
        loaded_pages_after_adaptive_split

    Policy:
        - If a touched mapping is dense enough, keep it as one mapping and
          count the full mapping size as loaded.
        - If a touched mapping is sparse, isolate touched pages and count only
          touched pages as loaded.
        - Untouched mappings remain unchanged in mapping count, but they do not
          contribute to loaded pages.
    """
    adaptive_count = 0
    loaded_after_split = 0

    for mapping in mappings:
        touched_inside = mapping_touched_pages(mapping, touched_pages)

        if not touched_inside:
            adaptive_count += 1
            continue

        density = len(touched_inside) / mapping.size_pages

        if mapping.size_pages == 1 or density >= split_density_threshold:
            adaptive_count += 1
            loaded_after_split += mapping.size_pages
        else:
            adaptive_count += count_segments_after_isolating_touched_pages(
                mapping,
                touched_inside,
            )
            loaded_after_split += len(touched_inside)

    split_added_entries = adaptive_count - len(mappings)
    return adaptive_count, split_added_entries, loaded_after_split


def permission_boundaries(region_size_pages: int) -> List[int]:
    """
    Synthetic permission boundaries.

    The goal is not to model a specific OS layout, but to stress the fact that
    mappings cannot safely cross regions with different permissions.
    """
    if region_size_pages < 8:
        return []

    candidates = {
        region_size_pages // 4,
        region_size_pages // 2,
        (3 * region_size_pages) // 4,
    }

    # Add guard-like finer boundaries for large regions.
    if region_size_pages >= 1024:
        step = 257
        candidates.update(range(step, region_size_pages, step))

    return sorted(b for b in candidates if 0 < b < region_size_pages)


def refined_count_by_boundaries(mappings: List[Mapping], boundaries: Sequence[int]) -> int:
    if not boundaries:
        return len(mappings)

    count = 0

    for mapping in mappings:
        inside = [
            b for b in boundaries
            if mapping.relative_start_page < b < mapping.relative_end_page
        ]

        # n internal boundaries split one mapping into n+1 mappings.
        count += len(inside) + 1

    return count


def estimated_tlb_reach_pages(mappings: List[Mapping], tlb_entries: int) -> int:
    sizes = sorted((m.size_pages for m in mappings), reverse=True)
    return sum(sizes[:tlb_entries])


def evaluate_strategy_on_workload(
    strategy: str,
    mappings: List[Mapping],
    workload_name: str,
    touched_pages: Set[int],
    tlb_entries: int,
    split_density_threshold: float,
) -> WorkloadResult:
    touched_pages_count = len(touched_pages)

    touched_mapping_list: List[Mapping] = []
    loaded_no_split = 0

    for mapping in mappings:
        touched_inside = mapping_touched_pages(mapping, touched_pages)
        if touched_inside:
            touched_mapping_list.append(mapping)
            loaded_no_split += mapping.size_pages

    adaptive_count, split_added, loaded_after_split = adaptive_split_metrics(
        mappings=mappings,
        touched_pages=touched_pages,
        split_density_threshold=split_density_threshold,
    )

    boundaries = permission_boundaries(mappings[0].region_size_pages)
    permission_refined_count = refined_count_by_boundaries(mappings, boundaries)

    return WorkloadResult(
        strategy=strategy,
        workload=workload_name,
        region_start_page=mappings[0].region_start_page,
        region_size_pages=mappings[0].region_size_pages,
        mapping_count=len(mappings),
        largest_mapping_pages=max(m.size_pages for m in mappings),
        estimated_tlb_reach_pages=estimated_tlb_reach_pages(mappings, tlb_entries),
        touched_pages=touched_pages_count,
        touched_mappings=len(touched_mapping_list),
        loaded_pages_no_split=loaded_no_split,
        fault_amplification_no_split=loaded_no_split / max(1, touched_pages_count),
        adaptive_mapping_count=adaptive_count,
        adaptive_split_added_entries=split_added,
        loaded_pages_after_adaptive_split=loaded_after_split,
        fault_amplification_after_adaptive_split=loaded_after_split / max(1, touched_pages_count),
        permission_refined_mapping_count=permission_refined_count,
        permission_split_added_entries=permission_refined_count - len(mappings),
    )


# ============================================================
# CSV output
# ============================================================

def write_results_csv(results: List[WorkloadResult], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "strategy",
        "workload",
        "region_start_page",
        "region_size_pages",
        "mapping_count",
        "largest_mapping_pages",
        "estimated_tlb_reach_pages",
        "touched_pages",
        "touched_mappings",
        "loaded_pages_no_split",
        "fault_amplification_no_split",
        "adaptive_mapping_count",
        "adaptive_split_added_entries",
        "loaded_pages_after_adaptive_split",
        "fault_amplification_after_adaptive_split",
        "permission_refined_mapping_count",
        "permission_split_added_entries",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            writer.writerow(
                {
                    "strategy": r.strategy,
                    "workload": r.workload,
                    "region_start_page": r.region_start_page,
                    "region_size_pages": r.region_size_pages,
                    "mapping_count": r.mapping_count,
                    "largest_mapping_pages": r.largest_mapping_pages,
                    "estimated_tlb_reach_pages": r.estimated_tlb_reach_pages,
                    "touched_pages": r.touched_pages,
                    "touched_mappings": r.touched_mappings,
                    "loaded_pages_no_split": r.loaded_pages_no_split,
                    "fault_amplification_no_split": f"{r.fault_amplification_no_split:.4f}",
                    "adaptive_mapping_count": r.adaptive_mapping_count,
                    "adaptive_split_added_entries": r.adaptive_split_added_entries,
                    "loaded_pages_after_adaptive_split": r.loaded_pages_after_adaptive_split,
                    "fault_amplification_after_adaptive_split": f"{r.fault_amplification_after_adaptive_split:.4f}",
                    "permission_refined_mapping_count": r.permission_refined_mapping_count,
                    "permission_split_added_entries": r.permission_split_added_entries,
                }
            )


def write_selected_csv(results: List[WorkloadResult], output_file: Path) -> None:
    selected_region_size = 10000
    selected_start = 0
    selected_workloads = [
        "dense_sequential",
        "sparse_random",
        "very_sparse_random",
        "hot_cold_clustered",
        "cow_burst",
    ]
    selected_strategies = [
        "fixed",
        "multi_size_aligned",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    rows = [
        r for r in results
        if r.region_size_pages == selected_region_size
        and r.region_start_page == selected_start
        and r.workload in selected_workloads
        and r.strategy in selected_strategies
    ]

    write_results_csv(rows, output_file)


# ============================================================
# Plotting
# ============================================================

def plot_amplification_for_workload(
    results: List[WorkloadResult],
    output_file: Path,
    workload: str,
    region_size_pages: int,
    region_start_page: int = 0,
) -> None:
    strategies = [
        "fixed",
        "huge_mixed",
        "multi_size_aligned",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    rows = [
        r for r in results
        if r.workload == workload
        and r.region_size_pages == region_size_pages
        and r.region_start_page == region_start_page
        and r.strategy in strategies
    ]

    rows.sort(key=lambda r: strategies.index(r.strategy))

    x = list(range(len(rows)))
    labels = [r.strategy for r in rows]
    no_split = [r.fault_amplification_no_split for r in rows]
    after_split = [r.fault_amplification_after_adaptive_split for r in rows]

    width = 0.38

    plt.figure(figsize=(10.5, 5.4))
    plt.bar([i - width / 2 for i in x], no_split, width=width, label="No split")
    plt.bar([i + width / 2 for i in x], after_split, width=width, label="After adaptive split")

    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Page-fault amplification")
    plt.title(f"Fault amplification: {workload}, region size {region_size_pages} pages")
    plt.grid(True, axis="y", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_loaded_pages_by_workload(
    results: List[WorkloadResult],
    output_file: Path,
    strategy: str,
    region_size_pages: int,
    region_start_page: int = 0,
) -> None:
    workloads = list(WORKLOADS.keys())

    rows = [
        r for r in results
        if r.strategy == strategy
        and r.region_size_pages == region_size_pages
        and r.region_start_page == region_start_page
        and r.workload in workloads
    ]

    rows.sort(key=lambda r: workloads.index(r.workload))

    x = list(range(len(rows)))
    labels = [r.workload for r in rows]
    touched = [r.touched_pages for r in rows]
    loaded_no_split = [r.loaded_pages_no_split for r in rows]
    loaded_after_split = [r.loaded_pages_after_adaptive_split for r in rows]

    width = 0.25

    plt.figure(figsize=(11, 5.6))
    plt.bar([i - width for i in x], touched, width=width, label="Touched pages")
    plt.bar(x, loaded_no_split, width=width, label="Loaded pages, no split")
    plt.bar([i + width for i in x], loaded_after_split, width=width, label="Loaded pages, adaptive split")

    plt.yscale("log")
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Pages (log scale)")
    plt.title(f"Loaded pages by workload: {strategy}, region size {region_size_pages}")
    plt.grid(True, axis="y", which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_permission_refinement(
    results: List[WorkloadResult],
    output_file: Path,
    region_size_pages: int,
    region_start_page: int = 0,
) -> None:
    strategies = [
        "fixed",
        "huge_mixed",
        "multi_size_aligned",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    rows = [
        r for r in results
        if r.workload == "mixed_permissions"
        and r.region_size_pages == region_size_pages
        and r.region_start_page == region_start_page
        and r.strategy in strategies
    ]

    rows.sort(key=lambda r: strategies.index(r.strategy))

    x = list(range(len(rows)))
    labels = [r.strategy for r in rows]
    original = [r.mapping_count for r in rows]
    refined = [r.permission_refined_mapping_count for r in rows]

    width = 0.38

    plt.figure(figsize=(10.5, 5.4))
    plt.bar([i - width / 2 for i in x], original, width=width, label="Original mappings")
    plt.bar([i + width / 2 for i in x], refined, width=width, label="After permission refinement")

    plt.yscale("log")
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Mapping entries (log scale)")
    plt.title(f"Permission-boundary refinement, region size {region_size_pages}")
    plt.grid(True, axis="y", which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def make_plots(results: List[WorkloadResult], output_dir: Path) -> None:
    plot_dir = output_dir / "plots"

    plot_amplification_for_workload(
        results,
        plot_dir / "fault_amplification_sparse_random_v3.png",
        workload="sparse_random",
        region_size_pages=10000,
    )

    plot_amplification_for_workload(
        results,
        plot_dir / "fault_amplification_cow_burst_v3.png",
        workload="cow_burst",
        region_size_pages=10000,
    )

    plot_loaded_pages_by_workload(
        results,
        plot_dir / "loaded_pages_binary_adaptive_limited_v3.png",
        strategy="binary_adaptive_limited",
        region_size_pages=10000,
    )

    plot_permission_refinement(
        results,
        plot_dir / "permission_refinement_v3.png",
        region_size_pages=10000,
    )


# ============================================================
# Experiment runner
# ============================================================

def default_region_sizes() -> List[int]:
    return [1000, 4096, 10000]


def default_region_starts() -> List[int]:
    return [0, 1, 7, 13, 64, 255]


def run_experiment(
    region_sizes: Sequence[int],
    region_starts: Sequence[int],
    max_page_size_pages: int,
    max_bap_chunk_pages: int,
    huge_page_size_pages: int,
    tlb_entries: int,
    split_density_threshold: float,
    seed: int,
    output_dir: Path,
    make_plot_files: bool,
) -> List[WorkloadResult]:
    all_results: List[WorkloadResult] = []

    for start in region_starts:
        for size in region_sizes:
            strategy_mappings = build_mappings(
                region_start_page=start,
                region_size_pages=size,
                max_page_size_pages=max_page_size_pages,
                max_bap_chunk_pages=max_bap_chunk_pages,
                huge_page_size_pages=huge_page_size_pages,
            )

            for workload_name, workload_fn in WORKLOADS.items():
                rng = random.Random(seed + 1000003 * size + 9176 * start + hash(workload_name) % 10000)
                touched_pages = workload_fn(size, rng)

                for strategy, mappings in strategy_mappings.items():
                    all_results.append(
                        evaluate_strategy_on_workload(
                            strategy=strategy,
                            mappings=mappings,
                            workload_name=workload_name,
                            touched_pages=touched_pages,
                            tlb_entries=tlb_entries,
                            split_density_threshold=split_density_threshold,
                        )
                    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_results_csv(all_results, output_dir / "workload_summary_v3.csv")
    write_selected_csv(all_results, output_dir / "selected_workload_comparison_v3.csv")

    if make_plot_files:
        make_plots(all_results, output_dir)

    print(f"[OK] Wrote workload summary: {output_dir / 'workload_summary_v3.csv'}")
    print(f"[OK] Wrote selected comparison: {output_dir / 'selected_workload_comparison_v3.csv'}")
    if make_plot_files:
        print(f"[OK] Wrote plots under: {output_dir / 'plots'}")

    return all_results


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Workload-aware Simulator v3 for Binary Adaptive Paging."
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the XOR/MSB lookup rule.",
    )

    parser.add_argument(
        "--max-validate-size",
        type=int,
        default=4096,
        help="Maximum region size for lookup validation.",
    )

    parser.add_argument(
        "--tlb-entries",
        type=int,
        default=64,
        help="Number of entries in the simplified TLB reach model.",
    )

    parser.add_argument(
        "--max-page-size-pages",
        type=int,
        default=512,
        help="Maximum page size for multi-size baselines, in base pages.",
    )

    parser.add_argument(
        "--max-bap-chunk-pages",
        type=int,
        default=512,
        help="Maximum chunk size for binary_adaptive_limited, in base pages.",
    )

    parser.add_argument(
        "--huge-page-size-pages",
        type=int,
        default=512,
        help="Huge-page size for huge_mixed, in base pages.",
    )

    parser.add_argument(
        "--split-density-threshold",
        type=float,
        default=0.25,
        help=(
            "If touched density inside a mapping is below this threshold, "
            "the adaptive model splits the mapping."
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for synthetic workloads.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results_v3"),
        help="Output directory.",
    )

    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Disable plot generation.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.validate:
        validate_bap_lookup(args.max_validate_size)

    run_experiment(
        region_sizes=default_region_sizes(),
        region_starts=default_region_starts(),
        max_page_size_pages=args.max_page_size_pages,
        max_bap_chunk_pages=args.max_bap_chunk_pages,
        huge_page_size_pages=args.huge_page_size_pages,
        tlb_entries=args.tlb_entries,
        split_density_threshold=args.split_density_threshold,
        seed=args.seed,
        output_dir=args.output_dir,
        make_plot_files=not args.no_plots,
    )


if __name__ == "__main__":
    main()
