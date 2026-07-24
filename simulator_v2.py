from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt


# ============================================================
# Simulator v2 for Binary Adaptive Paging
# ============================================================
#
# Purpose of v2:
#   - Separate "fair comparison" from "upper-bound comparison".
#   - Add two BAP variants:
#       1. binary_adaptive_unbounded
#          Pure theoretical BAP. A region of 4096 pages may become one
#          4096-page chunk.
#
#       2. binary_adaptive_limited
#          Practical/fair BAP. It first applies BAP binary decomposition,
#          then splits chunks larger than max_bap_chunk_pages.
#          Example with max_bap_chunk_pages = 512:
#              4096 -> eight 512-page mappings
#              10000 -> 8192 + 1024 + 512 + 256 + 16
#                    -> 16*512 + 2*512 + 512 + 256 + 16
#                    -> 21 mappings
#
#   - Keep strong baselines:
#       fixed
#       huge_mixed
#       multi_size_unaligned
#       multi_size_aligned
#
# Main outputs:
#   summary_v2.csv
#   fair_comparison_start0_v2.csv
#   upper_bound_comparison_start0_v2.csv
#   alignment_effect_v2.csv
#   plots/*.png
#
# Important:
#   This is still not a full OS simulator. It does not model:
#       - copy-on-write
#       - swapping
#       - permission conflicts
#       - physical-contiguity failure
#       - page-fault amplification
#
# It is intended to support the early paper claim:
#   BAP can reduce mapping metadata compared with fixed paging, but fair
#   comparison requires matching maximum page/chunk sizes against multi-size
#   baselines.


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


@dataclass(frozen=True)
class Metrics:
    strategy: str
    region_start_page: int
    region_size_pages: int
    mapping_count: int
    avg_mapping_size_pages: float
    largest_mapping_pages: int
    estimated_tlb_reach_pages: int
    internal_fragmentation_pages: int
    lookup_model: str
    comparison_group: str


# ============================================================
# Utilities
# ============================================================

def msb_position(x: int) -> int:
    if x <= 0:
        raise ValueError("msb_position is defined only for positive integers.")
    return x.bit_length() - 1


def binary_decomposition(size_pages: int) -> List[int]:
    """
    Decompose an integer into descending powers of two.

    Examples:
        13 -> [8, 4, 1]
        19 -> [16, 2, 1]
        10000 -> [8192, 1024, 512, 256, 16]
    """
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

    sizes: List[int] = []
    value = max_size_pages
    while value >= 1:
        sizes.append(value)
        value //= 2
    return sizes


def split_chunk_by_cap(chunk_size: int, cap: int) -> List[int]:
    """
    Split one BAP logical chunk into physical mapping chunks no larger than cap.

    If chunk_size <= cap:
        return [chunk_size]

    Because both chunk_size and cap are powers of two in the intended use,
    chunk_size is divisible by cap when chunk_size > cap.
    """
    if cap <= 0:
        raise ValueError("Cap must be positive.")
    if chunk_size <= cap:
        return [chunk_size]

    full_count, remainder = divmod(chunk_size, cap)
    parts = [cap] * full_count
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
    """
    Simple huge-page baseline:
      - use huge_page_size_pages whenever possible
      - map remainder with base pages
    """
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
    """
    Idealized multi-size baseline.

    Greedily uses the largest page size that fits, without alignment constraints.
    This is a strong baseline and is intentionally generous.
    """
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
    """
    Alignment-constrained multi-size baseline.

    A page of size p may start only at an address divisible by p:
        virtual_start_page % p == 0

    This approximates the alignment restriction that large pages usually have.
    It still does not model physical-contiguity constraints.
    """
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
    """
    Pure theoretical BAP.

    Uses the exact binary decomposition of the region size, without limiting
    maximum chunk size.
    """
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
    """
    Fair/practical BAP.

    Step 1:
        Apply logical BAP binary decomposition.

    Step 2:
        If a logical BAP chunk is larger than max_bap_chunk_pages,
        split it into equal capped mappings.

    This makes BAP comparable to multi-size baselines with the same maximum
    mapping size.

    Note:
        The XOR/MSB rule identifies the logical BAP chunk. If that chunk was
        capped, an additional sub-index is needed inside the logical chunk.
        This is still a simple arithmetic step and should be reported clearly
        in the paper.
    """
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


# ============================================================
# BAP lookup validation
# ============================================================

def bap_lookup(region_size_pages: int, address_offset_page: int) -> Tuple[int, int, int]:
    """
    Pure unbounded BAP lookup.

    Given:
        S = region_size_pages
        a = address_offset_page

    Compute:
        x = a XOR S
        k = MSB(x)
        chunk_size = 2^k
        chunk_base = S with lower (k+1) bits cleared
    """
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


