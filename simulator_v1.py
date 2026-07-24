from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import matplotlib.pyplot as plt


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


def msb_position(x: int) -> int:
    if x <= 0:
        raise ValueError("msb_position is defined only for positive integers.")
    return x.bit_length() - 1


def binary_decomposition(size_pages: int) -> List[int]:
    """Decompose a positive integer into descending powers of two."""
    if size_pages <= 0:
        raise ValueError("Region size must be positive.")
    return [1 << k for k in range(msb_position(size_pages), -1, -1) if size_pages & (1 << k)]


def default_allowed_page_sizes(max_size_pages: int = 512) -> List[int]:
    """Return [512, 256, ..., 1] by default."""
    if max_size_pages <= 0 or (max_size_pages & (max_size_pages - 1)) != 0:
        raise ValueError("max_size_pages must be a positive power of two.")
    sizes: List[int] = []
    value = max_size_pages
    while value >= 1:
        sizes.append(value)
        value //= 2
    return sizes


def fixed_paging(region_start_page: int, region_size_pages: int) -> List[Mapping]:
    return [
        Mapping("fixed", region_start_page, region_size_pages, region_start_page + i, 1)
        for i in range(region_size_pages)
    ]


def huge_page_mixed(
    region_start_page: int,
    region_size_pages: int,
    huge_page_size_pages: int = 512,
) -> List[Mapping]:
    """Simple baseline: 512-page huge mappings plus 1-page remainder mappings."""
    mappings: List[Mapping] = []
    cursor = 0

    while region_size_pages - cursor >= huge_page_size_pages:
        mappings.append(
            Mapping("huge_mixed", region_start_page, region_size_pages, region_start_page + cursor, huge_page_size_pages)
        )
        cursor += huge_page_size_pages

    while cursor < region_size_pages:
        mappings.append(
            Mapping("huge_mixed", region_start_page, region_size_pages, region_start_page + cursor, 1)
        )
        cursor += 1

    return mappings


def multi_size_unaligned(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
) -> List[Mapping]:
    """
    Strong idealized baseline.

    Greedily covers the region using multiple power-of-two page sizes,
    without requiring absolute virtual alignment.

    Important: with [512, 256, ..., 1], this usually matches BAP in mapping count.
    That is useful because it tells us whether the contribution is raw mapping count
    or the XOR/MSB lookup and metadata organization.
    """
    mappings: List[Mapping] = []
    cursor = 0

    while cursor < region_size_pages:
        remaining = region_size_pages - cursor
        chosen = next((s for s in allowed_sizes if s <= remaining), None)
        if chosen is None:
            raise RuntimeError("No allowed page size can cover remaining region.")
        mappings.append(
            Mapping("multi_size_unaligned", region_start_page, region_size_pages, region_start_page + cursor, chosen)
        )
        cursor += chosen

    return mappings


def multi_size_aligned(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
) -> List[Mapping]:
    """
    More realistic multi-size baseline.

    Greedily chooses the largest page size that:
      1. fits the remaining region
      2. satisfies absolute virtual alignment: virtual_start_page % size == 0

    Size 1 always works, so this always covers the region.
    """
    mappings: List[Mapping] = []
    cursor = 0

    while cursor < region_size_pages:
        absolute_start = region_start_page + cursor
        remaining = region_size_pages - cursor
        chosen = next((s for s in allowed_sizes if s <= remaining and absolute_start % s == 0), None)
        if chosen is None:
            raise RuntimeError("No aligned page size can cover remaining region.")
        mappings.append(
            Mapping("multi_size_aligned", region_start_page, region_size_pages, absolute_start, chosen)
        )
        cursor += chosen

    return mappings


def binary_adaptive_paging(region_start_page: int, region_size_pages: int) -> List[Mapping]:
    """
    Binary Adaptive Paging.

    Decomposes the region into descending power-of-two chunks based on the
    binary representation of the region size.

    This model treats chunks as region-relative mappings. In a real OS/hardware
    design, this should be paired with a clear assumption about variable-size
    TLB entries or region metadata support.
    """
    mappings: List[Mapping] = []
    cursor = 0

    for chunk_size in binary_decomposition(region_size_pages):
        mappings.append(
            Mapping("binary_adaptive", region_start_page, region_size_pages, region_start_page + cursor, chunk_size)
        )
        cursor += chunk_size

    assert cursor == region_size_pages
    return mappings


def bap_lookup(region_size_pages: int, address_offset_page: int) -> Tuple[int, int, int]:
    """
    XOR/MSB lookup rule.

    Returns:
      chunk_base, chunk_size, k
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


def naive_find_chunk(mappings: List[Mapping], address_offset_page: int) -> Mapping:
    for m in mappings:
        if m.relative_start_page <= address_offset_page < m.relative_start_page + m.size_pages:
            return m
    raise ValueError("Address is not covered by any mapping.")


def validate_bap_lookup(max_region_size_pages: int = 4096) -> None:
    for S in range(1, max_region_size_pages + 1):
        mappings = binary_adaptive_paging(0, S)
        for a in range(S):
            chunk_base, chunk_size, _ = bap_lookup(S, a)
            ref = naive_find_chunk(mappings, a)
            assert chunk_base == ref.relative_start_page, (
                f"Base mismatch: S={S}, a={a}, lookup={chunk_base}, ref={ref.relative_start_page}"
            )
            assert chunk_size == ref.size_pages, (
                f"Size mismatch: S={S}, a={a}, lookup={chunk_size}, ref={ref.size_pages}"
            )
    print(f"[OK] BAP lookup validated for region sizes 1..{max_region_size_pages} pages.")


def estimated_tlb_reach_pages(mappings: List[Mapping], tlb_entries: int) -> int:
    """Optimistic upper bound: TLB stores the largest mappings."""
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
        "fixed": "shift/mask; constant-time base-page lookup",
        "huge_mixed": "single huge size plus base pages",
        "multi_size_unaligned": "idealized multi-size; no alignment constraint",
        "multi_size_aligned": "multi-size with absolute virtual alignment",
        "binary_adaptive": "xor + msb + region metadata lookup",
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
    )


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
    Multiple starts expose alignment effects.
    0 is perfectly aligned. Non-zero starts simulate regions that do not begin
    at a large-page boundary.
    """
    return [0, 1, 7, 13, 64, 255]


def build_strategy_mappings(
    region_start_page: int,
    region_size_pages: int,
    allowed_sizes: Sequence[int],
) -> dict[str, List[Mapping]]:
    return {
        "fixed": fixed_paging(region_start_page, region_size_pages),
        "huge_mixed": huge_page_mixed(region_start_page, region_size_pages),
        "multi_size_unaligned": multi_size_unaligned(region_start_page, region_size_pages, allowed_sizes),
        "multi_size_aligned": multi_size_aligned(region_start_page, region_size_pages, allowed_sizes),
        "binary_adaptive": binary_adaptive_paging(region_start_page, region_size_pages),
    }


def write_summary_csv(rows: List[Metrics], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "strategy",
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
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "strategy": r.strategy,
                "region_start_page": r.region_start_page,
                "region_size_pages": r.region_size_pages,
                "mapping_count": r.mapping_count,
                "avg_mapping_size_pages": f"{r.avg_mapping_size_pages:.4f}",
                "largest_mapping_pages": r.largest_mapping_pages,
                "estimated_tlb_reach_pages": r.estimated_tlb_reach_pages,
                "internal_fragmentation_pages": r.internal_fragmentation_pages,
                "lookup_model": r.lookup_model,
            })