def bap_limited_lookup(
    region_size_pages: int,
    address_offset_page: int,
    max_bap_chunk_pages: int,
) -> Tuple[int, int, int, int]:
    """
    Limited BAP lookup.

    First applies pure BAP lookup to find the logical chunk.
    If the logical chunk is larger than the maximum allowed chunk size,
    it computes the capped physical subchunk.

    Returns:
        physical_chunk_base
        physical_chunk_size
        logical_chunk_base
        logical_chunk_size
    """
    logical_base, logical_size, _k = bap_lookup(region_size_pages, address_offset_page)

    if logical_size <= max_bap_chunk_pages:
        return logical_base, logical_size, logical_base, logical_size

    offset_inside_logical = address_offset_page - logical_base
    sub_index = offset_inside_logical // max_bap_chunk_pages

    physical_base = logical_base + sub_index * max_bap_chunk_pages
    physical_size = max_bap_chunk_pages

    return physical_base, physical_size, logical_base, logical_size


def naive_find_chunk(mappings: List[Mapping], address_offset_page: int) -> Mapping:
    for mapping in mappings:
        start = mapping.relative_start_page
        end = start + mapping.size_pages
        if start <= address_offset_page < end:
            return mapping
    raise ValueError("Address is not covered by any mapping.")


def validate_bap_lookup(max_region_size_pages: int) -> None:
    for S in range(1, max_region_size_pages + 1):
        mappings = binary_adaptive_unbounded(region_start_page=0, region_size_pages=S)

        for a in range(S):
            chunk_base, chunk_size, _k = bap_lookup(S, a)
            reference = naive_find_chunk(mappings, a)

            assert chunk_base == reference.relative_start_page, (
                f"Unbounded base mismatch: S={S}, a={a}, "
                f"lookup={chunk_base}, ref={reference.relative_start_page}"
            )
            assert chunk_size == reference.size_pages, (
                f"Unbounded size mismatch: S={S}, a={a}, "
                f"lookup={chunk_size}, ref={reference.size_pages}"
            )

    print(f"[OK] Unbounded BAP lookup validated for region sizes 1..{max_region_size_pages}.")


def validate_bap_limited_lookup(max_region_size_pages: int, max_bap_chunk_pages: int) -> None:
    for S in range(1, max_region_size_pages + 1):
        mappings = binary_adaptive_limited(
            region_start_page=0,
            region_size_pages=S,
            max_bap_chunk_pages=max_bap_chunk_pages,
        )

        for a in range(S):
            physical_base, physical_size, _logical_base, _logical_size = bap_limited_lookup(
                region_size_pages=S,
                address_offset_page=a,
                max_bap_chunk_pages=max_bap_chunk_pages,
            )
            reference = naive_find_chunk(mappings, a)

            assert physical_base == reference.relative_start_page, (
                f"Limited base mismatch: S={S}, a={a}, "
                f"lookup={physical_base}, ref={reference.relative_start_page}"
            )
            assert physical_size == reference.size_pages, (
                f"Limited size mismatch: S={S}, a={a}, "
                f"lookup={physical_size}, ref={reference.size_pages}"
            )

    print(
        f"[OK] Limited BAP lookup validated for region sizes 1..{max_region_size_pages} "
        f"with max chunk {max_bap_chunk_pages}."
    )


# ============================================================
# Metrics
# ============================================================

def estimated_tlb_reach_pages(mappings: List[Mapping], tlb_entries: int) -> int:
    """
    Optimistic TLB reach estimate:
      - assume the TLB keeps the largest mappings
      - sum how many base pages those mappings cover
    """
    sizes = sorted((m.size_pages for m in mappings), reverse=True)
    return sum(sizes[:tlb_entries])