def write_selected_comparison_csv(rows: List[Metrics], output_file: Path) -> None:
    selected_sizes = [13, 19, 512, 513, 1000, 4096, 10000]
    selected_start = 0
    strategies = ["fixed", "huge_mixed", "multi_size_unaligned", "multi_size_aligned", "binary_adaptive"]
    by_key = {(r.region_start_page, r.region_size_pages, r.strategy): r for r in rows}

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["region_start_page", "region_size_pages"] + [f"{s}_mappings" for s in strategies]
        fieldnames += ["bap_reduction_vs_fixed_percent"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for size in selected_sizes:
            row = {"region_start_page": selected_start, "region_size_pages": size}
            if any((selected_start, size, s) not in by_key for s in strategies):
                continue
            for s in strategies:
                row[f"{s}_mappings"] = by_key[(selected_start, size, s)].mapping_count
            fixed_count = by_key[(selected_start, size, "fixed")].mapping_count
            bap_count = by_key[(selected_start, size, "binary_adaptive")].mapping_count
            row["bap_reduction_vs_fixed_percent"] = f"{100.0 * (1.0 - bap_count / fixed_count):.2f}"
            writer.writerow(row)


def plot_metric_by_region_size(
    rows: List[Metrics],
    output_file: Path,
    metric_name: str,
    ylabel: str,
    title: str,
    strategies: Sequence[str],
    region_start_page: int = 0,
    log_y: bool = False,
) -> None:
    filtered = [r for r in rows if r.region_start_page == region_start_page and r.strategy in strategies]
    plt.figure(figsize=(8.5, 5.2))
    for strategy in strategies:
        data = sorted([r for r in filtered if r.strategy == strategy], key=lambda r: r.region_size_pages)
        if not data:
            continue
        plt.plot(
            [r.region_size_pages for r in data],
            [getattr(r, metric_name) for r in data],
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


def plot_bap_reduction_vs_fixed(rows: List[Metrics], output_file: Path, region_start_page: int = 0) -> None:
    by_key = {(r.region_size_pages, r.strategy): r for r in rows if r.region_start_page == region_start_page}
    region_sizes = sorted({r.region_size_pages for r in rows if r.region_start_page == region_start_page})
    xs, ys = [], []
    for size in region_sizes:
        fixed = by_key.get((size, "fixed"))
        bap = by_key.get((size, "binary_adaptive"))
        if fixed and bap:
            xs.append(size)
            ys.append(100.0 * (1.0 - bap.mapping_count / fixed.mapping_count))
    plt.figure(figsize=(8.5, 5.2))
    plt.plot(xs, ys, marker="o")
    plt.xscale("log")
    plt.xlabel("Region size (base pages, log scale)")
    plt.ylabel("Mapping-entry reduction vs fixed paging (%)")
    plt.title("Binary Adaptive Paging metadata reduction")
    plt.grid(True, which="both", linewidth=0.5)
    plt.tight_layout()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def plot_selected_sizes_bar(rows: List[Metrics], output_file: Path, region_start_page: int = 0) -> None:
    selected_sizes = [13, 19, 1000, 4096, 10000]
    strategies = ["fixed", "huge_mixed", "multi_size_unaligned", "multi_size_aligned", "binary_adaptive"]
    by_key = {(r.region_size_pages, r.strategy): r for r in rows if r.region_start_page == region_start_page}
    x = list(range(len(selected_sizes)))
    width = 0.14

    plt.figure(figsize=(10, 5.5))
    for i, strategy in enumerate(strategies):
        values = [by_key[(size, strategy)].mapping_count for size in selected_sizes]
        shifted_x = [pos + (i - 2) * width for pos in x]
        plt.bar(shifted_x, values, width=width, label=strategy)

    plt.yscale("log")
    plt.xlabel("Region size (base pages)")
    plt.ylabel("Mapping entries (log scale)")
    plt.title("Strategy comparison on selected region sizes")
    plt.xticks(x, [str(s) for s in selected_sizes])
    plt.grid(True, which="both", axis="y", linewidth=0.5)
    plt.legend()
    plt.tight_layout()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=220)
    plt.close()


def make_plots(rows: List[Metrics], output_dir: Path) -> None:
    strategies = ["fixed", "huge_mixed", "multi_size_unaligned", "multi_size_aligned", "binary_adaptive"]
    plot_metric_by_region_size(
        rows, output_dir / "mapping_entries_by_region_size_v1.png",
        "mapping_count", "Mapping entries (log scale)", "Mapping entries by region size",
        strategies, region_start_page=0, log_y=True,
    )
    plot_metric_by_region_size(
        rows, output_dir / "estimated_tlb_reach_v1.png",
        "estimated_tlb_reach_pages", "Estimated TLB reach (base pages)",
        "Estimated TLB reach with fixed TLB entries", strategies, region_start_page=0, log_y=False,
    )
    plot_bap_reduction_vs_fixed(rows, output_dir / "bap_mapping_reduction_vs_fixed_v1.png", region_start_page=0)
    plot_selected_sizes_bar(rows, output_dir / "strategy_comparison_selected_sizes_v1.png", region_start_page=0)


def run_experiment(
    region_sizes: Sequence[int],
    region_starts: Sequence[int],
    allowed_sizes: Sequence[int],
    tlb_entries: int,
    output_dir: Path,
    make_plot_files: bool,
) -> List[Metrics]:
    rows: List[Metrics] = []
    for start in region_starts:
        for size in region_sizes:
            strategies = build_strategy_mappings(start, size, allowed_sizes)
            for strategy, mappings in strategies.items():
                rows.append(compute_metrics(strategy, start, size, mappings, tlb_entries))

    write_summary_csv(rows, output_dir / "summary_v1.csv")
    write_selected_comparison_csv(rows, output_dir / "selected_comparison_v1.csv")
    if make_plot_files:
        make_plots(rows, output_dir)
    print(f"[OK] Wrote summary to {output_dir / 'summary_v1.csv'}")
    print(f"[OK] Wrote selected comparison to {output_dir / 'selected_comparison_v1.csv'}")
    if make_plot_files:
        print(f"[OK] Wrote plots to {output_dir}")
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulator v1 for Binary Adaptive Paging.")
    parser.add_argument("--validate", action="store_true", help="Run exhaustive validation of XOR/MSB lookup.")
    parser.add_argument("--max-validate-size", type=int, default=4096)
    parser.add_argument("--tlb-entries", type=int, default=64)
    parser.add_argument("--max-multisize-page", type=int, default=512)
    parser.add_argument("--output-dir", type=Path, default=Path("results_v1"))
    parser.add_argument("--no-plots", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.validate:
        validate_bap_lookup(max_region_size_pages=args.max_validate_size)
    allowed_sizes = default_allowed_page_sizes(args.max_multisize_page)
    run_experiment(
        region_sizes=default_region_sizes(),
        region_starts=default_region_starts(),
        allowed_sizes=allowed_sizes,
        tlb_entries=args.tlb_entries,
        output_dir=args.output_dir,
        make_plot_files=not args.no_plots,
    )


if __name__ == "__main__":
    main()