def compute_metrics(
    strategy: str,
    region_start_page: int,
    region_size_pages: int,
    mappings: List[Mapping],
    tlb_entries: int,
) -> Metrics:
    mapping_count = len(mappings)
    mapped_pages = sum(m.size_pages for m in mappings)

    lookup_models = {
        "fixed": "shift/mask; base-page lookup",
        "huge_mixed": "huge/base page-table lookup",
        "multi_size_unaligned": "idealized greedy multi-size lookup",
        "multi_size_aligned": "greedy multi-size lookup with alignment constraint",
        "binary_adaptive_unbounded": "xor+msb logical chunk lookup",
        "binary_adaptive_limited": "xor+msb logical lookup plus capped subchunk index",
    }

    comparison_groups = {
        "fixed": "both",
        "huge_mixed": "both",
        "multi_size_unaligned": "fair",
        "multi_size_aligned": "fair",
        "binary_adaptive_limited": "fair",
        "binary_adaptive_unbounded": "upper_bound",
    }

    return Metrics(
        strategy=strategy,
        region_start_page=region_start_page,
        region_size_pages=region_size_pages,
        mapping_count=mapping_count,
        avg_mapping_size_pages=region_size_pages / mapping_count,
        largest_mapping_pages=max(m.size_pages for m in mappings),
        estimated_tlb_reach_pages=estimated_tlb_reach_pages(mappings, tlb_entries),
        internal_fragmentation_pages=mapped_pages - region_size_pages,
        lookup_model=lookup_models[strategy],
        comparison_group=comparison_groups[strategy],
    )


# ============================================================
# Experiment setup
# ============================================================

def default_region_sizes() -> List[int]:
    return [
        1, 2, 3, 4, 5, 7, 8, 9,
        13, 16, 19, 31, 32, 33,
        63, 64, 65, 127, 128, 129,
        255, 256, 257, 511, 512, 513,
        1000, 1024, 2048, 4096, 8192, 10000,
    ]


def default_region_starts() -> List[int]:
    """
    Used to test alignment effects.
    """
    return [0, 1, 7, 13, 64, 255]


def build_all_mappings(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
    max_bap_chunk_pages: int,
    huge_page_size_pages: int,
) -> dict[str, List[Mapping]]:
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
# CSV output
# ============================================================

def write_csv(rows: List[dict], output_file: Path, fieldnames: Sequence[str]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_summary_csv(metrics: List[Metrics], output_file: Path) -> None:
    rows = []
    for m in metrics:
        rows.append(
            {
                "strategy": m.strategy,
                "comparison_group": m.comparison_group,
                "region_start_page": m.region_start_page,
                "region_size_pages": m.region_size_pages,
                "mapping_count": m.mapping_count,
                "avg_mapping_size_pages": f"{m.avg_mapping_size_pages:.4f}",
                "largest_mapping_pages": m.largest_mapping_pages,
                "estimated_tlb_reach_pages": m.estimated_tlb_reach_pages,
                "internal_fragmentation_pages": m.internal_fragmentation_pages,
                "lookup_model": m.lookup_model,
            }
        )

    write_csv(
        rows,
        output_file,
        [
            "strategy",
            "comparison_group",
            "region_start_page",
            "region_size_pages",
            "mapping_count",
            "avg_mapping_size_pages",
            "largest_mapping_pages",
            "estimated_tlb_reach_pages",
            "internal_fragmentation_pages",
            "lookup_model",
        ],
    )


def metrics_index(metrics: List[Metrics]) -> dict[tuple[int, int, str], Metrics]:
    return {
        (m.region_start_page, m.region_size_pages, m.strategy): m
        for m in metrics
    }


def write_fair_comparison_csv(metrics: List[Metrics], output_file: Path) -> None:
    selected_sizes = [13, 19, 512, 513, 1000, 4096, 10000]
    selected_start = 0
    strategies = [
        "fixed",
        "huge_mixed",
        "multi_size_unaligned",
        "multi_size_aligned",
        "binary_adaptive_limited",
    ]

    idx = metrics_index(metrics)
    rows = []

    for size in selected_sizes:
        row = {
            "region_start_page": selected_start,
            "region_size_pages": size,
        }

        missing = False
        for strategy in strategies:
            metric = idx.get((selected_start, size, strategy))
            if metric is None:
                missing = True
                break
            row[f"{strategy}_mappings"] = metric.mapping_count

        if missing:
            continue

        fixed = idx[(selected_start, size, "fixed")].mapping_count
        bap = idx[(selected_start, size, "binary_adaptive_limited")].mapping_count

        row["bap_limited_reduction_vs_fixed_percent"] = f"{100.0 * (1.0 - bap / fixed):.2f}"
        rows.append(row)

    write_csv(
        rows,
        output_file,
        [
            "region_start_page",
            "region_size_pages",
            "fixed_mappings",
            "huge_mixed_mappings",
            "multi_size_unaligned_mappings",
            "multi_size_aligned_mappings",
            "binary_adaptive_limited_mappings",
            "bap_limited_reduction_vs_fixed_percent",
        ],
    )


def write_upper_bound_comparison_csv(metrics: List[Metrics], output_file: Path) -> None:
    selected_sizes = [13, 19, 512, 513, 1000, 4096, 10000]
    selected_start = 0
    strategies = [
        "fixed",
        "huge_mixed",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    idx = metrics_index(metrics)
    rows = []

    for size in selected_sizes:
        row = {
            "region_start_page": selected_start,
            "region_size_pages": size,
        }

        missing = False
        for strategy in strategies:
            metric = idx.get((selected_start, size, strategy))
            if metric is None:
                missing = True
                break
            row[f"{strategy}_mappings"] = metric.mapping_count

        if missing:
            continue

        fixed = idx[(selected_start, size, "fixed")].mapping_count
        bap_unbounded = idx[(selected_start, size, "binary_adaptive_unbounded")].mapping_count

        row["bap_unbounded_reduction_vs_fixed_percent"] = f"{100.0 * (1.0 - bap_unbounded / fixed):.2f}"
        rows.append(row)

    write_csv(
        rows,
        output_file,
        [
            "region_start_page",
            "region_size_pages",
            "fixed_mappings",
            "huge_mixed_mappings",
            "binary_adaptive_limited_mappings",
            "binary_adaptive_unbounded_mappings",
            "bap_unbounded_reduction_vs_fixed_percent",
        ],
    )


def write_alignment_effect_csv(metrics: List[Metrics], output_file: Path) -> None:
    """
    Compare aligned multi-size baseline against BAP variants for different starts.
    """
    selected_sizes = [1000, 4096, 10000]
    selected_starts = default_region_starts()
    strategies = [
        "multi_size_unaligned",
        "multi_size_aligned",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    idx = metrics_index(metrics)
    rows = []

    for size in selected_sizes:
        for start in selected_starts:
            row = {
                "region_start_page": start,
                "region_size_pages": size,
            }

            missing = False
            for strategy in strategies:
                metric = idx.get((start, size, strategy))
                if metric is None:
                    missing = True
                    break
                row[f"{strategy}_mappings"] = metric.mapping_count

            if missing:
                continue

            aligned = idx[(start, size, "multi_size_aligned")].mapping_count
            unaligned = idx[(start, size, "multi_size_unaligned")].mapping_count
            row["alignment_penalty_entries"] = aligned - unaligned
            rows.append(row)

    write_csv(
        rows,
        output_file,
        [
            "region_start_page",
            "region_size_pages",
            "multi_size_unaligned_mappings",
            "multi_size_aligned_mappings",
            "binary_adaptive_limited_mappings",
            "binary_adaptive_unbounded_mappings",
            "alignment_penalty_entries",
        ],
    )


# ============================================================
# Plotting
# ============================================================

def plot_metric_by_size(
    metrics: List[Metrics],
    output_file: Path,
    strategies: Sequence[str],
    metric_attr: str,
    title: str,
    ylabel: str,
    region_start_page: int = 0,
    log_y: bool = False,
) -> None:
    plt.figure(figsize=(8.8, 5.3))

    for strategy in strategies:
        data = sorted(
            [
                m for m in metrics
                if m.region_start_page == region_start_page and m.strategy == strategy
            ],
            key=lambda m: m.region_size_pages,
        )

        if not data:
            continue

        plt.plot(
            [m.region_size_pages for m in data],
            [getattr(m, metric_attr) for m in data],
            marker="o",
            label=strategy,
        )

    plt.xscale("log")
    if log_y:
        plt.yscale("log")

    plt.xlabel("Region size (base pages, log scale)")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_alignment_effect(
    metrics: List[Metrics],
    output_file: Path,
    region_size_pages: int = 10000,
) -> None:
    strategies = [
        "multi_size_unaligned",
        "multi_size_aligned",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    plt.figure(figsize=(8.8, 5.3))

    for strategy in strategies:
        data = sorted(
            [
                m for m in metrics
                if m.region_size_pages == region_size_pages and m.strategy == strategy
            ],
            key=lambda m: m.region_start_page,
        )

        if not data:
            continue

        plt.plot(
            [m.region_start_page for m in data],
            [m.mapping_count for m in data],
            marker="o",
            label=strategy,
        )

    plt.xlabel("Region start page")
    plt.ylabel("Mapping entries")
    plt.title(f"Alignment effect for region size {region_size_pages} pages")
    plt.grid(True, which="both", linewidth=0.5)
    plt.legend()
    plt.tight_layout()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def make_plots(metrics: List[Metrics], output_dir: Path) -> None:
    plot_dir = output_dir / "plots"

    fair_strategies = [
        "fixed",
        "huge_mixed",
        "multi_size_unaligned",
        "multi_size_aligned",
        "binary_adaptive_limited",
    ]

    upper_bound_strategies = [
        "fixed",
        "huge_mixed",
        "binary_adaptive_limited",
        "binary_adaptive_unbounded",
    ]

    plot_metric_by_size(
        metrics=metrics,
        output_file=plot_dir / "fair_mapping_entries_v2.png",
        strategies=fair_strategies,
        metric_attr="mapping_count",
        title="Fair comparison: mapping entries by region size",
        ylabel="Mapping entries (log scale)",
        log_y=True,
    )

    plot_metric_by_size(
        metrics=metrics,
        output_file=plot_dir / "upper_bound_mapping_entries_v2.png",
        strategies=upper_bound_strategies,
        metric_attr="mapping_count",
        title="Upper-bound comparison: unbounded BAP",
        ylabel="Mapping entries (log scale)",
        log_y=True,
    )

    plot_metric_by_size(
        metrics=metrics,
        output_file=plot_dir / "fair_tlb_reach_v2.png",
        strategies=fair_strategies,
        metric_attr="estimated_tlb_reach_pages",
        title="Fair comparison: estimated TLB reach",
        ylabel="Estimated TLB reach (base pages)",
        log_y=False,
    )

    plot_alignment_effect(
        metrics=metrics,
        output_file=plot_dir / "alignment_effect_10000_v2.png",
        region_size_pages=10000,
    )


# ============================================================
# Experiment runner
# ============================================================

def run_experiment(
    region_sizes: Sequence[int],
    region_starts: Sequence[int],
    max_page_size_pages: int,
    max_bap_chunk_pages: int,
    huge_page_size_pages: int,
    tlb_entries: int,
    output_dir: Path,
    make_plot_files: bool,
) -> List[Metrics]:
    allowed_sizes = descending_powers_of_two(max_page_size_pages)

    all_metrics: List[Metrics] = []

    for start in region_starts:
        for size in region_sizes:
            mapping_sets = build_all_mappings(
                region_start_page=start,
                region_size_pages=size,
                allowed_sizes=allowed_sizes,
                max_bap_chunk_pages=max_bap_chunk_pages,
                huge_page_size_pages=huge_page_size_pages,
            )

            for strategy, mappings in mapping_sets.items():
                all_metrics.append(
                    compute_metrics(
                        strategy=strategy,
                        region_start_page=start,
                        region_size_pages=size,
                        mappings=mappings,
                        tlb_entries=tlb_entries,
                    )
                )

    output_dir.mkdir(parents=True, exist_ok=True)

    write_summary_csv(all_metrics, output_dir / "summary_v2.csv")
    write_fair_comparison_csv(all_metrics, output_dir / "fair_comparison_start0_v2.csv")
    write_upper_bound_comparison_csv(all_metrics, output_dir / "upper_bound_comparison_start0_v2.csv")
    write_alignment_effect_csv(all_metrics, output_dir / "alignment_effect_v2.csv")

    if make_plot_files:
        make_plots(all_metrics, output_dir)

    print(f"[OK] Wrote summary: {output_dir / 'summary_v2.csv'}")
    print(f"[OK] Wrote fair comparison: {output_dir / 'fair_comparison_start0_v2.csv'}")
    print(f"[OK] Wrote upper-bound comparison: {output_dir / 'upper_bound_comparison_start0_v2.csv'}")
    print(f"[OK] Wrote alignment effect: {output_dir / 'alignment_effect_v2.csv'}")
    if make_plot_files:
        print(f"[OK] Wrote plots under: {output_dir / 'plots'}")

    return all_metrics


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulator v2 for Binary Adaptive Paging."
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation for unbounded and limited BAP lookup.",
    )

    parser.add_argument(
        "--max-validate-size",
        type=int,
        default=4096,
        help="Maximum region size for exhaustive validation.",
    )

    parser.add_argument(
        "--tlb-entries",
        type=int,
        default=64,
        help="Number of TLB entries for the simplified TLB reach model.",
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
        help="Huge-page size for huge_mixed baseline, in base pages.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results_v2"),
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
        validate_bap_limited_lookup(
            max_region_size_pages=args.max_validate_size,
            max_bap_chunk_pages=args.max_bap_chunk_pages,
        )

    run_experiment(
        region_sizes=default_region_sizes(),
        region_starts=default_region_starts(),
        max_page_size_pages=args.max_page_size_pages,
        max_bap_chunk_pages=args.max_bap_chunk_pages,
        huge_page_size_pages=args.huge_page_size_pages,
        tlb_entries=args.tlb_entries,
        output_dir=args.output_dir,
        make_plot_files=not args.no_plots,
    )


if __name__ == "__main__":
    main()
